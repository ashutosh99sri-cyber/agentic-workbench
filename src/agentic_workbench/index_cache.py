"""Incremental indexing: fresh source reads on every refresh, reused per-file derivations.

Every refresh reads the workspace through collect_workspace: the policy-bounded traversal,
fresh raw reads, hashing and redaction. Only per-file derived facts are reused, and only when
the path, raw source hash, redacted text hash and secret flag match under the same workspace,
configuration and analysis version. Chunks are always rebuilt from the freshly read text.
Timestamps are never consulted.
"""

from __future__ import annotations

import copy
import re
from typing import Any

from .errors import WorkbenchError
from .models import Evidence, canonical_hash, canonical_json, text_hash
from .policy import SourceFile, WorkspacePolicy
from .repository import (
    INDEX_ANALYSIS_VERSION,
    RepositoryIndex,
    collect_workspace,
    index_source,
    merge_source,
)
from .retrieval import Chunk
from .state import StateStore

_FACTS = ("symbols", "calls", "manifests", "frameworks", "languages", "imports", "references")
_RECORD = "derived"  # one bounded, mutable record of the existing "index" kind
_RECORD_BYTES = 900_000  # below the state store's 1 MiB record limit
_HASH = re.compile(r"[a-f0-9]{64}")
# Failures of the optional durable copy: store errors, undecodable or non-finite JSON, and
# pathological nesting. None of them may cost the caller a fresh index.
_UNREADABLE = (WorkbenchError, ValueError, TypeError, RecursionError)


def _chunks(source: SourceFile) -> list[Chunk]:
    """The 60-line chunks index_source derives, rebuilt from the fresh text."""
    lines = source.text.splitlines()
    return [
        Chunk(
            Evidence(source.path, start + 1, min(start + 60, len(lines)), source.source_hash),
            "\n".join(lines[start : start + 60]),
        )
        for start in range(0, len(lines), 60)
    ]


# Minimum string fields each persisted fact kind needs before its consumers may read it.
_FIELDS = {
    "symbols": ("name", "kind"),
    "calls": ("callee", "resolution"),
    "manifests": ("path", "language"),
    "imports": ("resolution",),
    "references": ("name", "resolution"),
}
_EVIDENCE = {"path", "start_line", "end_line", "source_hash"}


