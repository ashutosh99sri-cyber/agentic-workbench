"""Change impact: what a change to indexed files reaches, from static facts only.

A pure, bounded selector over a RepositoryIndex. Every fact keeps its source-hash Evidence.
Declaration links come from structural facts when the index has them; otherwise matches are
by name, so same-name symbols elsewhere may appear. Nothing here proves runtime behavior.
"""

from __future__ import annotations

import os
import re
from typing import Any

from .errors import WorkbenchError
from .models import Evidence
from .repository import _EXTENSIONS, RepositoryIndex
from .selection import select_context_chunks as select_impact_chunks

__all__ = ["impact", "select_impact_chunks", "validate_paths"]

LIMITATIONS = [
    "Definitions, calls, imports and references are static facts; dynamic dispatch, "
    "reflection, computed names and unresolved calls are not followed.",
    "Imports, references and resolved calls bind to changed definitions by declaration ID. "
    "Python calls without a declaration link match by name, so same-name functions may appear.",
    "Tests are code files whose path names a test, matched by whole-word text unless a "
    "declaration-linked import or reference ties them to a changed definition.",
]


def validate_paths(index: RepositoryIndex, paths: Any) -> list[str]:
    if (
        not isinstance(paths, list)
        or not 1 <= len(paths) <= 20
        or any(not isinstance(path, str) or path not in index.files for path in paths)
        or len(set(paths)) != len(paths)
    ):
        raise WorkbenchError(
            "VALIDATION_ERROR", "Impact requires 1-20 distinct indexed relative paths"
        )
    return list(paths)


def _is_test(path: str) -> bool:
    lowered = path.lower()
    return os.path.splitext(lowered)[1] in _EXTENSIONS and (
        "test" in lowered or ".spec." in lowered
    )


def impact(index: RepositoryIndex, changed_paths: list[str], limit: int = 20) -> dict[str, Any]:
    changed = validate_paths(index, changed_paths)
    if type(limit) is not int or not 1 <= limit <= 50:
        raise WorkbenchError("VALIDATION_ERROR", "Impact limit must be 1-50")
    targets = set(changed)
    definitions = [s for s in index.symbols if s["evidence"]["path"] in targets]
    names = {s["name"] for s in definitions}
    ids = {s["id"] for s in definitions if s.get("id")}
    python = {s["name"] for s in definitions if s["evidence"]["path"].endswith(".py")}

    def outside(fact: dict[str, Any]) -> bool:
        return fact["evidence"]["path"] not in targets

    def declared(fact: dict[str, Any]) -> bool:
        return outside(fact) and bool(fact.get("target_id")) and fact["target_id"] in ids

    def caller(call: dict[str, Any]) -> bool:
        if call.get("target_id"):
            return declared(call)
        # Legacy Python calls carry no declaration link: match changed Python names.
        callee = call["callee"]
        return (
            outside(call)
            and call["evidence"]["path"].endswith(".py")
            and (callee in python or callee.rsplit(".", 1)[-1] in python)
        )

    callers = [c for c in index.calls if caller(c)]
    # Imports and references bind by declaration ID only, so aliases and shadowing hold.
    imports = [i for i in index.imports if declared(i)]
    references = [r for r in index.references if declared(r)]
    # A declaration-linked use in a test file is a check even under an alias that never
    # spells the changed name; it keeps its own evidence.
    tests = [
        {
            "name": fact.get("name") or fact.get("local") or fact.get("imported"),
            "link": "declaration",
            "evidence": fact["evidence"],
        }
        for fact in imports + references
        if _is_test(fact["evidence"]["path"])
    ]
    seen = {(t["evidence"]["path"], t["evidence"]["start_line"]) for t in tests}
    if names:
        # Identifier boundaries include `$`, so JavaScript's $total is one whole name.
        alternatives = "|".join(sorted(map(re.escape, names)))
        pattern = re.compile(r"(?<![\w$])(" + alternatives + r")(?![\w$])")
        for source in index.files.values():
            if source.path in targets or not _is_test(source.path):
                continue
            for line, text in enumerate(source.text.splitlines(), 1):
                match = pattern.search(text)
                if match and (source.path, line) not in seen:
                    evidence = Evidence(source.path, line, line, source.source_hash).to_dict()
                    tests.append({"name": match.group(1), "link": "textual", "evidence": evidence})
    tests.sort(key=lambda t: (t["evidence"]["path"], t["evidence"]["start_line"]))
    groups = {
        "definitions": definitions,
        "callers": callers,
        "imports": imports,
        "references": references,
        "tests": tests,
    }
    affected = sorted(
        {fact["evidence"]["path"] for key in groups if key != "definitions" for fact in groups[key]}
    )
    return {
        "fingerprint": index.fingerprint,
        "changed_paths": changed,
        "affected_paths": affected[:50],
        **{key: value[:limit] for key, value in groups.items()},
        "truncated": len(affected) > 50 or any(len(value) > limit for value in groups.values()),
        "limitations": LIMITATIONS,
    }
