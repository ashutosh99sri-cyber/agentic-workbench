"""Changed-path context must preserve complete affordable definition bodies."""

from pathlib import Path

import pytest
from test_typescript import analyzer as analyzer

from agentic_workbench.impact import select_impact_chunks
from agentic_workbench.models import Evidence, canonical_json
from agentic_workbench.policy import WorkspacePolicy
from agentic_workbench.repository import RepositoryIndex, scan_workspace
from agentic_workbench.retrieval import Chunk
from agentic_workbench.sdk import Workbench
from agentic_workbench.typescript import TypeScriptAnalyzer

QUERY = "Assess compatibility of the modified processing rules with their consumers and checks."


def _python_definition(name: str, lines: int) -> str:
    head = [f"def {name}(entries, capacity=8):", "    weights = {"]
    middle = [
        "    }",
        "    demand = 0",
        "    for entry in entries:",
        "        if entry.get('disabled', False):",
        "            continue",
        "        demand += entry['units'] * weights.get(entry.get('profile'), 1)",
        "    if demand > capacity:",
        "        return {'accepted': False, 'demand': demand}",
        "    lanes = (",
    ]
    tail = [
        "    )",
        "    return {'accepted': True, 'demand': demand, 'lane': lanes[demand % len(lanes)]}",
    ]
    entries = lines - len(head + middle + tail)
    weights = [f"        'profile-{i:03d}': {i % 3 + 1}," for i in range(entries // 2)]
    lanes = [f"        'lane-{i:03d}'," for i in range(entries - len(weights))]
    source = "\n".join(head + weights + middle + lanes + tail) + "\n"
    assert len(source.splitlines()) == lines
    return source


def _write_fixture(tmp_path: Path, definitions: dict[str, tuple[str, int]]) -> WorkspacePolicy:
    for path, (name, lines) in definitions.items():
        (tmp_path / path).write_text(_python_definition(name, lines))
    names = [name for name, _ in definitions.values()]
    imports = "".join(
        f"from {Path(path).stem} import {name}\n" for path, (name, _) in definitions.items()
    )
    calls = ", ".join(f"{name}(entries)" for name in names)
    (tmp_path / "consumer.py").write_text(
        imports + f"\n\ndef prepare_batch(entries):\n    return [{calls}]\n"
    )
    (tmp_path / "test_rules.py").write_text(
        imports
        + "\n\ndef test_excess_capacity():\n"
        + "".join(f"    assert {name}([{{'units': 12}}])['accepted'] is False\n" for name in names)
    )
    return WorkspacePolicy(tmp_path)


def _covered(chunks: list[Chunk], path: str) -> set[int]:
    return {
        line
        for chunk in chunks
        if chunk.evidence.path == path
        for line in range(chunk.evidence.start_line, chunk.evidence.end_line + 1)
    }


def _assert_source_spans(index: RepositoryIndex, chunks: list[Chunk]) -> None:
    for chunk in chunks:
        evidence = chunk.evidence
        source = index.files[evidence.path]
        assert evidence.source_hash == source.source_hash
        assert 1 <= evidence.start_line <= evidence.end_line <= len(source.text.splitlines())
        assert chunk.text == "\n".join(
            source.text.splitlines()[evidence.start_line - 1 : evidence.end_line]
        )


def _assert_complete_first_six(
    index: RepositoryIndex, fresh: list[Chunk], selected: list[Chunk], changed: list[str]
) -> None:
    # The uncompressed source chunks already fit, so body loss buys no needed capacity.
    assert len(fresh) <= 6
    assert len(canonical_json([chunk.to_dict() for chunk in fresh]).encode()) <= 16000
    first = selected[:6]
    assert len(canonical_json([chunk.to_dict() for chunk in first]).encode()) <= 16000
    _assert_source_spans(index, selected)
    for path in changed:
        definitions = [
            symbol
            for symbol in index.symbols
            if symbol["evidence"]["path"] == path
            and symbol["evidence"]["start_line"] == 1
            and symbol["evidence"]["end_line"] == len(index.files[path].text.splitlines())
        ]
        assert len(definitions) == 1
        evidence = definitions[0]["evidence"]
        expected = set(range(evidence["start_line"], evidence["end_line"] + 1))
        missing = expected - _covered(first, path)
        assert not missing, (
            f"{path}: {len(missing)} changed-body lines missing, first {sorted(missing)[:12]}"
        )
    for path in index.files:
        if path in changed:
            continue
        anchor = "return " if path.startswith("consumer.") else "assert "
        required = {
            line
            for line, text in enumerate(index.files[path].text.splitlines(), 1)
            if anchor in text
        }
        assert required, f"{path} must contain a direct caller or behavioral check"
        assert required <= _covered(first, path), f"{path}: direct caller/check was dropped"


@pytest.mark.parametrize("body_lines", [70, 110, 170, 230])
def test_changed_definition_keeps_its_complete_body_when_source_chunks_fit(
    tmp_path: Path, body_lines: int
) -> None:
    changed = ["garden_rules.py"]
    policy = _write_fixture(tmp_path, {changed[0]: ("evaluate_garden_load", body_lines)})
    index = scan_workspace(policy)
    fresh = index.current_chunks(policy)
    selected = select_impact_chunks(index, QUERY, fresh, changed_paths=changed)
    _assert_complete_first_six(index, fresh, selected, changed)


def test_two_changed_bodies_keep_their_middle_lines_and_shared_caller_check(tmp_path: Path) -> None:
    definitions = {
        "meadow_rules.py": ("evaluate_meadow_load", 90),
        "orchard_rules.py": ("evaluate_orchard_load", 90),
    }
    changed = list(definitions)
    policy = _write_fixture(tmp_path, definitions)
    index = scan_workspace(policy)
    fresh = index.current_chunks(policy)
    selected = select_impact_chunks(index, QUERY, fresh, changed_paths=changed)
    _assert_complete_first_six(index, fresh, selected, changed)


def test_partial_fresh_definition_span_cannot_expand_into_unavailable_lines(tmp_path: Path) -> None:
    changed = ["garden_rules.py"]
    policy = _write_fixture(tmp_path, {changed[0]: ("evaluate_garden_load", 170)})
    index = scan_workspace(policy)
    source = index.files[changed[0]]
    behavior_line = next(
        line
        for line, text in enumerate(source.text.splitlines(), 1)
        if "if demand > capacity:" in text
    )
    fresh = index.current_chunks(policy)
    middle = next(
        chunk
        for chunk in fresh
        if chunk.evidence.path == changed[0]
        and chunk.evidence.start_line <= behavior_line <= chunk.evidence.end_line
    )
    start, end = middle.evidence.start_line + 3, middle.evidence.end_line - 4
    fragment = Chunk(
        Evidence(changed[0], start, end, source.source_hash),
        "\n".join(source.text.splitlines()[start - 1 : end]),
    )
    available = [chunk for chunk in fresh if chunk.evidence.path != changed[0]] + [fragment]
    selected = select_impact_chunks(
        index,
        "Review demand and capacity behavior in the modified processing rules.",
        available,
        changed_paths=changed,
    )
    _assert_source_spans(index, selected)
    assert _covered(selected, changed[0]), (
        "The available changed-body fragment should remain usable"
    )
    for path in index.files:
        assert _covered(selected, path) <= _covered(available, path), (
            f"{path}: unavailable lines expanded"
        )


def test_native_typescript_changed_body_keeps_middle_behavior_and_alias_users(
    tmp_path: Path, analyzer: TypeScriptAnalyzer
) -> None:
    head = [
        "export function evaluateNurseryLoad("
        "entries: { units: number; profile?: string }[], capacity = 8) {",
        "  const weights: Record<string, number> = {",
    ]
    middle = [
        "  };",
        "  let demand = 0;",
        "  for (const entry of entries) {",
        "    if (entry.units <= 0) continue;",
        "    demand += entry.units * (weights[entry.profile ?? ''] ?? 1);",
        "  }",
        "  if (demand > capacity) return { accepted: false, demand };",
        "  const lanes = [",
    ]
    tail = [
        "  ];",
        "  return { accepted: true, demand, lane: lanes[demand % lanes.length] };",
        "}",
    ]
    rows = 170 - len(head + middle + tail)
    weights = [f"    'profile-{i:03d}': {i % 3 + 1}," for i in range(rows // 2)]
    lanes = [f"    'lane-{i:03d}'," for i in range(rows - len(weights))]
    (tmp_path / "nursery.ts").write_text("\n".join(head + weights + middle + lanes + tail) + "\n")
    (tmp_path / "consumer.ts").write_text(
        "import { evaluateNurseryLoad as assessLoad } from './nursery';\n\n"
        "export function prepareBatch(entries: { units: number }[]) {\n"
        "  return assessLoad(entries);\n}\n"
    )
    (tmp_path / "nursery.test.ts").write_text(
        "import assert from 'node:assert/strict';\n"
        "import { evaluateNurseryLoad as assessLoad } from './nursery';\n\n"
        "assert.equal(assessLoad([{ units: 12 }]).accepted, false);\n"
    )
    with Workbench(tmp_path, typescript_analyzer=analyzer) as workbench:
        index = workbench._scan()
        fresh = index.current_chunks(workbench.policy)
        selected = select_impact_chunks(index, QUERY, fresh, changed_paths=["nursery.ts"])
        _assert_complete_first_six(index, fresh, selected, ["nursery.ts"])


def test_native_exported_arrow_keeps_middle_body_and_aliased_users(
    tmp_path: Path, analyzer: TypeScriptAnalyzer
) -> None:
    head = [
        "export const evaluateAtriumLoad = ("
        "entries: { units: number; profile?: string }[], capacity = 8) => {",
        "  const weights: Record<string, number> = {",
    ]
    middle = [
        "  };",
        "  let demand = 0;",
        "  for (const entry of entries) {",
        "    if (entry.units <= 0) continue;",
        "    demand += entry.units * (weights[entry.profile ?? ''] ?? 1);",
        "  }",
        "  if (demand > capacity) return { accepted: false, demand };",
        "  const lanes = [",
    ]
    tail = [
        "  ];",
        "  return { accepted: true, demand, lane: lanes[demand % lanes.length] };",
        "};",
    ]
    rows = 96 - len(head + middle + tail)
    weights = [f"    'profile-{i:03d}': {i % 3 + 1}," for i in range(rows // 2)]
    lanes = [f"    'lane-{i:03d}'," for i in range(rows - len(weights))]
    (tmp_path / "atrium.ts").write_text("\n".join(head + weights + middle + lanes + tail) + "\n")
    (tmp_path / "consumer.ts").write_text(
        "import { evaluateAtriumLoad as assessLoad } from './atrium';\n\n"
        "export function prepareBatch(entries: { units: number }[]) {\n"
        "  return assessLoad(entries);\n}\n"
    )
    (tmp_path / "atrium.test.ts").write_text(
        "import assert from 'node:assert/strict';\n"
        "import { evaluateAtriumLoad as assessLoad } from './atrium';\n\n"
        "assert.equal(assessLoad([{ units: 12 }]).accepted, false);\n"
    )
    with Workbench(tmp_path, typescript_analyzer=analyzer) as workbench:
        index = workbench._scan()
        fresh = index.current_chunks(workbench.policy)
        selected = select_impact_chunks(
            index,
            "Assess compatibility of the modified capacity rules with their consumers and checks.",
            fresh,
            changed_paths=["atrium.ts"],
        )
        _assert_complete_first_six(index, fresh, selected, ["atrium.ts"])
