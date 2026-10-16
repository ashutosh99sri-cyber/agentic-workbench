"""Selection keeps exact declaration links and supplied fresh source boundaries."""

from typing import Any

from agentic_workbench.impact import select_impact_chunks
from agentic_workbench.models import Evidence, text_hash
from agentic_workbench.policy import SourceFile
from agentic_workbench.repository import RepositoryIndex
from agentic_workbench.retrieval import Chunk


def source_index(texts: dict[str, str]) -> RepositoryIndex:
    index = RepositoryIndex()
    for path, text in texts.items():
        source = SourceFile(path, text, text_hash(text), len(text.encode()), False)
        index.files[path] = source
        index.chunks.append(
            Chunk(Evidence(path, 1, len(text.splitlines()), source.source_hash), text)
        )
    return index


def cite(index: RepositoryIndex, path: str, start: int = 1, end: int = 1) -> dict[str, Any]:
    return Evidence(path, start, end, index.files[path].source_hash).to_dict()


def test_exact_declaration_beats_same_name_calls_beyond_trace_limit() -> None:
    index = source_index(
        {
            "real.ts": "export function process() { return 1; }\n",
            "other.ts": "export function process() { return 2; }\n",
            "facade.ts": "export { process as actual } from './real';\n",
            "user.ts": "actual();\n",
            **{f"wrong_{n:02}.ts": "process();\n" for n in range(51)},
        }
    )
    index.symbols = [
        {
            "name": "process",
            "kind": "function",
            "id": path + ":process",
            "evidence": cite(index, path),
        }
        for path in ("real.ts", "other.ts")
    ]
    index.calls = [
        {
            "callee": "process",
            "target_id": "other.ts:process",
            "resolution": "static-symbol",
            "evidence": cite(index, f"wrong_{n:02}.ts"),
        }
        for n in range(51)
    ] + [
        {
            "callee": "actual",
            "target_id": "real.ts:process",
            "resolution": "static-symbol",
            "evidence": cite(index, "user.ts"),
        }
    ]
    index.imports = [
        {
            "module": "./real",
            "imported": "process",
            "local": "actual",
            "target_id": "real.ts:process",
            "resolution": "static-symbol",
            "evidence": cite(index, "facade.ts"),
        }
    ]
    selected = select_impact_chunks(index, "Fix process in real.ts and show caller", index.chunks)
    paths = [chunk.evidence.path for chunk in selected]
    assert paths[0] == "real.ts"
    assert set(paths[1:3]) == {"user.ts", "facade.ts"}
    assert all(not path.startswith("wrong_") for path in paths[:3])


def test_unlinked_python_callers_keep_ambiguous_name_fallback() -> None:
    index = source_index(
        {
            "real.py": "def process():\n    return 1\n",
            "other.py": "def process():\n    return 2\n",
            "legacy.py": "process()\n",
        }
    )
    index.symbols = [
        {"name": "process", "kind": "function", "evidence": cite(index, path, 1, 2)}
        for path in ("real.py", "other.py")
    ]
    index.calls = [{"callee": "process", "evidence": cite(index, "legacy.py")}]
    selected = select_impact_chunks(index, "Fix process in real.py", index.chunks)
    assert [chunk.evidence.path for chunk in selected[:2]] == ["real.py", "legacy.py"]


def test_partial_fresh_span_cannot_expand_to_other_source_lines() -> None:
    text = "# outside fresh span\n" * 31 + "def process():\n" + "    pass\n" * 58
    index = source_index({"real.py": text})
    index.symbols = [
        {"name": "process", "kind": "function", "evidence": cite(index, "real.py", 32, 90)}
    ]
    evidence = Evidence("real.py", 30, 35, index.files["real.py"].source_hash)
    fresh = [Chunk(evidence, "\n".join(text.splitlines()[29:35]))]
    selected = select_impact_chunks(index, "Fix process in real.py", fresh)
    assert selected
    assert all(
        chunk.evidence.path == "real.py"
        and 30 <= chunk.evidence.start_line <= chunk.evidence.end_line <= 35
        and chunk.text
        == "\n".join(text.splitlines()[chunk.evidence.start_line - 1 : chunk.evidence.end_line])
        for chunk in selected
    )
