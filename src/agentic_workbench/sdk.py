"""Public host SDK. Approval and permission objects stay outside model context."""

from __future__ import annotations

import copy
import os
import stat
import tomllib
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .agents import AgentRuntime, Budget, Intents
from .changes import ChangeWorkflow
from .config import DEFAULT_CONFIG, Config
from .context import ContextManager
from .errors import WorkbenchError
from .execution import (
    ExecutionContext,
    ExecutionLimits,
    Harness,
    Observation,
    Plan,
    PlanRequest,
    Step,
    Verification,
    VerificationRequest,
)
from .models import Grant, canonical_hash, canonical_json, strict_json, text_hash
from .orchestrator import Node, Orchestrator
from .policy import WorkspacePolicy
from .providers import EmbeddingProvider, Provider, ProviderRegistry
from .repository import RepositoryIndex
from .retrieval import VectorIndex
from .skills import SkillRegistry
from .state import StateStore
from .tool_registry import ToolRegistry
from .tools import ReadTools

if TYPE_CHECKING:
    from .index_cache import IncrementalIndexCache
    from .typescript import TypeScriptAnalyzer


def _read_config(policy: WorkspacePolicy) -> Config:
    path = policy.root / ".agentic" / "config.toml"
    if os.name == "posix":
        with policy.directory((".agentic",)) as parent:
            try:
                fd = os.open(
                    "config.toml", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent
                )
            except FileNotFoundError:
                return Config()
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 1_048_576:
                    raise WorkbenchError("POLICY_DENIED", "Unsafe configuration file")
                data = os.read(fd, 1_048_577)
                after = os.fstat(fd)
                if (info.st_ino, info.st_size, info.st_mtime_ns) != (
                    after.st_ino,
                    after.st_size,
                    after.st_mtime_ns,
                ):
                    raise WorkbenchError("CONFLICT", "Configuration changed while reading")
            finally:
                os.close(fd)
    else:
        if path.resolve() != path or path.is_symlink():
            raise WorkbenchError("POLICY_DENIED", "Unsafe configuration alias")
        if not path.exists():
            return Config()
        if path.stat().st_size > 1_048_576 or path.stat().st_nlink != 1:
            raise WorkbenchError("POLICY_DENIED", "Unsafe configuration file")
        data = path.read_bytes()
    try:
        return Config.from_dict(tomllib.loads(data.decode("utf-8")))
    except (UnicodeError, tomllib.TOMLDecodeError) as error:
        raise WorkbenchError("CONFIG_ERROR", "Invalid configuration TOML") from error


