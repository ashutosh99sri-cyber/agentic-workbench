import shutil
from pathlib import Path

import pytest

from agentic_workbench import Workbench, WorkbenchError
from agentic_workbench.typescript import TypeScriptAnalyzer


def analyzer() -> TypeScriptAnalyzer:
    package = Path(__file__).resolve().parents[1] / "adapters/node/node_modules/typescript"
    node = shutil.which("node")
    if not node or not package.exists():
        pytest.skip("explicit trusted TypeScript 7.0.2 installation unavailable")
    return TypeScriptAnalyzer(Path(node), package)


def test_sdk_structure_alias_trace_refresh_and_import_dependency(tmp_path: Path) -> None:
    (tmp_path / "math.ts").write_text("export function $total(x: number) { return x * 2; }\n")
    (tmp_path / "barrel.ts").write_text('export { $total as amount } from "./math";\n')
    (tmp_path / "use.ts").write_text(
        'import { amount } from "./barrel";\nexport const price = amount(2);\n'
    )
    with Workbench(tmp_path, typescript_analyzer=analyzer()) as wb:
        first = wb._scan()
        trace = first.trace("$total")
        assert {c["evidence"]["path"] for c in trace["callers"]} == {"use.ts"}
        assert trace["imports"] and trace["references"]
        second = wb._scan()
        assert second.structural["reused"] is True
        assert second.symbols == first.symbols
        assert second.fingerprint == first.fingerprint
        tools = wb.tools(index=second)
        tools.execute("trace_symbol", {"name": "$total"})
        (tmp_path / "barrel.ts").write_text("export const amount = (x: number) => x;\n")
        with pytest.raises(WorkbenchError, match="Source changed"):
            tools.execute("trace_symbol", {"name": "$total"})
        third = wb._scan()
        assert third.structural["reused"] is False
        assert not third.trace("$total")["callers"]


def test_unconfigured_structure_discloses_gap(tmp_path: Path) -> None:
    (tmp_path / "app.ts").write_text("export function total() { return 2; }\n")
    with Workbench(tmp_path) as wb:
        index = wb._scan()
        assert index.structural["status"] == "not-configured"
        assert index.structural["coverage"]["unparsed_files"] == 1
        assert not index.symbols


def test_cached_structure_rechecks_parser_identity(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "app.ts").write_text("export function total() { return 2; }\n")
    parser = analyzer()
    with Workbench(tmp_path, typescript_analyzer=parser) as wb:
        wb._scan()
        monkeypatch.setattr(parser, "_identity", lambda: {})
        with pytest.raises(WorkbenchError, match="parser identity changed"):
            wb._scan()


def test_new_resolution_source_invalidates_existing_trace(tmp_path: Path) -> None:
    (tmp_path / "math.js").write_text("export function total(x) { return x * 2; }\n")
    (tmp_path / "use.ts").write_text('import { total } from "./math";\ntotal(2);\n')
    with Workbench(tmp_path, typescript_analyzer=analyzer()) as wb:
        tools = wb.tools()
        assert tools.execute("trace_symbol", {"name": "total"})["callers"]
        (tmp_path / "math.ts").write_text("export function total(x: number) { return x; }\n")
        with pytest.raises(WorkbenchError, match="Source changed"):
            tools.execute("trace_symbol", {"name": "total"})
        current = wb._scan()
        assert {c["evidence"]["path"] for c in current.trace("total")["callers"]} == {"use.ts"}


def test_unresolved_typescript_calls_never_use_python_name_fallback(tmp_path: Path) -> None:
    (tmp_path / "lib.ts").write_text("export function work() {}\n")
    (tmp_path / "other.ts").write_text("export {}; work(); external.work();\n")
    with Workbench(tmp_path, typescript_analyzer=analyzer()) as wb:
        index = wb._scan()
        assert any(c["resolution"] == "unresolved" for c in index.calls)
        assert not index.trace("work")["callers"]


@pytest.mark.parametrize("separator", ["\u0085", "\v", "\f", "\x1c"])
def test_native_evidence_matches_reader_line_convention(tmp_path: Path, separator: str) -> None:
    (tmp_path / "app.ts").write_text(
        "// comment" + separator + "still the same comment\nexport function work() {}\nwork();\n"
    )
    with Workbench(tmp_path, typescript_analyzer=analyzer()) as wb:
        index = wb._scan()
        tools = wb.tools(index=index)
        [definition] = index.trace("work")["definitions"]
        citation = definition["evidence"]
        read = tools.execute("read_source", citation)
        assert "export function work" in read["text"]
        assert citation["start_line"] == 3
