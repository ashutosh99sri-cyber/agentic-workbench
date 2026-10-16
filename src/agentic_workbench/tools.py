"""Closed read tools. Retrieved instructions never become runtime authority."""

from __future__ import annotations

from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from .errors import WorkbenchError
from .models import Evidence, canonical_json
from .policy import WorkspacePolicy
from .repository import RepositoryIndex
from .state import StateStore

_PARAMETERS: dict[str, dict[str, Any]] = {
    "repository_summary": {},
    "read_source": {
        "path": {"type": "string", "maxLength": 4096},
        "start_line": {"type": "integer", "minimum": 1},
        "end_line": {"type": "integer", "minimum": 1},
        "source_hash": {"type": ["string", "null"], "pattern": "^[a-f0-9]{64}$"},
    },
    "search_code": {
        "query": {"type": "string", "maxLength": 4096},
        "limit": {"type": "integer", "minimum": 1, "maximum": 10},
    },
    "lookup_memory": {
        "namespace": {"type": "string", "enum": ["source", "episodic", "workflow"]},
        "key": {"type": "string", "maxLength": 256},
    },
    "list_symbols": {"path": {"type": "string", "maxLength": 4096}},
    "trace_symbol": {"name": {"type": "string", "pattern": "^[A-Za-z_$][A-Za-z0-9_$]{0,255}$"}},
}

_DESCRIPTIONS = {
    "repository_summary": "Fingerprint, detected languages and frameworks, coverage counts, "
    "and as many of the first 100 file paths and first 10 dependency manifests as fit the "
    "result limit; truncated marks omitted entries.",
    "read_source": "Read one current source file span of at most 101 lines. Pass source_hash "
    "to fail instead of reading a changed file.",
    "search_code": "Lexical search over indexed source chunks. Returns cited chunks with "
    "path, line span and source hash.",
    "lookup_memory": "Read one persisted value by namespace and exact key from this "
    "workspace's local state.",
    "list_symbols": "Indexed Python and configured TypeScript/JavaScript definitions "
    "with line spans; "
    "truncated marks omitted entries. Other languages require an analyzer.",
    "trace_symbol": "Static trace of an indexed symbol: definitions, callers, callees, test "
    "references, imports and references. TypeScript resolution requires the host parser; "
    "truncated marks omitted entries.",
}


_FIT = {
    "repository_summary": ("files", "manifests"),
    "list_symbols": ("symbols",),
    "trace_symbol": ("definitions", "callers", "callees", "tests", "imports", "references"),
}


def _fit(result: dict[str, Any], keys: tuple[str, ...], limit: int = 12_000) -> dict[str, Any]:
    """Drop trailing whole entries from the largest list by size until the result fits."""
    while len(canonical_json(result).encode()) > limit:
        key = max(keys, key=lambda name: len(canonical_json(result[name]).encode()))
        if not result[key]:
            break
        result[key].pop()
        result["truncated"] = True
    return result


class ReadTools:
    def __init__(
        self,
        policy: WorkspacePolicy,
        index: RepositoryIndex,
        store: StateStore,
        *,
        allowed: tuple[str, ...] | None = None,
        task_id: str | None = None,
    ) -> None:
        self.policy, self.index, self.store = policy, index, store
        self.task_id = task_id
        self.allowed = tuple(
            name
            for name in (policy.config.policy.allowed_tools if allowed is None else allowed)
            if name in policy.config.policy.allowed_tools
        )

    @property
    def schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "name": name,
                "description": _DESCRIPTIONS[name],
                "strict": True,
                "parameters": {
                    "type": "object",
                    "properties": _PARAMETERS[name],
                    "required": list(_PARAMETERS[name]),
                    "additionalProperties": False,
                },
            }
            for name in self.allowed
        ]

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if self.task_id is not None and self.store.cancelled(self.task_id):
            raise WorkbenchError("CANCELLED", "Task was cancelled before tool execution")
        if name not in self.allowed or name not in _PARAMETERS:
            raise WorkbenchError("POLICY_DENIED", "Tool is not in the effective read scope")
        canonical_json(arguments)
        parameters = {
            "type": "object",
            "properties": _PARAMETERS[name],
            "required": list(_PARAMETERS[name]),
            "additionalProperties": False,
        }
        try:
            Draft202012Validator(parameters).validate(arguments)
        except ValidationError as error:
            raise WorkbenchError("VALIDATION_ERROR", "Invalid tool arguments") from error
        result: dict[str, Any]
        if name == "repository_summary":
            result = {
                "fingerprint": self.index.fingerprint,
                "frameworks": self.index.frameworks,
                "languages": self.index.languages,
                "coverage": self.index.coverage,
                "files": list(self.index.files)[:100],
                "manifests": self.index.manifests[:10],
                "truncated": len(self.index.files) > 100 or len(self.index.manifests) > 10,
            }
        elif name == "read_source":
            source = self.policy.read_source(arguments["path"])
            start, end = arguments["start_line"], arguments["end_line"]
            lines = source.text.splitlines()
            if not 1 <= start <= end <= len(lines) or end - start > 100:
                raise WorkbenchError(
                    "LIMIT_EXCEEDED", "Source tool requires a current span of at most 101 lines"
                )
            if (
                arguments["source_hash"] is not None
                and source.source_hash != arguments["source_hash"]
            ):
                raise WorkbenchError("STALE", "Source changed before tool execution")
            result = {
                "evidence": Evidence(source.path, start, end, source.source_hash).to_dict(),
                "text": "\n".join(lines[start - 1 : end]),
            }
        elif name == "search_code":
            result = {
                "mode": "lexical",
                "chunks": [
                    c.to_dict()
                    for c in self.index.search(
                        arguments["query"], arguments["limit"], policy=self.policy
                    )
                ],
            }
        elif name == "list_symbols":
            source = self.policy.read_source(arguments["path"])
            indexed = self.index.files.get(source.path)
            if indexed is None or indexed.source_hash != source.source_hash:
                raise WorkbenchError("STALE", "Source changed before symbol lookup; rebuild index")
            symbols = self.index.symbols_in(source.path)
            result = {
                "path": source.path,
                "source_hash": source.source_hash,
                "symbols": symbols[:100],
                "truncated": len(symbols) > 100,
            }
        elif name == "trace_symbol":
            result = self.index.trace(arguments["name"], limit=12)
            citations = [
                Evidence(**entry.get("evidence", entry))
                for group in ("definitions", "callers", "callees", "tests", "imports", "references")
                for entry in result[group]
            ]
            if not all(self.index.current_evidence(self.policy, citations)) or (
                self.index.structural.get("parser")
                and not self.index.current_relationships(self.policy)
            ):
                raise WorkbenchError("STALE", "Source changed before symbol trace; rebuild index")
        else:
            result = {
                "value": self.store.get_memory(arguments["namespace"], arguments["key"]),
                "namespace": arguments["namespace"],
                "scope": self.policy.workspace_id,
            }
        result = self.policy.redactor.clean(result)
        if name in _FIT:
            # Fit after redaction: redacted paths can be longer than the originals.
            result = _fit(result, _FIT[name])
        if len(canonical_json(result).encode()) > 12_000:
            raise WorkbenchError(
                "LIMIT_EXCEEDED", "Tool result exceeds context byte limit; narrow the request"
            )
        return result