def _strings(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _valid(source: SourceFile, facts: Any) -> bool:
    """Persisted facts are reused only if well-formed and citing this fresh source's lines."""
    lines = max(1, len(source.text.splitlines()))
    try:
        if (
            set(facts) != {*_FACTS, "parse_errors"}
            or type(facts["parse_errors"]) is not int
            or facts["parse_errors"] < 0
            or not _strings(facts["frameworks"])
            or not _strings(facts["languages"])
        ):
            return False
        for name, fields in _FIELDS.items():
            for fact in facts[name]:
                evidence = fact["evidence"]
                if (
                    any(not isinstance(fact.get(field), str) for field in fields)
                    or set(evidence) != _EVIDENCE
                    or evidence["path"] != source.path
                    or evidence["source_hash"] != source.source_hash
                    or type(evidence["start_line"]) is not int
                    or type(evidence["end_line"]) is not int
                    or not 1 <= evidence["start_line"] <= evidence["end_line"] <= lines
                    or name == "manifests"
                    and (
                        fact["path"] != source.path
                        or not _strings(fact["dependencies"])
                        or not _strings(fact["frameworks"])
                    )
                ):
                    return False
        return True
    except (KeyError, TypeError, AttributeError):
        return False


class IncrementalIndexCache:
    """Reuse per-file derivations across refreshes; memory holds current entries only."""

    def __init__(self) -> None:
        self._binding: dict[str, str] | None = None
        self._entries: dict[str, dict[str, Any]] = {}
        # Paths whose entries came from the durable record and are not yet checked.
        self._pending: set[str] = set()
        self._saved: str | None = None

    def refresh(self, policy: WorkspacePolicy, store: StateStore) -> RepositoryIndex:
        index = collect_workspace(policy)
        binding = {
            "workspace": policy.workspace_id,
            "config": policy.config.fingerprint,
            "version": INDEX_ANALYSIS_VERSION,
        }
        if binding != self._binding:
            self._binding = binding
            self._entries = self._load(store, binding)
        stats = dict.fromkeys(
            ("files_read", "reused", "rebuilt", "deleted", "persisted", "truncated"), 0
        )
        stats["files_read"] = len(index.files)
        current: dict[str, dict[str, Any]] = {}
        for path, source in index.files.items():
            key = [source.source_hash, text_hash(source.text), source.contains_secrets]
            entry = self._entries.get(path)
            if (
                entry is not None
                and entry["key"] == key
                and (path not in self._pending or _valid(source, entry["facts"]))
            ):
                stats["reused"] += 1
                derived = RepositoryIndex(
                    chunks=_chunks(source),
                    coverage={"parse_errors": entry["facts"]["parse_errors"]},
                    **{name: copy.deepcopy(entry["facts"][name]) for name in _FACTS},
                )
            else:
                stats["rebuilt"] += 1
                derived = index_source(source)
                facts = {name: copy.deepcopy(getattr(derived, name)) for name in _FACTS}
                facts["parse_errors"] = derived.coverage.get("parse_errors", 0)
                entry = {"key": key, "facts": facts}
            current[path] = entry
            merge_source(index, derived)
        stats["deleted"] = len(self._entries.keys() - current.keys())
        self._entries, self._pending = current, set()
        stats["persisted"], stats["truncated"] = self._save(store, binding)
        index.cache_stats = stats
        return index

    def _load(self, store: StateStore, binding: dict[str, str]) -> dict[str, dict[str, Any]]:
        # The durable copy is optional: an undecodable, non-finite or malformed record means a
        # cold rebuild, and the next valid snapshot overwrites it.
        self._saved = None
        try:
            record = store.load("index", _RECORD)
            if not isinstance(record, dict) or record.get("binding") != binding:
                return {}
            entries = record.get("entries")
            if not isinstance(entries, list):
                return {}
            # Outer shape only here; each entry's facts are checked against its fresh source
            # at first reuse, and anything malformed is rebuilt rather than trusted.
            loaded = {
                item["path"]: {"key": item["key"], "facts": item["facts"]}
                for item in entries
                if isinstance(item, dict)
                and isinstance(item.get("path"), str)
                and isinstance(item.get("key"), list)
                and len(item["key"]) == 3
                and all(
                    isinstance(value, str) and _HASH.fullmatch(value) for value in item["key"][:2]
                )
                and type(item["key"][2]) is bool
                and isinstance(item.get("facts"), dict)
            }
            saved = canonical_hash(record)
        except _UNREADABLE:
            return {}
        self._saved, self._pending = saved, set(loaded)
        return loaded

    def _save(self, store: StateStore, binding: dict[str, str]) -> tuple[int, int]:
        """Persist one bounded snapshot of current facts, without source text."""
        entries, size, truncated = [], 0, 0
        for path in sorted(self._entries):
            item = {"path": path, **self._entries[path]}
            cost = len(canonical_json(item).encode())
            if size + cost > _RECORD_BYTES:
                truncated += 1
                continue
            entries.append(item)
            size += cost
        record = {
            "binding": binding,
            "entries": entries,
            "persisted": len(entries),
            "truncated": truncated,
        }
        try:
            digest = canonical_hash(record)
            if digest != self._saved:
                # Never read the old row back: it may be the corrupt one being replaced.
                try:
                    store.update("index", _RECORD, record)
                except WorkbenchError as error:
                    if error.code != "VALIDATION_ERROR":
                        raise
                    store.save("index", _RECORD, record)
                self._saved = digest
        except _UNREADABLE:
            # The durable copy is only acceleration; this scan stays complete without it.
            return 0, len(self._entries)
        return len(entries), truncated
