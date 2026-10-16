"""Eight independently callable roles using one guarded analysis runtime."""

from __future__ import annotations

import re
import uuid
from contextlib import suppress
from dataclasses import asdict
from threading import Event, Thread
from typing import TYPE_CHECKING, Any

from .changes import ChangeWorkflow
from .context import ContextManager
from .errors import WorkbenchError
from .models import (
    AgentResult,
    Evidence,
    Finding,
    Usage,
    canonical_hash,
    schema,
    validate,
)
from .policy import WorkspacePolicy
from .providers import Provider
from .repository import RepositoryIndex
from .retrieval import Chunk
from .skills import ROLES, SkillRegistry
from .state import StateStore
from .tools import ReadTools

if TYPE_CHECKING:
    from .tool_registry import ToolRegistry


class WorkerLease:
    """Keep a live local worker distinct from an abandoned execution claim."""

    def __init__(self, store: StateStore, task_id: str, owner: str, interval: float = 10) -> None:
        self.store, self.task_id, self.owner, self.interval = store, task_id, owner, interval
        self.stopped = Event()
        self.failure: WorkbenchError | None = None
        self.thread = Thread(target=self._renew, daemon=True)

    def _renew(self) -> None:
        while not self.stopped.wait(self.interval):
            try:
                self.store.heartbeat(self.task_id, self.owner)
            except WorkbenchError as error:
                self.failure = error
                return

    def start(self) -> None:
        self.thread.start()

    def check(self) -> None:
        if self.failure is not None:
            raise self.failure

    def close(self) -> None:
        self.stopped.set()
        self.thread.join(timeout=6)


class Budget:
    def __init__(self, store: StateStore, root_id: str) -> None:
        self.store, self.root_id = store, root_id

    def reserve(self, maximum: int) -> None:
        self.store.reserve(self.root_id, maximum)


class Intents:
    def __init__(self, store: StateStore, task_id: str) -> None:
        self.store, self.task_id = store, task_id

    def intent(self, kind: str, metadata: dict[str, Any]) -> str:
        identifier = self.store.intent(self.task_id, kind, metadata)
        try:
            self.store.event(self.task_id, "provider.dispatch", {"intent_id": identifier})
        except BaseException:
            # Nothing was dispatched yet; close the intent so it cannot block resume.
            with suppress(WorkbenchError):
                self.store.receipt(identifier, {"status": "not_dispatched"})
            raise
        return identifier

    def receipt(self, intent_id: str, metadata: dict[str, Any]) -> None:
        self.store.receipt(intent_id, metadata)

    def unknown(self, intent_id: str) -> None:
        self.store.unknown(intent_id)


def _targets(index: RepositoryIndex, instruction: str, chunks: list[Chunk]) -> list[str]:
    """Symbols the instruction names, else symbols defined inside lexically matched chunks."""
    if instruction in index.files:
        return list(dict.fromkeys(s["name"] for s in index.symbols_in(instruction)))[:5]
    names = {s["name"] for s in index.symbols}
    tokens = dict.fromkeys(re.findall(r"[A-Za-z_$][A-Za-z0-9_$]*", instruction))
    direct = [token for token in tokens if token in names]
    if direct:
        return direct[:5]
    spans = [(c.evidence.path, c.evidence.start_line, c.evidence.end_line) for c in chunks]
    overlapping = [
        s["name"]
        for s in index.symbols
        if any(
            s["evidence"]["path"] == path
            and s["evidence"]["start_line"] <= end
            and s["evidence"]["end_line"] >= start
            for path, start, end in spans
        )
    ]
    return list(dict.fromkeys(overlapping))[:5]


def _sites(entries: list[dict[str, Any]], limit: int = 10) -> str:
    cited = [e.get("evidence", e) for e in entries[:limit]]
    text = ", ".join(f"{e['path']}:{e['start_line']}" for e in cited)
    return text + (" …" if len(entries) > limit else "")


