"""Compact, source-bound context selection; retrieved content grants no authority."""

from __future__ import annotations

import re
from itertools import islice, zip_longest
from typing import TYPE_CHECKING, Any

from .models import Evidence
from .retrieval import Chunk, lexical_search, tokens

if TYPE_CHECKING:
    from .repository import RepositoryIndex


def _checks(path: str) -> bool:
    return "test" in path.lower() or ".spec." in path.lower()


def _matches(use: dict[str, Any], declaration: dict[str, Any]) -> bool:
    if use.get("target_id") is not None:
        return bool(use["target_id"] == declaration.get("id"))
    return bool(
        declaration["evidence"]["path"].endswith(".py")
        and use["evidence"]["path"].endswith(".py")
        and use.get("callee", "").rsplit(".", 1)[-1] == declaration["name"]
    )


def _unique(groups: list[list[Chunk]]) -> list[Chunk]:
    """Round-robin groups so one definition/file cannot consume every early slot."""
    result: dict[str, Chunk] = {}
    for row in zip_longest(*groups):
        for chunk in row:
            if chunk is not None:
                result.setdefault(chunk.id, chunk)
    return list(result.values())


def select_context_chunks(
    index: RepositoryIndex,
    instruction: str,
    fresh_chunks: list[Chunk],
    changed_paths: list[str] | None = None,
) -> list[Chunk]:
    """Balance declaration/body windows, users and checks before lexical fallback.

    Every excerpt stays inside a contiguous union of supplied fresh source chunks.
    Relations are static hints; omitted/unresolved relationships remain unknown.
    """
    lexical = lexical_search(fresh_chunks, instruction[:4096], 50)
    wanted = set(tokens(instruction))
    identifiers = set(re.findall(r"[\w$]+", instruction.lower()))
    available: dict[str, list[tuple[int, int]]] = {}
    for chunk in fresh_chunks:
        e = chunk.evidence
        source = index.files.get(e.path)
        if source is None or source.source_hash != e.source_hash:
            continue
        spans = available.setdefault(e.path, [])
        spans.append((e.start_line, e.end_line))
    for path, spans in available.items():
        merged: list[tuple[int, int]] = []
        for start, end in sorted(spans):
            if merged and start <= merged[-1][1] + 1:
                merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
            else:
                merged.append((start, end))
        available[path] = merged
    lines: dict[str, list[str]] = {}

    def source_lines(path: str) -> list[str]:
        if path not in lines:
            lines[path] = index.files[path].text.splitlines()
        return lines[path]

    def window(path: str, anchor: int, end: int | None = None) -> list[Chunk]:
        for first, last in available.get(path, []):
            if first <= anchor <= last:
                text = source_lines(path)
                if len(text) <= 60:
                    start, stop = first, last
                else:
                    body_length = end - anchor + 1 if end is not None else 61
                    short_body = body_length <= 60
                    padding = min(3, 60 - body_length) if short_body else 3
                    start = max(first, anchor - padding)
                    stop = min(last, max(anchor + 12, end or anchor))
                    stop = min(stop, start + (59 if short_body else 23))
                return [
                    Chunk(
                        Evidence(path, start, stop, index.files[path].source_hash),
                        "\n".join(text[start - 1 : stop]),
                    )
                ]
        return []

    def relevance(chunk: Chunk) -> tuple[int, str, int]:
        return (
            -len(wanted & set(tokens(chunk.text))),
            chunk.evidence.path,
            chunk.evidence.start_line,
        )

    definitions = [s for s in index.symbols if s["evidence"]["path"] in available]
    named = [s for s in definitions if s["name"].lower() in identifiers]
    explicit = [path for path in available if path in instruction]
    targets = list(dict.fromkeys([*(changed_paths or []), *explicit]))
    if not targets:
        targets = list(dict.fromkeys(s["evidence"]["path"] for s in named))
    if not targets:
        # Infer only code locations with indexed declarations; do not elevate prose.
        declared = {s["evidence"]["path"] for s in definitions}
        targets = list(
            dict.fromkeys(
                c.evidence.path
                for c in lexical
                if c.evidence.path in declared and not _checks(c.evidence.path)
            )
        )[:3]
    targets = [path for path in targets[:20] if path in available]
    if not targets:
        return lexical

    def declaration_rank(fact: dict[str, Any]) -> tuple[int, int, int, int]:
        e = fact["evidence"]
        preview = "\n".join(source_lines(e["path"])[e["start_line"] - 1 : e["start_line"] + 12])
        overlap = next(
            (
                rank
                for rank, chunk in enumerate(lexical)
                if chunk.evidence.path == e["path"]
                and chunk.evidence.start_line <= e["end_line"]
                and e["start_line"] <= chunk.evidence.end_line
            ),
            50,
        )
        return (
            0 if fact["name"].lower() in identifiers else 1,
            -len(wanted & set(tokens(preview))),
            overlap,
            e["end_line"] - e["start_line"],
        )

    per_file = []
    for path in targets:
        ranked = sorted(
            (s for s in definitions if s["evidence"]["path"] == path),
            key=declaration_rank,
        )
        per_file.append(ranked[:2])
    selected = [fact for row in zip_longest(*per_file) for fact in row if fact is not None][:20]
    if changed_paths:
        # Native declarations include parameters and local variables. For an edit,
        # recover their enclosing callable's behavior and incoming relationships.
        for position, fact in enumerate(selected):
            e = fact["evidence"]
            if e["path"] not in changed_paths or fact["kind"] not in {
                "Parameter",
                "TypeParameter",
                "VariableDeclaration",
            }:
                continue
            enclosing = [
                s
                for s in definitions
                if s["evidence"]["path"] == e["path"]
                and s["kind"]
                in {
                    "FunctionDeclaration",
                    "MethodDeclaration",
                    "GetAccessor",
                    "SetAccessor",
                    "VariableDeclaration",
                    "PropertyDeclaration",
                }
                and s["evidence"]["start_line"] <= e["start_line"]
                and e["end_line"] <= s["evidence"]["end_line"]
                and (s["evidence"]["start_line"], s["evidence"]["end_line"])
                != (e["start_line"], e["end_line"])
            ]
            if enclosing:
                selected[position] = min(
                    enclosing, key=lambda s: s["evidence"]["end_line"] - s["evidence"]["start_line"]
                )
    declarations: list[Chunk] = []
    bodies: list[Chunk] = []
    users: list[Chunk] = []
    checks: list[Chunk] = []
    relation_priority: dict[str, int] = {}
    symbols_by_path: dict[str, list[dict[str, Any]]] = {}
    for fact in definitions:
        symbols_by_path.setdefault(fact["evidence"]["path"], []).append(fact)

    def related(e: dict[str, Any]) -> list[Chunk]:
        # Include the nearest enclosing check's declaration rather than a distant import.
        containers = [
            s["evidence"]
            for s in symbols_by_path.get(e["path"], [])
            if s["evidence"]["start_line"] <= e["start_line"] <= s["evidence"]["end_line"]
        ]
        if containers and _checks(e["path"]):
            enclosing = min(containers, key=lambda s: s["end_line"] - s["start_line"])
            if enclosing["end_line"] - enclosing["start_line"] < 60:
                return window(e["path"], enclosing["start_line"], enclosing["end_line"])
            return window(e["path"], e["start_line"]) + window(e["path"], enclosing["start_line"])
        return window(e["path"], e["start_line"], e["end_line"])

    for fact in selected:
        e = fact["evidence"]
        declarations += window(e["path"], e["start_line"], e["end_line"])
        if e["end_line"] - e["start_line"] > 24:
            bodies += window(e["path"], max(e["start_line"], e["end_line"] - 10), e["end_line"])

        # Filter by the selected identity before limits; name-wide traces also compute
        # unused callees with quadratic list membership on call-heavy files.
        for group_rank, group in enumerate((index.calls, index.references, index.imports)):
            for use in islice((use for use in group if _matches(use, fact)), 50):
                target = checks if _checks(use["evidence"]["path"]) else users
                for offset, chunk in enumerate(related(use["evidence"])):
                    target.append(chunk)
                    relation_priority[chunk.id] = min(
                        relation_priority.get(chunk.id, 8), group_rank * 2 + offset
                    )
        pattern = re.compile(rf"(?<![\w$]){re.escape(fact['name'])}(?![\w$])")
        mentions = (
            Evidence(path, number, number, index.files[path].source_hash).to_dict()
            for path in available
            if _checks(path)
            for number, line in enumerate(source_lines(path), 1)
            if pattern.search(line)
        )
        for evidence in islice(mentions, 50):
            for offset, chunk in enumerate(related(evidence)):
                checks.append(chunk)
                relation_priority[chunk.id] = min(relation_priority.get(chunk.id, 8), 6 + offset)
    # Textual query matches remain useful where structural analysis is unavailable.
    lexical_windows = []
    for chunk in lexical:
        e = chunk.evidence
        text = chunk.text.splitlines()
        if not text:
            continue
        offset = max(
            range(len(text)),
            key=lambda line: len(wanted & set(tokens(text[line]))),
        )
        candidates = window(e.path, e.start_line + offset)
        lexical_windows.extend(candidates)
        if _checks(e.path):
            checks.extend(candidates)

    def relation_rank(chunk: Chunk) -> tuple[int, tuple[int, str, int]]:
        return relation_priority.get(chunk.id, 8), relevance(chunk)

    users = sorted({c.id: c for c in users}.values(), key=relation_rank)
    checks = sorted({c.id: c for c in checks}.values(), key=relation_rank)
    # Keep both targets' behavior ahead of low-specificity lexical detail.
    result = {
        chunk.id: chunk
        for chunk in [
            *declarations[:1],
            *users[:1],
            *checks[:1],
            *declarations[1:],
            *bodies,
            *_unique([users[1:], checks[1:], lexical_windows, lexical]),
        ]
    }
    if changed_paths:
        # An edit can affect any line in its definition. Preserve complete fresh
        # bodies when they and their direct users/checks fit the early six slots.
        # Larger or partially supplied bodies retain the compact fallback above.
        edited = [
            fact["evidence"] for fact in selected if fact["evidence"]["path"] in changed_paths
        ]
        if edited and all(
            any(
                first <= e["start_line"] <= e["end_line"] <= last
                for first, last in available[e["path"]]
            )
            for e in edited
        ):
            complete = [
                chunk
                for chunk in fresh_chunks
                if any(
                    chunk.evidence.path == e["path"]
                    and chunk.evidence.source_hash == index.files[e["path"]].source_hash
                    and chunk.evidence.start_line <= e["end_line"]
                    and e["start_line"] <= chunk.evidence.end_line
                    for e in edited
                )
            ]
            indexed = {c.id: c for c in index.chunks}
            if any(c.id not in indexed for c in complete):
                return list(result.values())
            complete = [indexed[c.id] for c in complete]
            direct_users = [c for c in users if relation_priority.get(c.id, 8) == 0] or users[:1]
            direct_checks = [c for c in checks if relation_priority.get(c.id, 8) <= 1] or checks[:1]
            bundle = _unique([complete, direct_users, direct_checks])
            if len(bundle) <= 6:
                return list({c.id: c for c in [*bundle, *result.values()]}.values())
    return list(result.values())