class Workbench:
    def __init__(
        self,
        root: Path | str,
        config: Config | None = None,
        *,
        grants: Grant | None = None,
        provider: Provider | None = None,
        provider_registry: ProviderRegistry | None = None,
        skill_directories: list[Path] | None = None,
        external_skill_scopes: tuple[Path, ...] = (),
        configure_tools: Callable[[ToolRegistry], None] | None = None,
        index_cache: IncrementalIndexCache | None = None,
        typescript_analyzer: TypeScriptAnalyzer | None = None,
    ) -> None:
        bootstrap = WorkspacePolicy(root, config, grants=grants)
        bootstrap.prepare_state_dir()
        self.policy = WorkspacePolicy(
            bootstrap.root, config or _read_config(bootstrap), grants=grants
        )
        self.store = StateStore(self.policy)
        self._provider_override = provider
        self._provider_registry = provider_registry
        self._skill_directories = skill_directories
        self._external_skill_scopes = external_skill_scopes
        self._configure_tools = configure_tools
        from .index_cache import IncrementalIndexCache

        self.index_cache = index_cache if index_cache is not None else IncrementalIndexCache()
        self.typescript_analyzer = typescript_analyzer
        self._structure_key: str | None = None
        self._structure: dict[str, Any] | None = None
        self._index: RepositoryIndex | None = None
        self.changes = ChangeWorkflow(
            self.policy, self.store, skill_pins=lambda: [s.pin() for s in self._registry().skills]
        )

    def close(self) -> None:
        self.store.close()

    def __enter__(self) -> Workbench:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _registry(self) -> SkillRegistry:
        return SkillRegistry(
            self.policy,
            directories=self._skill_directories,
            external_scopes=self._external_skill_scopes,
        )

    def _scan(self) -> RepositoryIndex:
        self._index = self.index_cache.refresh(self.policy, self.store)
        typed_sources = {
            path: source
            for path, source in self._index.files.items()
            if Path(path).suffix in {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts"}
        }
        if self.typescript_analyzer is not None and typed_sources:
            key = canonical_hash(
                {
                    "parser": self.typescript_analyzer.fingerprint,
                    "sources": {
                        path: [source.source_hash, text_hash(source.text), source.contains_secrets]
                        for path, source in sorted(typed_sources.items())
                    },
                }
            )
            reused = self._structure_key == key and self._structure is not None
            if reused:
                self.typescript_analyzer.verify()
            else:
                self._structure = self.typescript_analyzer.analyze(typed_sources)
                self._structure_key = key
            assert self._structure is not None
            structure = copy.deepcopy(self._structure)
            for name in ("symbols", "calls", "imports", "references"):
                getattr(self._index, name).extend(structure.pop(name))
            self._index.structural = {**structure, "reused": reused}
        else:
            self._index.structural = {
                "status": "not-configured" if typed_sources else "not-needed",
                "coverage": {"unparsed_files": len(typed_sources)},
                "limitations": [
                    "TypeScript/JavaScript structure requires a trusted host-selected parser."
                ]
                if typed_sources
                else [],
            }
        projection = self._index.to_dict()
        # Request-local reuse counters are observability, not persisted source identity.
        projection.pop("cache_stats", None)
        projection["structural"] = {
            key: value for key, value in self._index.structural.items() if key != "reused"
        }
        if len(canonical_json(projection).encode()) <= 1_048_576:
            try:
                existing = self.store.load("index", "current")
                if existing is None:
                    self.store.save("index", "current", projection)
                elif canonical_hash(existing) != canonical_hash(projection):
                    self.store.update("index", "current", projection)
            except (WorkbenchError, ValueError, TypeError, RecursionError):
                # This optional projection never decides source or execution authority.
                self._index.cache_stats["projection_unavailable"] = 1
        return self._index

    def _provider(self) -> Provider | None:
        if self._provider_override is not None:
            return self._provider_override
        if self.policy.config.provider.name == "none":
            return None
        if self._provider_registry is not None:
            return self._provider_registry.get(self.policy.config.provider.name)
        if self.policy.config.provider.name != "openai":
            raise WorkbenchError(
                "INTEGRATION_UNAVAILABLE", "Pass a trusted provider adapter to the SDK"
            )
        from .providers_openai import OpenAIProvider

        return OpenAIProvider(self.policy)

    def _runtime(self) -> AgentRuntime:
        index = self._scan()
        return AgentRuntime(
            self.policy,
            index,
            self.store,
            self._registry(),
            self.changes,
            self._provider(),
            tool_registry=self.tools(index=index) if self._configure_tools else None,
        )

    def tools(self, *, index: RepositoryIndex | None = None) -> ToolRegistry:
        """Build a source-pinned registry; extensions come only from trusted host code."""
        registry = ToolRegistry(self.policy, self.store)
        registry.register_read_tools(ReadTools(self.policy, index or self._scan(), self.store))
        if self._configure_tools:
            self._configure_tools(registry)
        return registry

    def impact(self, changed_paths: list[str], *, limit: int = 20) -> dict[str, Any]:
        from .impact import impact

        index = self._scan()
        result = impact(index, changed_paths, limit)
        if not index.current_relationships(self.policy):
            raise WorkbenchError("STALE", "Source changed before impact analysis; rebuild index")
        return result

    def context(
        self, query: str, *, role: str = "engineering", changed_paths: list[str] | None = None
    ) -> dict[str, Any]:
        index = self._scan()
        return ContextManager(self.policy, index, self.store).build(
            query,
            role=role,
            changed_paths=changed_paths,
            skills=self._registry().select(role, index.frameworks, index.languages),
        )

    def remember_decision(
        self,
        task_id: str,
        text: str,
        evidence: list[dict[str, Any]],
        *,
        critical: bool = False,
        supersedes: str | None = None,
    ) -> dict[str, Any]:
        return ContextManager(self.policy, self._scan(), self.store).remember_decision(
            task_id, text, evidence, critical=critical, supersedes=supersedes
        )

    def decisions(self, query: str) -> list[dict[str, Any]]:
        return ContextManager(self.policy, self._scan(), self.store).decisions(query)

    def harness(
        self,
        *,
        planner: Callable[[PlanRequest], Plan],
        executor: Callable[[Step, ExecutionContext], Observation],
        verifier: Callable[[VerificationRequest], Verification],
        pins: dict[str, Any],
        limits: ExecutionLimits | None = None,
        replay_safe_actions: frozenset[str] = frozenset(),
    ) -> Harness:
        """Construct the execution controller with explicit trusted host callbacks."""
        return Harness(
            self.store,
            planner=planner,
            executor=executor,
            verifier=verifier,
            pins=pins,
            limits=limits,
            replay_safe_actions=replay_safe_actions,
        )

    def execute(
        self,
        instruction: str,
        *,
        proposal_id: str | None = None,
        command_id: str | None = None,
        approval: str | None = None,
        test_approval: str | None = None,
        backend: str = "docker",
        task_id: str | None = None,
    ) -> dict[str, Any]:
        """Run source analysis or an exactly approved change with a required check."""
        from .workflows import execute

        return execute(
            self,
            instruction,
            proposal_id=proposal_id,
            command_id=command_id,
            approval=approval,
            test_approval=test_approval,
            backend=backend,
            task_id=task_id,
        )

    def repair(
        self,
        instruction: str,
        *,
        command_id: str,
        edit_paths: list[str],
        baseline_approval: str | None = None,
        approval: str | None = None,
        test_approval: str | None = None,
        backend: str = "docker",
        task_id: str | None = None,
        max_attempts: int = 2,
    ) -> dict[str, Any]:
        """Reproduce a failing configured command, then try bounded approved candidate fixes."""
        from .repair import repair

        return repair(
            self,
            instruction,
            command_id=command_id,
            edit_paths=edit_paths,
            baseline_approval=baseline_approval,
            approval=approval,
            test_approval=test_approval,
            backend=backend,
            task_id=task_id,
            max_attempts=max_attempts,
        )

    def cancel(self, task_id: str) -> dict[str, Any]:
        cancelled = self.store.cancel_tree(task_id)
        return {
            "task_id": task_id,
            "cancelled_tasks": cancelled,
            "task": self.store.get_task(task_id),
        }

    def trace(self, task_id: str) -> dict[str, Any]:
        task = self.store.get_task(task_id)
        return {
            "task_id": task_id,
            "state": task["state"],
            "events": self.store.task_events(task_id),
            "phases": [
                r["value"]
                for r in self.store.list_records("execution_trace")
                if r["value"]["task_id"] == task_id
            ],
            "resources": self.store.resource_usage(task["root_id"]),
        }

    def init(self) -> dict[str, Any]:
        directory = self.policy.prepare_state_dir()
        created = False
        if os.name == "posix":
            with self.policy.directory((".agentic",)) as parent:
                try:
                    fd = os.open(
                        "config.toml",
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                        0o600,
                        dir_fd=parent,
                    )
                except FileExistsError:
                    _read_config(self.policy)
                else:
                    try:
                        os.write(fd, DEFAULT_CONFIG.encode())
                        os.fsync(fd)
                    finally:
                        os.close(fd)
                    os.fsync(parent)
                    created = True
        else:
            target = directory / "config.toml"
            if target.exists():
                _read_config(self.policy)
            else:
                with target.open("x", encoding="utf-8") as output:
                    output.write(DEFAULT_CONFIG)
                created = True
        return {
            "workspace_id": self.policy.workspace_id,
            "state_directory": str(directory),
            "configuration_created": created,
            "provider": "none",
            "permissions": asdict(self.policy.grants),
        }

    def scan(self) -> dict[str, Any]:
        runtime = self._runtime()
        # Discovery remains offline even if a provider is configured.
        runtime.provider = None
        result = runtime.run("discovery", "Inventory repository architecture and dependencies")
        return {**runtime.index.to_dict(), "task_id": result["task_id"], "result": result}

    def run_agent(self, role: str, instruction: str) -> dict[str, Any]:
        return self._runtime().run(role, instruction)

    def explain(self, target: str) -> dict[str, Any]:
        return self.run_agent("intelligence", target)

    def orchestrate(self, instruction: str, nodes: list[Node] | None = None) -> dict[str, Any]:
        return Orchestrator(self._runtime()).execute(instruction, nodes)

    def plan(self, instruction: str, *, proposal: dict[str, Any] | None = None) -> dict[str, Any]:
        if proposal is not None:
            if (
                not isinstance(proposal, dict)
                or set(proposal) - {"schema_version", "rationale", "edits", "evidence"}
                or not {"schema_version", "rationale", "edits"} <= set(proposal)
                or type(proposal["schema_version"]) is not int
                or proposal["schema_version"] != 1
            ):
                raise WorkbenchError("VALIDATION_ERROR", "Invalid imported proposal envelope")
        output = self.orchestrate(instruction)
        if proposal is not None:
            review = self.changes.propose(
                proposal["edits"],
                rationale=proposal["rationale"],
                instruction=instruction,
                evidence=proposal.get("evidence"),
                task_id=output["task_id"],
            )
            output["proposal_ids"].append(review["proposal_id"])
            output["proposals"].append(review)
        return output

    def propose(
        self,
        edits: list[dict[str, Any]],
        *,
        rationale: str,
        instruction: str = "",
        evidence: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return self.changes.propose(
            edits, rationale=rationale, instruction=instruction, evidence=evidence
        )

    def review(self, proposal_id: str) -> dict[str, Any]:
        return self.changes.review(proposal_id)

    def apply(
        self,
        proposal_id: str,
        *,
        approval: str | None = None,
        approve: Callable[[dict[str, Any]], bool] | None = None,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        review = self.review(proposal_id)
        if approve is not None and not dry_run:
            decision = approve(review)
            if type(decision) is not bool:
                raise WorkbenchError(
                    "VALIDATION_ERROR", "Host approval callbacks must return a boolean"
                )
            approval = review["digest"] if decision else None
        return self.changes.apply(proposal_id, approval=approval, dry_run=dry_run)

    def review_rollback(self, change_id: str) -> dict[str, Any]:
        return self.changes.review_rollback(change_id)

    def rollback(
        self, change_id: str, *, approval: str | None = None, dry_run: bool = True
    ) -> dict[str, Any]:
        return self.changes.rollback(change_id, approval=approval, dry_run=dry_run)

    def task_status(self, task_id: str) -> dict[str, Any]:
        return self.store.get_task(task_id)

    def resume(self, task_id: str) -> dict[str, Any]:
        self.store.interrupt_expired(300)
        task = self.store.get_task(task_id)
        if task["agent"] == "harness":
            options = self.store.load("execution-options", task_id)
            if options is not None:
                return self.execute(task["instruction"], task_id=task_id, **options)
            repair = self.store.load("repair", task_id)
            if repair is not None:
                return self.repair(task["instruction"], task_id=task_id, **repair["options"])
            raise WorkbenchError(
                "INTEGRATION_UNAVAILABLE", "Resume this execution with its trusted host harness"
            )
        runtime = self._runtime()
        workflow = self.store.load("workflow", task_id)
        if workflow is not None:
            nodes = [
                Node(n["id"], n["role"], tuple(n["dependencies"]), n.get("instruction"))
                for n in workflow["nodes"]
            ]
            return Orchestrator(runtime).execute(task["instruction"], nodes, root_id=task_id)
        self.store.resume(task_id, runtime.pins(task["agent"]))
        return runtime.run(task["agent"], task["instruction"], task_id=task_id)

    def search(
        self,
        query: str,
        *,
        semantic: bool = False,
        mode: str | None = None,
        dimensions: int = 256,
        limit: int = 5,
    ) -> dict[str, Any]:
        if (
            not isinstance(query, str)
            or not 1 <= len(query) <= 4096
            or type(semantic) is not bool
            or type(limit) is not int
            or not 1 <= limit <= 50
            or type(dimensions) is not int
            or not 1 <= dimensions <= 8192
        ):
            raise WorkbenchError("VALIDATION_ERROR", "Invalid bounded search request")
        if (
            (mode is not None and not isinstance(mode, str))
            or mode not in {None, "lexical", "semantic", "combined"}
            or (semantic and mode not in {None, "semantic"})
        ):
            raise WorkbenchError("VALIDATION_ERROR", "Contradictory or invalid retrieval mode")
        mode = mode or ("semantic" if semantic else "lexical")
        canonical_json(query)
        if self.policy.redactor.contains_secret(query):
            raise WorkbenchError("POLICY_DENIED", "Search queries cannot contain credentials")
        index = self._scan()
        if mode == "lexical":
            return {
                "mode": "lexical",
                "chunks": [c.to_dict() for c in index.search(query, limit, policy=self.policy)],
            }
        if not self.policy.grants.network:
            raise WorkbenchError("POLICY_DENIED", "Semantic search requires the host network grant")
        limits = self.policy.config.limits
        batch_rows = min(256, (limits.context_bytes - 2048) // (dimensions * 32 + 256))
        if batch_rows < 1 or limits.provider_requests < 2:
            raise WorkbenchError(
                "LIMIT_EXCEEDED",
                "Embedding dimensions require more response bytes and at least two requests",
            )
        provider = self._provider()
        if not isinstance(provider, EmbeddingProvider):
            raise WorkbenchError(
                "INTEGRATION_UNAVAILABLE", "Semantic search needs an embedding provider/model"
            )
        attached = getattr(provider, "policy", None)
        if isinstance(attached, WorkspacePolicy) and (
            attached.workspace_id != self.policy.workspace_id
            or attached.config.fingerprint != self.policy.config.fingerprint
        ):
            raise WorkbenchError(
                "POLICY_DENIED", "Embedding adapter is bound to a different policy"
            )
        profile = {
            "adapter": getattr(provider, "fingerprint", None)
            or f"{type(provider).__module__}.{type(provider).__qualname__}",
            "provider": self.policy.config.provider.name,
            "model": self.policy.config.provider.embedding_model,
            "dimensions": dimensions,
        }
        profile_id = canonical_hash(profile)
        task_id = self.store.create_task(
            "intelligence",
            "Semantic source retrieval",
            {"index": index.fingerprint, "embeddings": profile_id},
        )
        self.store.claim(task_id, "semantic-host")
        budget, intents = Budget(self.store, task_id), Intents(self.store, task_id)
        try:
            from .retrieval import lexical_search

            fresh = index.current_chunks(self.policy)
            ranked = lexical_search(fresh, query, 50)
            # Distribute remaining capacity across files, rather than one early file's chunks.
            candidates = ranked + sorted(
                fresh, key=lambda chunk: (chunk.evidence.start_line, chunk.evidence.path)
            )
            chunks = []
            size = 0
            seen: set[str] = set()
            for chunk in candidates:
                if chunk.id in seen:
                    continue
                seen.add(chunk.id)
                length = len(chunk.text.encode())
                if size + length <= min(8000, self.policy.config.limits.context_bytes // 2):
                    chunks.append(chunk)
                    size += length
                    if len(chunks) >= batch_rows * (limits.provider_requests - 1):
                        break
            if not chunks:
                raise WorkbenchError(
                    "VALIDATION_ERROR", "No source chunks fit the embedding budget"
                )
            identity = self.store.load("embedding-identity", profile_id)

            def cache_id(chunk_hash: str, metadata: dict[str, Any]) -> str:
                return canonical_hash(
                    {
                        "profile": profile_id,
                        **metadata,
                        "dimensions": dimensions,
                        "hash": chunk_hash,
                    }
                )

            def save(kind: str, identifier: str, value: dict[str, Any]) -> None:
                try:
                    self.store.save(kind, identifier, value)
                except WorkbenchError as error:
                    existing = self.store.load(kind, identifier)
                    if error.code != "CONFLICT" or canonical_hash(existing) != canonical_hash(
                        value
                    ):
                        raise

            rows: dict[str, dict[str, Any]] = {}
            unique = {text_hash(chunk.text): chunk for chunk in chunks}
            if identity is not None:
                for chunk_hash in unique:
                    cached = self.store.load("vectors", cache_id(chunk_hash, identity))
                    if cached is not None:
                        rows[chunk_hash] = cached
            cached_chunks = sum(text_hash(chunk.text) in rows for chunk in chunks)
            missing = [chunk for chunk_hash, chunk in unique.items() if chunk_hash not in rows]
            source_requests = 0
            if missing:
                for start in range(0, len(missing), batch_rows):
                    batch = missing[start : start + batch_rows]
                    if source_requests >= limits.provider_requests - 1:
                        raise WorkbenchError(
                            "LIMIT_EXCEEDED", "Embedding retries exhausted the query request budget"
                        )
                    response = provider.embed(
                        [c.text for c in batch],
                        chunk_hashes=[text_hash(c.text) for c in batch],
                        dimensions=dimensions,
                        source_grant=True,
                        budget=budget,
                        intents=intents,
                    )
                    source_requests += response.usage.requests
                    if len(response.vectors) != len(batch) or tuple(response.chunk_hashes) != tuple(
                        text_hash(c.text) for c in batch
                    ):
                        raise WorkbenchError(
                            "VALIDATION_ERROR", "Embeddings do not match source ordering"
                        )
                    returned_identity = {"provider": response.provider, "model": response.model}
                    if identity is not None and returned_identity != identity:
                        raise WorkbenchError("VALIDATION_ERROR", "Embedding batch metadata changed")
                    if (
                        self.policy.config.provider.embedding_model
                        and response.model != self.policy.config.provider.embedding_model
                    ):
                        raise WorkbenchError(
                            "VALIDATION_ERROR", "Embedding model differs from configuration"
                        )
                    validator = VectorIndex(response.provider, response.model, dimensions)
                    for chunk, vector in zip(batch, response.vectors, strict=True):
                        validator.add(chunk, list(vector), text_hash(chunk.text))
                    if identity is None:
                        identity = returned_identity
                        save("embedding-identity", profile_id, identity)
                    for chunk, vector in zip(batch, response.vectors, strict=True):
                        chunk_hash = text_hash(chunk.text)
                        row = {
                            **identity,
                            "dimensions": dimensions,
                            "hash": chunk_hash,
                            "vector": list(vector),
                        }
                        save("vectors", cache_id(chunk_hash, identity), row)
                        rows[chunk_hash] = row
            if identity is None:
                raise WorkbenchError("VALIDATION_ERROR", "Embedding source identity is unavailable")
            vectors = VectorIndex(identity["provider"], identity["model"], dimensions)
            for chunk in chunks:
                row = rows[text_hash(chunk.text)]
                if row["dimensions"] != dimensions or any(
                    row[key] != identity[key] for key in ("provider", "model")
                ):
                    raise WorkbenchError("STALE", "Cached vector metadata changed")
                vectors.add(chunk, row["vector"], row["hash"])
            embedding = provider.embed(
                [query],
                chunk_hashes=[text_hash(query)],
                dimensions=dimensions,
                source_grant=True,
                budget=budget,
                intents=intents,
            )
            if (
                len(embedding.vectors) != 1
                or embedding.provider != identity["provider"]
                or embedding.model != identity["model"]
                or tuple(embedding.chunk_hashes) != (text_hash(query),)
            ):
                raise WorkbenchError("VALIDATION_ERROR", "Query embedding metadata mismatch")
            current = index.current_chunks(self.policy, chunks)
            vector_ranked = vectors.search(list(embedding.vectors[0]), current, 50)
            if mode == "combined":
                from .retrieval import combine_rankings

                selected = combine_rankings(
                    lexical_search(current, query, 50), vector_ranked, limit
                )
            else:
                selected = vector_ranked[:limit]
            output = {
                "mode": mode,
                "task_id": task_id,
                "chunks": [c.to_dict() for c in selected],
                "indexed_chunks": len(chunks),
                "total_chunks": len(index.chunks),
                "coverage": {
                    "current_candidates": len(current),
                    "cached_chunks": cached_chunks,
                    "new_vectors": len(missing),
                    "selection": "lexical relevance followed by source diversity",
                },
                "usage": {"requests": source_requests + embedding.usage.requests},
                "limitations": [
                    "Real vector results rank a bounded candidate set selected by lexical "
                    "relevance and source diversity; indexed and total chunks report coverage."
                ],
            }
            self.store.transition(task_id, "running", "succeeded", result=output)
            return output
        except WorkbenchError as error:
            if self.store.cancelled(task_id):
                raise WorkbenchError(
                    "CANCELLED", "Semantic search was cancelled by the host"
                ) from error
            self.store.transition(task_id, "running", "failed", error=error.to_dict())
            raise
        except BaseException:
            if self.store.cancelled(task_id):
                raise WorkbenchError(
                    "CANCELLED", "Semantic search was cancelled by the host"
                ) from None
            self.store.transition(
                task_id,
                "running",
                "interrupted",
                error={"code": "INTERRUPTED", "message": "Retrieval interrupted"},
            )
            raise

    def test_review(self, command_id: str, *, backend: str = "docker") -> dict[str, Any]:
        from .runner import Runner

        return Runner(self.policy, self.store).review(command_id, backend)

    def cleanup_tests(self) -> list[dict[str, Any]]:
        from .runner import Runner

        return Runner(self.policy, self.store).cleanup_pending()

    def test(
        self,
        command_id: str,
        *,
        approval: str | None = None,
        backend: str = "docker",
        dry_run: bool = True,
    ) -> dict[str, Any]:
        from .runner import Runner

        runner = Runner(self.policy, self.store)
        if dry_run:
            return runner.review(command_id, backend)
        if approval is None:
            raise WorkbenchError("APPROVAL_REQUIRED", "Test execution requires a reviewed digest")
        return runner.execute(command_id, approval, backend)


def read_proposal_file(path: Path) -> dict[str, Any]:
    # Explicit host import paths may use OS parent aliases such as macOS /var.
    path = path.parent.resolve(strict=True) / path.name
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
        or path.is_symlink()
        or info.st_size > 1_048_576
    ):
        raise WorkbenchError("POLICY_DENIED", "Proposal import requires a bounded unaliased file")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    try:
        opened = os.fstat(fd)
        if (info.st_dev, info.st_ino) != (opened.st_dev, opened.st_ino):
            raise WorkbenchError("CONFLICT", "Proposal import identity changed")
        data = bytearray()
        while len(data) <= 1_048_576:
            block = os.read(fd, min(65536, 1_048_577 - len(data)))
            if not block:
                break
            data.extend(block)
        after = os.fstat(fd)
        if (info.st_size, info.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise WorkbenchError("CONFLICT", "Proposal import changed during read")
        value = strict_json(data.decode("utf-8"))
    finally:
        os.close(fd)
    if not isinstance(value, dict):
        raise WorkbenchError("VALIDATION_ERROR", "Proposal import requires an object")
    return value