def _span(evidence: dict[str, Any]) -> str:
    return f"{evidence['path']}:{evidence['start_line']}-{evidence['end_line']}"


class AgentRuntime:
    def __init__(
        self,
        policy: WorkspacePolicy,
        index: RepositoryIndex,
        store: StateStore,
        registry: SkillRegistry,
        changes: ChangeWorkflow,
        provider: Provider | None = None,
        tool_registry: ToolRegistry | None = None,
    ) -> None:
        if tool_registry is not None and tool_registry.policy.fingerprint != policy.fingerprint:
            raise WorkbenchError("POLICY_DENIED", "Tool registry is bound to a different policy")
        self.policy, self.index, self.store = policy, index, store
        self.registry, self.changes, self.provider = registry, changes, provider
        self.tool_registry = tool_registry
        self.context = ContextManager(policy, index, store)

    def pins(self, role: str) -> dict[str, Any]:
        provider_pin = getattr(self.provider, "fingerprint", None)
        return {
            "contracts": canonical_hash(schema("AgentResult")),
            "index": self.index.fingerprint,
            "skills": [
                s.pin()
                for s in self.registry.select(role, self.index.frameworks, self.index.languages)
            ],
            "mode": "llm" if self.provider else "static",
            **(
                {"structural_parser": self.index.structural["parser"]}
                if self.index.structural.get("parser")
                else {}
            ),
            **({"tools": self.tool_registry.fingerprint} if self.tool_registry else {}),
            **({"model_routing": provider_pin} if isinstance(provider_pin, str) else {}),
        }

    def _check_cancelled(self, task_id: str, root_id: str) -> None:
        task = self.store.get_task(task_id)
        root = task if task_id == root_id else self.store.get_task(root_id)
        if task["state"] == "cancelled" or root["state"] == "cancelled":
            raise WorkbenchError("CANCELLED", "Agent execution was cancelled by the host")

    def run(
        self,
        role: str,
        instruction: str,
        *,
        task_id: str | None = None,
        root_id: str | None = None,
        parent_id: str | None = None,
        dependencies: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if (
            role not in ROLES
            or not isinstance(instruction, str)
            or not 1 <= len(instruction) <= 8192
        ):
            raise WorkbenchError("VALIDATION_ERROR", "Invalid role or instruction")
        if self.policy.redactor.contains_secret(instruction):
            raise WorkbenchError("POLICY_DENIED", "Task instructions cannot contain credentials")
        if task_id is None and root_id is not None:
            self._check_cancelled(root_id, root_id)
        task_id = task_id or self.store.create_task(
            role, instruction, self.pins(role), root_id, parent_id
        )
        task = self.store.get_task(task_id)
        self.verify_task(task, role, instruction)
        self._check_cancelled(task_id, task["root_id"])
        if task["state"] == "succeeded":
            return task["result"]  # type: ignore[no-any-return]
        owner = uuid.uuid4().hex
        if not self.store.claim(task_id, owner):
            raise WorkbenchError("CONFLICT", "Task is already owned or needs explicit resume")
        lease = WorkerLease(self.store, task_id, owner)
        lease.start()
        try:
            self._check_cancelled(task_id, task["root_id"])
            result = self._analyze(task_id, task["root_id"], role, instruction, dependencies or [])
            self._check_cancelled(task_id, task["root_id"])
            self.store.heartbeat(task_id, owner)
            result = self.policy.redactor.clean(result)
            validate("AgentResult", result)
            citations = result["evidence"] + [e for f in result["findings"] for e in f["evidence"]]
            if not all(
                self.index.current_evidence(self.policy, [Evidence(**e) for e in citations])
            ) or (
                self.index.structural.get("parser")
                and not self.index.current_relationships(self.policy)
            ):
                raise WorkbenchError("STALE", "Agent result cites unavailable or changed source")
            try:
                self.store.put_memory(
                    "episodic",
                    task_id,
                    {"agent": role, "summary": result["summary"], "index": self.index.fingerprint},
                )
                if citations:
                    unique = {canonical_hash(citation): citation for citation in citations}
                    self.context.remember_decision(
                        task_id, result["summary"], list(unique.values())[:50]
                    )
            except WorkbenchError:
                result["limitations"].append(
                    "Task memory was unavailable; use the saved task result."
                )
            lease.check()
            lease.close()
            self._check_cancelled(task_id, task["root_id"])
            self.store.transition(task_id, "running", "succeeded", result=result)
            return result  # type: ignore[no-any-return]
        except WorkbenchError as error:
            self._check_cancelled(task_id, task["root_id"])
            try:
                self.store.transition(task_id, "running", "failed", error=error.to_dict())
            except WorkbenchError:
                self._check_cancelled(task_id, task["root_id"])
                raise
            raise
        except BaseException:
            self._check_cancelled(task_id, task["root_id"])
            try:
                self.store.transition(
                    task_id,
                    "running",
                    "interrupted",
                    error={"code": "INTERRUPTED", "message": "Task stopped before completion"},
                )
            except WorkbenchError:
                self._check_cancelled(task_id, task["root_id"])
                raise
            raise
        finally:
            lease.close()

    def verify_task(
        self,
        task: dict[str, Any],
        role: str,
        instruction: str,
        additional_pins: dict[str, Any] | None = None,
    ) -> None:
        expected = {
            **self.pins(role),
            **(additional_pins or {}),
            "workspace_id": self.policy.workspace_id,
            "policy_fingerprint": self.policy.fingerprint,
        }
        if (
            task["agent"] != role
            or task["instruction"] != instruction
            or canonical_hash(task["pins"]) != canonical_hash(expected)
        ):
            raise WorkbenchError(
                "CONFLICT", "Task source, role, configuration or skill pins changed"
            )

    def _analyze(
        self,
        task_id: str,
        root_id: str,
        role: str,
        instruction: str,
        dependencies: list[dict[str, Any]],
    ) -> dict[str, Any]:
        skills = self.registry.select(role, self.index.frameworks, self.index.languages)
        if self.provider is not None:
            if not self.policy.grants.network:
                raise WorkbenchError(
                    "POLICY_DENIED", "Provider context requires this workspace's host network grant"
                )
            attached = getattr(self.provider, "policy", None)
            if isinstance(attached, WorkspacePolicy) and (
                attached.workspace_id != self.policy.workspace_id
                or attached.config.fingerprint != self.policy.config.fingerprint
            ):
                raise WorkbenchError(
                    "POLICY_DENIED",
                    "Provider adapter is bound to a different workspace or configuration",
                )
            required_tools = tuple(
                dict.fromkeys(tool for skill in skills for tool in skill.required_tools)
            )
            tools = (
                self.tool_registry.scoped(required_tools, task_id=task_id)
                if self.tool_registry is not None
                else ReadTools(
                    self.policy, self.index, self.store, allowed=required_tools, task_id=task_id
                )
            )
            measure = getattr(self.provider, "context_size", None)
            context = self.context.build(
                instruction,
                role=role,
                skills=skills,
                dependencies=dependencies,
                measure=(
                    (lambda value: measure(instruction, value, executor=tools))
                    if callable(measure)
                    else None
                ),
            )
            response = self.provider.analyze(
                instruction,
                context,
                executor=tools,
                budget=Budget(self.store, root_id),
                intents=Intents(self.store, task_id),
            )
            analysis = response.analysis
            validate("ModelAnalysis", analysis)
            findings = [
                Finding(
                    title=f["title"],
                    details=f["details"],
                    kind=f["kind"],
                    severity=f["severity"],
                    evidence=[Evidence(**e) for e in f["evidence"]],
                )
                for f in analysis["findings"]
            ]
            proposal_ids = []
            if analysis["candidate_edits"]:
                proposal = self.changes.propose(
                    analysis["candidate_edits"],
                    rationale=analysis["summary"],
                    task_id=task_id,
                    instruction=instruction,
                    evidence=[asdict(e) for f in findings for e in f.evidence],
                )
                proposal_ids.append(proposal["proposal_id"])
            return AgentResult(
                task_id,
                role,
                "llm",
                analysis["summary"],
                findings=findings,
                recommendations=analysis["recommendations"],
                proposal_ids=proposal_ids,
                limitations=analysis["limitations"],
                usage=response.usage,
            ).to_dict()
        return self._static(task_id, role, instruction)

    def _static(self, task_id: str, role: str, instruction: str) -> dict[str, Any]:
        index = self.index
        chunks = index.search(instruction[:4096], 5, policy=self.policy)
        if instruction in index.files:
            chunks = [c for c in index.chunks if c.evidence.path == instruction][:5]
        evidence = [c.evidence for c in chunks]
        frameworks = ", ".join(index.frameworks) or "no identified framework"
        languages = ", ".join(index.languages) or "no identified source language"
        findings: list[Finding] = []
        recommendations: list[str] = []
        limitations = ["Static analysis; runtime, visual QA and exploit validation are unverified."]
        if role == "discovery":
            summary = (
                f"Scanned {len(index.files)} text files ({index.coverage['bytes']} bytes). "
                f"Languages: {languages}. Frameworks: {frameworks}. "
                f"Dependency manifests: {len(index.manifests)}."
            )
            evidence = [Evidence(**m["evidence"]) for m in index.manifests[:20]]
        elif role == "intelligence":
            targets = _targets(index, instruction, chunks)
            traces = [index.trace(name) for name in targets]
            definitions = [d for t in traces for d in t["definitions"]]
            paths = {c.evidence.path for c in chunks} | {d["evidence"]["path"] for d in definitions}
            for trace in traces:
                name = trace["name"]
                for definition in trace["definitions"]:
                    findings.append(
                        Finding(
                            f"Definition of {name}",
                            f"{definition['kind']} at {_span(definition['evidence'])}.",
                            "fact",
                            evidence=[Evidence(**definition["evidence"])],
                        )
                    )
                if trace["callers"]:
                    call_title = f"Call sites naming {name}"
                    if any("target_id" in c for c in trace["callers"]):
                        call_title = f"Resolved call sites for {name}"
                    findings.append(
                        Finding(
                            call_title,
                            _sites(trace["callers"]),
                            "fact",
                            evidence=[Evidence(**c["evidence"]) for c in trace["callers"][:10]],
                        )
                    )
                if trace["callees"]:
                    findings.append(
                        Finding(
                            f"Calls inside {name}",
                            ", ".join(dict.fromkeys(c["callee"] for c in trace["callees"])),
                            "fact",
                            evidence=[Evidence(**c["evidence"]) for c in trace["callees"][:10]],
                        )
                    )
                for relationship in ("imports", "references"):
                    if trace[relationship]:
                        findings.append(
                            Finding(
                                f"Static {relationship} for {name}",
                                _sites(trace[relationship]),
                                "fact",
                                evidence=[
                                    Evidence(**row["evidence"]) for row in trace[relationship][:10]
                                ],
                            )
                        )
                if trace["tests"]:
                    findings.append(
                        Finding(
                            f"Tests mentioning {name}",
                            _sites(trace["tests"]),
                            "fact",
                            evidence=[Evidence(**e) for e in trace["tests"][:10]],
                        )
                    )
                else:
                    findings.append(
                        Finding(
                            f"No test mentions {name}",
                            "No file whose path contains 'test' references this name.",
                            "unknown",
                            "medium",
                        )
                    )
            test_paths = sorted({e["path"] for t in traces for e in t["tests"]})
            summary = (
                f"Traced {', '.join(targets) or 'no indexed symbol'}: "
                f"{len(definitions)} definitions, "
                f"{sum(len(t['callers']) for t in traces)} call sites, "
                f"{sum(len(t['tests']) for t in traces)} test references. "
                f"Relevant files: {', '.join(sorted(paths)) or 'no lexical match'}."
            )
            recommendations = [
                f"Reproduce the behavior with a focused assertion in {', '.join(test_paths)} "
                "before changing code."
                if test_paths
                else "Add a focused test that reproduces the behavior before changing code."
            ]
            evidence = [Evidence(**d["evidence"]) for d in definitions] + evidence
            limitations.append(
                "Python calls match source expressions; configured TypeScript resolves "
                "local aliases. "
                "Dynamic dispatch and external dependencies remain unresolved."
            )
        elif role == "engineering":
            targets = _targets(index, instruction, chunks)
            traces = [index.trace(name) for name in targets]
            definitions = [d for t in traces for d in t["definitions"]]
            definition_paths = sorted({d["evidence"]["path"] for d in definitions})
            caller_paths = sorted(
                {c["evidence"]["path"] for t in traces for c in t["callers"]}
                - set(definition_paths)
            )
            test_paths = sorted({e["path"] for t in traces for e in t["tests"]})
            affected = list(dict.fromkeys(definition_paths + caller_paths + test_paths)) or sorted(
                {c.evidence.path for c in chunks}
            )
            summary = (
                f"Change plan for: {instruction}. Affected files: "
                f"{', '.join(affected) or 'require target identification'}. "
                "Prepare complete replacements in a source-bound proposal and review its diff."
            )
            for trace in traces:
                for definition in trace["definitions"]:
                    findings.append(
                        Finding(
                            f"Edit target {trace['name']}",
                            f"{definition['kind']} at {_span(definition['evidence'])}; "
                            f"{len(trace['callers'])} call sites; "
                            f"{len(trace['tests'])} test references.",
                            "fact",
                            evidence=[Evidence(**definition["evidence"])],
                        )
                    )
            recommendations = [
                f"Change {', '.join(targets)} once at its definition in "
                f"{', '.join(definition_paths)}; call sites in "
                f"{', '.join(caller_paths) or 'no other file'} share it."
                if definitions
                else f"Inspect callers and contracts in {', '.join(affected) or 'the targets'}.",
                f"Add a regression in {', '.join(test_paths)} that fails on the reported issue."
                if test_paths
                else "Add a behavioral regression that fails on the reported issue.",
                "Review exact edits, apply with host approval, then run the approved test command.",
                "Keep the change journal for conflict-safe rollback.",
            ]
            evidence = [Evidence(**d["evidence"]) for d in definitions] + evidence
            limitations.append(
                "Import a proposal or use a provider for candidate code; static plans use evidence."
            )
        elif role == "architecture":
            summary = (
                f"Architecture inventory: {len(index.files)} text files, "
                f"{len(index.symbols)} indexed definitions, {len(index.calls)} source calls. "
                f"Stack evidence: {frameworks}."
            )
            for manifest in index.manifests[:10]:
                findings.append(
                    Finding(
                        "Dependency boundary",
                        f"{manifest['path']}: {len(manifest['dependencies'])} dependencies "
                        f"for {manifest['language']}.",
                        "fact",
                        evidence=[Evidence(**manifest["evidence"])],
                    )
                )
            recommendations = [
                "Review public module contracts and database/API boundaries in cited files.",
                "Measure throughput and resource use before proposing scaling changes.",
            ]
        elif role == "ux":
            inspected = 0
            for source in index.files.values():
                if source.path.endswith((".html", ".jsx", ".tsx", ".vue", ".svelte")):
                    inspected += 1
                    for match in re.finditer(r"<img\b[^>]*>", source.text, flags=re.IGNORECASE):
                        flags = 0 if source.path.endswith((".jsx", ".tsx")) else re.IGNORECASE
                        alt = (
                            r"\s(?::|v-bind:)?alt\s*="
                            if source.path.endswith(".vue")
                            else r"\salt\s*="
                        )
                        if not re.search(alt, match.group(), flags=flags):
                            line = source.text.count("\n", 0, match.start()) + 1
                            findings.append(
                                Finding(
                                    "Image lacks an explicit alt attribute",
                                    "This tag has no alt attribute. Choose descriptive text "
                                    "or an empty decorative alt after reviewing its purpose.",
                                    "fact",
                                    "medium",
                                    [
                                        Evidence(
                                            source.path,
                                            line,
                                            source.text.count("\n", 0, match.end()) + 1,
                                            source.source_hash,
                                        )
                                    ],
                                )
                            )
                            if len(findings) >= 20:
                                break
                    if len(findings) >= 20:
                        break
            summary = (
                f"Reviewed image tags in {inspected} interface files. "
                f"Found {len(findings)} tags without explicit alt attributes."
            )
            recommendations = [
                "Run keyboard, screen-reader, responsive and visual checks in the application."
            ]
        elif role == "testing":
            tests = [p for p in index.files if "test" in p.lower()][:30]
            command_names = ", ".join(self.policy.config.commands) or "none"
            targets = (
                _targets(index, instruction, chunks)
                or list(dict.fromkeys(s["name"] for s in index.symbols))[:10]
            )
            traced = {name: index.trace(name) for name in targets}
            covered = [name for name, trace in traced.items() if trace["tests"]]
            uncovered = [name for name in targets if name not in covered]
            for name in covered:
                findings.append(
                    Finding(
                        f"Tests mentioning {name}",
                        _sites(traced[name]["tests"]),
                        "fact",
                        evidence=[Evidence(**e) for e in traced[name]["tests"][:10]],
                    )
                )
            if uncovered:
                findings.append(
                    Finding(
                        "Symbols without test references",
                        ", ".join(uncovered),
                        "unknown",
                        "medium",
                    )
                )
            summary = (
                f"Detected test source: {', '.join(tests) or 'none'}. "
                f"Configured command IDs: {command_names}. "
                f"Test references found for {len(covered)} of {len(targets)} traced symbols."
            )
            recommendations = [
                f"Add assertions for {', '.join(uncovered)} covering normal behavior, "
                "boundary values and failures."
                if uncovered
                else "Cover normal behavior, boundary values and failures with regression checks.",
                "Configure an argv test command and review its snapshot/backend before execution.",
            ]
            evidence = [Evidence(**e) for n in covered for e in traced[n]["tests"]][:20] + evidence
        elif role == "documentation":
            manifest_names = ", ".join(m["path"] for m in index.manifests) or "none"
            api_names = ", ".join(s["name"] for s in index.symbols[:30]) or "none detected"
            summary = (
                f"# Source onboarding\n\nLanguages: {languages}. Frameworks: {frameworks}.\n\n"
                f"Dependency manifests: {manifest_names}. Install dependencies in an isolated "
                "environment after reviewing these manifests.\n\n"
                f"Indexed API definitions: {api_names}.\n\n"
                f"Configured test command IDs: {', '.join(self.policy.config.commands) or 'none'}. "
                "Use agentic test to review and approve execution.\n\n"
                "Deployment, authentication and infrastructure behavior require further evidence."
            )
            recommendations = [
                "Document setup from the actual dependency manifests and approved test commands.",
                "Explain cited entry points and unresolved deployment/authentication assumptions.",
            ]
        else:
            summary = (
                f"Available roles: {', '.join(ROLES)}. Source fingerprint: {index.fingerprint}. "
                f"Validated skills: {len(self.registry.skills)}. "
                "Coordination uses persisted dependency graphs and a shared provider budget."
            )
            recommendations = [
                "Use plan for discovery → analysis → engineering → testing/documentation, "
                "or supply a validated SDK graph."
            ]
        return AgentResult(
            task_id,
            role,
            "static",
            summary,
            evidence=evidence[:20],
            findings=findings,
            recommendations=recommendations,
            limitations=limitations,
            usage=Usage(),
        ).to_dict()
