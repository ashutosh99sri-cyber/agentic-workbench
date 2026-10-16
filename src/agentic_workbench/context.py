"""Bounded, cited context and host-recorded decisions; retrieved text is never authority."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from .errors import WorkbenchError
from .impact import select_impact_chunks, validate_paths
from .models import Evidence, canonical_json, validate
from .policy import WorkspacePolicy
from .repository import RepositoryIndex
from .retrieval import Chunk, tokens
from .skills import ROLES, Skill
from .state import StateStore


def _size(value: Any) -> int:
    return len(canonical_json(value).encode("utf-8"))


def _prefix(value: str, maximum: int) -> str:
    return value.encode("utf-8")[:maximum].decode("utf-8", errors="ignore")


def dependency_context(
    dependencies: list[dict[str, Any]], maximum: int, *, stale: set[str] | None = None
) -> tuple[list[dict[str, Any]], bool]:
    """Reserve all task identities before adding bounded summaries and whole citations."""
    for result in dependencies:
        validate("AgentResult", result)
    results = [
        {
            "task_id": result["task_id"],
            "agent": result["agent"],
            "truncated": True,
            **({"source_stale": True} if stale and result["task_id"] in stale else {}),
        }
        for result in dependencies
    ]
    if _size(results) > maximum:
        raise WorkbenchError("LIMIT_EXCEEDED", "Dependency identities exceed context byte limit")
    for position, result in enumerate(dependencies):
        identity = results[position]
        if identity.get("source_stale"):
            continue
        entry = {
            "task_id": result["task_id"],
            "agent": result["agent"],
            "summary": _prefix(result["summary"], 500),
            "findings": [
                {
                    **finding,
                    "details": _prefix(finding["details"], 500),
                    "evidence": finding["evidence"][:2],
                }
                for finding in result["findings"][:5]
            ],
            "evidence": result["evidence"][:5],
            "limitations": [_prefix(item, 200) for item in result["limitations"][:5]],
        }
        entry["truncated"] = any(entry[key] != result[key] for key in entry)
        results[position] = entry
        for key in ("evidence", "findings", "limitations"):
            while entry[key] and _size(results) > maximum:
                entry[key].pop()
                entry["truncated"] = True
        if _size(results) > maximum:
            entry["summary"] = ""
            entry["truncated"] = True
        if _size(results) > maximum:
            results[position] = identity
    return results, any(result["truncated"] for result in results)


class ContextManager:
    def __init__(self, policy: WorkspacePolicy, index: RepositoryIndex, store: StateStore) -> None:
        self.policy, self.index, self.store = policy, index, store

    def remember_decision(
        self,
        task_id: str,
        text: str,
        evidence: list[dict[str, Any]],
        *,
        critical: bool = False,
        supersedes: str | None = None,
    ) -> dict[str, Any]:
        """Host-recorded memory is immutable, source-bound and attributed to a real task."""
        if (
            not isinstance(text, str)
            or not text.strip()
            or type(critical) is not bool
            or not isinstance(evidence, list)
            or not 1 <= len(evidence) <= 50
        ):
            raise WorkbenchError("VALIDATION_ERROR", "Invalid decision memory")
        canonical_json(text)
        if len(text.encode("utf-8")) > 8192:
            raise WorkbenchError("LIMIT_EXCEEDED", "Decision memory exceeds text byte limit")
        task = self.store.get_task(task_id)
        for citation in evidence:
            validate("Evidence", citation)
        if not all(self.index.current_evidence(self.policy, [Evidence(**e) for e in evidence])):
            raise WorkbenchError("STALE", "Decision memory cites changed or unavailable source")
        if supersedes is not None and self.store.load("context-decision", supersedes) is None:
            raise WorkbenchError("VALIDATION_ERROR", "Superseded decision is unavailable")
        record: dict[str, Any] = self.policy.redactor.clean(
            {
                "decision_id": str(uuid4()),
                "task_id": task_id,
                "agent": task["agent"],
                "text": text,
                "evidence": evidence,
                "critical": critical,
                "supersedes": supersedes,
                "created_at": datetime.now(UTC).isoformat(),
            }
        )
        self.store.save("context-decision", record["decision_id"], record)
        return record

    def forget_decision(self, decision_id: str) -> None:
        """Retire a decision from retrieval without deleting its audit provenance."""
        if self.store.load("context-decision", decision_id) is None:
            raise WorkbenchError("VALIDATION_ERROR", "Decision memory is unavailable")
        self.store.save(
            "context-lifecycle",
            str(uuid4()),
            {"decision_id": decision_id, "state": "retired"},
        )

    def decisions(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        if (
            not isinstance(query, str)
            or len(query) > 8192
            or type(limit) is not int
            or not 1 <= limit <= 50
        ):
            raise WorkbenchError("VALIDATION_ERROR", "Invalid decision retrieval request")
        records = [row["value"] for row in self.store.list_records("context-decision")]
        inactive = {
            row["value"]["decision_id"] for row in self.store.list_records("context-lifecycle")
        } | {record["supersedes"] for record in records if record["supersedes"] is not None}
        active = [record for record in records if record["decision_id"] not in inactive]
        cited = [Evidence(**citation) for record in active for citation in record["evidence"]]
        fresh = iter(self.index.current_evidence(self.policy, cited))
        wanted = set(tokens(query))
        ranked: list[tuple[bool, int, str, dict[str, Any]]] = []
        for record in active:
            current = [next(fresh) for _ in record["evidence"]]
            relevance = len(wanted & set(tokens(record["text"])))
            if all(current) and (record["critical"] or relevance):
                ranked.append((not record["critical"], -relevance, record["decision_id"], record))
        ranked.sort(key=lambda row: row[:3])
        critical = [row[3] for row in ranked if not row[0]]
        return critical + [row[3] for row in ranked if row[0]][:limit]

    def build(
        self,
        instruction: str,
        *,
        role: str,
        skills: list[Skill],
        dependencies: list[dict[str, Any]] | None = None,
        candidates: list[Chunk] | None = None,
        changed_paths: list[str] | None = None,
        retrieval_mode: str = "lexical",
        maximum: int | None = None,
        measure: Callable[[dict[str, Any]], int] | None = None,
    ) -> dict[str, Any]:
        maximum = self.policy.config.limits.context_bytes if maximum is None else maximum
        if (
            not isinstance(instruction, str)
            or not 1 <= len(instruction) <= 8192
            or role not in ROLES
            or retrieval_mode not in {"lexical", "semantic", "combined"}
            or type(maximum) is not int
            or not 1 <= maximum <= self.policy.config.limits.context_bytes
            # Semantic and combined rankings arrive as host-supplied indexed candidates.
            or retrieval_mode != "lexical"
            and candidates is None
        ):
            raise WorkbenchError("VALIDATION_ERROR", "Invalid context request")
        if changed_paths is not None:
            # Changed paths guide selection only; they confer no grant or write authority.
            validate_paths(self.index, changed_paths)
        if self.policy.redactor.contains_secret(instruction):
            raise WorkbenchError("POLICY_DENIED", "Context instructions cannot contain credentials")

        def size(value: dict[str, Any]) -> int:
            if measure is None:
                return _size(value)
            measured = measure(value)
            if type(measured) is not int or measured < 0:
                raise WorkbenchError("VALIDATION_ERROR", "Invalid host context size measurement")
            return max(_size(value), measured)

        memories = self.decisions(instruction)
        dependencies = self.policy.redactor.clean(dependencies or [])
        dependency_evidence = []
        for result in dependencies:
            validate("AgentResult", result)
            dependency_evidence.append(
                result["evidence"]
                + [e for finding in result["findings"] for e in finding["evidence"]]
            )
        current = iter(
            self.index.current_evidence(
                self.policy, [Evidence(**e) for group in dependency_evidence for e in group]
            )
        )
        stale = set()
        for result, citations in zip(dependencies, dependency_evidence, strict=True):
            freshness = [next(current) for _ in citations]
            if not all(freshness):
                stale.add(result["task_id"])
        context: dict[str, Any] = self.policy.redactor.clean(
            {
                "role": role,
                "trust": "untrusted_context",
                "skills": [
                    {"id": skill.id, "instructions": skill.instructions} for skill in skills
                ],
                "repository": {
                    "frameworks": self.index.frameworks,
                    "languages": self.index.languages,
                    "coverage": self.index.coverage,
                },
                "retrieval": [],
                "retrieval_mode": retrieval_mode,
                "dependencies": [],
                "dependencies_truncated": False,
                "decisions": [record for record in memories if record["critical"]],
                "context_truncated": False,
            }
        )
        # Required skills and critical decisions keep their complete provenance or fail closed.
        dependency_budget = min(maximum // 4, maximum - size(context) + 2)
        context["dependencies"], context["dependencies_truncated"] = dependency_context(
            dependencies, dependency_budget, stale=stale
        )
        while size(context) > maximum:
            dependency_budget -= size(context) - maximum
            context["dependencies"], context["dependencies_truncated"] = dependency_context(
                dependencies, dependency_budget, stale=stale
            )
        for record in memories:
            if record["critical"]:
                continue
            excerpt = {**record, "text": _prefix(record["text"], 800)}
            if excerpt["text"] != record["text"]:
                excerpt["truncated"] = True
                context["context_truncated"] = True
            context["decisions"].append(excerpt)
            if size(context) > maximum:
                context["decisions"].pop()
                context["context_truncated"] = True
        if candidates is None:
            selected = select_impact_chunks(
                self.index, instruction, self.index.current_chunks(self.policy), changed_paths
            )
        else:
            indexed_ids = {chunk.id for chunk in self.index.chunks}
            if any(
                not isinstance(chunk, Chunk) or chunk.id not in indexed_ids for chunk in candidates
            ):
                raise WorkbenchError(
                    "VALIDATION_ERROR", "Context candidates must be indexed chunks"
                )
            selected = self.index.current_chunks(self.policy, candidates)
        ranked = list({chunk.id: chunk for chunk in selected}.values())
        context["context_truncated"] |= len(ranked) > 50
        ranked = ranked[:50]
        packed: dict[str, dict[str, Any]] = {}

        def pack(chunk: Chunk, ceiling: int) -> dict[str, Any] | None:
            value: dict[str, Any] = self.policy.redactor.clean(chunk.to_dict())
            context["retrieval"].append(value)
            if size(context) <= ceiling:
                return value
            context["retrieval"].pop()
            lines = value["text"].splitlines()
            low, high = 0, len(lines)
            while low < high:
                middle = (low + high + 1) // 2
                excerpt = Chunk(
                    Evidence(
                        chunk.evidence.path,
                        chunk.evidence.start_line,
                        chunk.evidence.start_line + middle - 1,
                        chunk.evidence.source_hash,
                    ),
                    "\n".join(lines[:middle]),
                ).to_dict()
                context["retrieval"].append(excerpt)
                fits = size(context) <= ceiling
                context["retrieval"].pop()
                if fits:
                    low = middle
                else:
                    high = middle - 1
            if not low:
                return None
            value = Chunk(
                Evidence(
                    chunk.evidence.path,
                    chunk.evidence.start_line,
                    chunk.evidence.start_line + low - 1,
                    chunk.evidence.source_hash,
                ),
                "\n".join(lines[:low]),
            ).to_dict()
            context["retrieval"].append(value)
            return value

        # Reserve early source diversity, then reuse unused shares before lower-ranked detail.
        priority = ranked[:6]
        for position, chunk in enumerate(priority):
            used = size(context)
            ceiling = used + (maximum - used) // (len(priority) - position)
            value = pack(chunk, ceiling)
            if value is not None:
                packed[chunk.id] = value
        for chunk in priority:
            previous = packed.get(chunk.id)
            if previous is not None:
                if previous["evidence"]["end_line"] == chunk.evidence.end_line:
                    continue
                context["retrieval"].remove(previous)
            value = pack(chunk, maximum)
            if value is not None:
                packed[chunk.id] = value
        for chunk in ranked[6:]:
            value = pack(chunk, maximum)
            if value is not None:
                packed[chunk.id] = value
        context["retrieval"] = [packed[chunk.id] for chunk in ranked if chunk.id in packed]
        context["context_truncated"] |= any(
            chunk.id not in packed
            or packed[chunk.id]["evidence"]["end_line"] < chunk.evidence.end_line
            for chunk in ranked
        )
        context["context_truncated"] |= context["dependencies_truncated"]
        if size(context) > maximum:
            raise WorkbenchError("LIMIT_EXCEEDED", "Complete context exceeds byte limit")
        return context
