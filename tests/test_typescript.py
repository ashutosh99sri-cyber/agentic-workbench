"""The optional native parser resolves only policy-approved source snapshots."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any

import pytest

from agentic_workbench import typescript
from agentic_workbench.errors import WorkbenchError
from agentic_workbench.policy import SourceFile
from agentic_workbench.typescript import TypeScriptAnalyzer


def source(path: str, text: str, *, secret: bool = False) -> SourceFile:
    raw = text.encode()
    return SourceFile(path, text, hashlib.sha256(raw).hexdigest(), len(raw), secret)


@pytest.fixture
def analyzer() -> TypeScriptAnalyzer:
    node = shutil.which("node")
    package = Path(__file__).resolve().parents[1] / "adapters/node/node_modules/typescript"
    if os.name != "posix" or node is None or not package.is_dir():
        if os.environ.get("AGENTIC_REQUIRE_TYPESCRIPT") == "1":
            pytest.fail("Selected native integration requires trusted Node and TypeScript 7.0.2")
        pytest.skip("Optional native tests require POSIX, Node and trusted TypeScript 7.0.2")
    return TypeScriptAnalyzer(Path(node), package)


def test_alias_reexport_namespace_and_shadowing(analyzer: TypeScriptAnalyzer) -> None:
    sources = {
        item.path: item
        for item in [
            source("lib.ts", "export function $work() { return 1; }\n"),
            source("barrel.ts", "export { $work as run } from './lib';\n"),
            source(
                "main.ts",
                "import { run as invoke } from './barrel';\n"
                "import * as lib from './lib';\n"
                "invoke(); lib.$work();\n"
                "function local(invoke: () => number) { invoke(); }\n",
            ),
        ]
    }
    result = analyzer.analyze(sources)
    definition = next(row for row in result["symbols"] if row["name"] == "$work")
    calls = [row for row in result["calls"] if row["evidence"]["start_line"] == 3]
    assert len(calls) == 2
    assert {row["target_id"] for row in calls} == {definition["id"]}
    shadow = next(row for row in result["calls"] if row["evidence"]["start_line"] == 4)
    assert shadow.get("target_id") != definition["id"]
    assert any(row.get("target_id") == definition["id"] for row in result["imports"])
    assert result["coverage"]["files_analyzed"] == 3
    assert result["parser"]["version"] == "7.0.2"


def test_js_jsx_malformed_and_dynamic(analyzer: TypeScriptAnalyzer) -> None:
    texts = {
        "lib.mjs": "export const greet = () => 1;\n",
        "main.js": "import { greet } from './lib.mjs'; greet(); import(name); obj[key]();\n",
        "view.tsx": "export function View() { return <section>Hello</section>; }\n",
        "bad.ts": "export function broken( {\n",
    }
    result = analyzer.analyze({path: source(path, text) for path, text in texts.items()})
    assert any(row["name"] == "View" for row in result["symbols"])
    assert any(row["callee"] == "greet" and row.get("target_id") for row in result["calls"])
    assert any(row["resolution"] == "dynamic" for row in result["calls"])
    assert result["coverage"]["parse_errors"] > 0
    assert result["limitations"]


def test_secret_sources_and_changed_snapshots(analyzer: TypeScriptAnalyzer) -> None:
    private = source("secret.ts", "export function hidden() {}", secret=True)
    original = source("main.ts", "export function work() {}\nwork();")
    before = analyzer.analyze({original.path: original, private.path: private})
    after_source = source("main.ts", "export function task() {}\ntask();")
    after = analyzer.analyze({after_source.path: after_source})
    assert before["coverage"]["secret_files_skipped"] == 1
    assert all(row["evidence"]["path"] != private.path for row in before["symbols"])
    assert before["symbols"][0]["id"] != after["symbols"][0]["id"]
    assert {row["name"] for row in after["symbols"]} == {"task"}


def test_explicit_unavailable_parser(tmp_path: Path) -> None:
    with pytest.raises(WorkbenchError, match="INTEGRATION_UNAVAILABLE"):
        TypeScriptAnalyzer(tmp_path / "missing-node", tmp_path / "missing-typescript")


@pytest.mark.parametrize("path", ["../bad.ts", "/bad.ts", "a\\bad.ts", "a/../bad.ts"])
def test_rejects_unsafe_snapshot_paths(analyzer: TypeScriptAnalyzer, path: str) -> None:
    with pytest.raises(WorkbenchError, match="VALIDATION_ERROR"):
        analyzer.analyze({path: source(path, "const x = 1")})


def test_rejects_malformed_bridge_output(
    analyzer: TypeScriptAnalyzer, monkeypatch: pytest.MonkeyPatch
) -> None:
    def bad_capture(*args: Any) -> dict[str, Any]:
        return {"exit_code": 0, "timed_out": False, "output_limited": False, "stdout": "{}"}

    monkeypatch.setattr("agentic_workbench.typescript._capture", bad_capture)
    with pytest.raises(WorkbenchError, match="INTEGRATION_ERROR"):
        analyzer.analyze({"a.ts": source("a.ts", "const x = 1")})


def test_utf16_offsets_and_line_endings(analyzer: TypeScriptAnalyzer) -> None:
    text = "// 😃\r\nexport function $first() {}\u2028$first();\r\n"
    result = analyzer.analyze({"unicode.ts": source("unicode.ts", text)})
    definition = next(row for row in result["symbols"] if row["name"] == "$first")
    call = result["calls"][0]
    assert definition["evidence"]["start_line"] == 2
    assert call["evidence"]["start_line"] == 3
    assert call["target_id"] == definition["id"]


def test_empty_and_unsupported_snapshots(analyzer: TypeScriptAnalyzer) -> None:
    result = analyzer.analyze({"app.py": source("app.py", "pass")})
    assert result["coverage"]["files_analyzed"] == 0
    assert result["symbols"] == []


def test_sources_never_import_application_or_use_real_filesystem(
    analyzer: TypeScriptAnalyzer, tmp_path: Path
) -> None:
    marker = tmp_path / "executed"
    outside = tmp_path / "outside.ts"
    outside.write_text("export function forbidden() {}")
    text = (
        f"import {{ forbidden }} from {json.dumps(str(outside))};\n"
        f"require('node:fs').writeFileSync({json.dumps(str(marker))}, 'bad');\n"
        "forbidden();\n"
    )
    result = analyzer.analyze({"main.ts": source("main.ts", text)})
    assert not marker.exists()
    assert not any(row["name"] == "forbidden" for row in result["symbols"])
    assert (
        next(row for row in result["calls"] if row["callee"] == "forbidden")["resolution"]
        == "unresolved"
    )


def test_virtual_filesystem_accepts_prototype_named_directories(
    analyzer: TypeScriptAnalyzer,
) -> None:
    sources = {
        "constructor/lib.ts": source("constructor/lib.ts", "export function work() {}"),
        "main.ts": source("main.ts", "import { work } from './constructor/lib'; work();"),
    }
    result = analyzer.analyze(sources)
    assert result["calls"][0]["resolution"] == "declaration"


def test_bounds_before_subprocess(analyzer: TypeScriptAnalyzer) -> None:
    with pytest.raises(WorkbenchError, match="LIMIT_EXCEEDED"):
        analyzer.analyze({f"f{i}.ts": source(f"f{i}.ts", "") for i in range(1001)})
    with pytest.raises(WorkbenchError, match="LIMIT_EXCEEDED"):
        analyzer.analyze({"big.ts": source("big.ts", " " * (8 * 1024 * 1024 + 1))})


def test_fact_bound_is_reported(analyzer: TypeScriptAnalyzer) -> None:
    item = source("many.ts", "function f() {}\n" + "f();\n" * 11000)
    result = analyzer.analyze({item.path: item})
    assert (
        sum(len(result[group]) for group in ("symbols", "calls", "imports", "references")) <= 20000
    )
    assert result["coverage"]["facts_truncated"] > 0


@pytest.mark.parametrize("field", ["path", "source_hash", "start", "start_line", "target"])
def test_rejects_forged_bridge_evidence(
    analyzer: TypeScriptAnalyzer, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    capture = typescript._capture

    def tamper(*args: Any) -> dict[str, Any]:
        outcome = capture(*args)
        value = json.loads(outcome["stdout"])
        row = value["calls"][0]
        row[field] = {
            "path": "outside.ts",
            "source_hash": "0" * 64,
            "start": 99999,
            "start_line": True,
            "target": "unknown",
        }[field]
        outcome["stdout"] = json.dumps(value)
        return outcome

    monkeypatch.setattr(typescript, "_capture", tamper)
    with pytest.raises(WorkbenchError, match="INTEGRATION_ERROR"):
        analyzer.analyze({"a.ts": source("a.ts", "function f() {}\nf();")})


def test_mismatched_version_is_explicit(analyzer: TypeScriptAnalyzer, tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name":"typescript","version":"5.9.0"}')
    with pytest.raises(WorkbenchError, match="INTEGRATION_UNAVAILABLE"):
        TypeScriptAnalyzer(analyzer.node_executable, tmp_path)


def test_capture_timeout_and_sanitized_environment(
    analyzer: TypeScriptAnalyzer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NODE_OPTIONS", "--invalid-inherited-option")
    monkeypatch.setenv("NODE_PATH", "/untrusted/modules")
    argv = [
        str(analyzer.node_executable),
        "-e",
        "process.stdout.write(JSON.stringify(process.env));",
    ]
    outcome = typescript._capture(argv, tmp_path, 2, b"")
    environment = json.loads(outcome["stdout"])
    assert "NODE_OPTIONS" not in environment and "NODE_PATH" not in environment
    assert environment["HOME"] == str(tmp_path)
    outcome = typescript._capture(
        [str(analyzer.node_executable), "-e", "setInterval(() => {}, 1000)"], tmp_path, 0.1, b""
    )
    assert outcome["timed_out"] and outcome["exit_code"] < 0


def test_capture_combined_output_limit(
    analyzer: TypeScriptAnalyzer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(typescript, "_MAX_BYTES", 128)
    script = "process.stdout.write('a'.repeat(256));process.stderr.write('b'.repeat(256));"
    outcome = typescript._capture([str(analyzer.node_executable), "-e", script], tmp_path, 2, b"")
    assert outcome["output_limited"]
    assert len(outcome["stdout"].encode()) + len(outcome["stderr"].encode()) <= 128


def test_timeout_kills_native_process_group(analyzer: TypeScriptAnalyzer, tmp_path: Path) -> None:
    marker = tmp_path / "surviving-child"
    child = (
        "setTimeout(() => require('node:fs').writeFileSync("
        + json.dumps(str(marker))
        + ", 'bad'), 700)"
    )
    script = (
        "const child = require('node:child_process').spawn(process.execPath, ['-e', "
        + json.dumps(child)
        + "]); process.stdout.write(String(child.pid)); setInterval(() => {}, 1000);"
    )
    outcome = typescript._capture(
        [str(analyzer.node_executable), "-e", script], tmp_path, 0.3, b"x" * 1000000
    )
    assert outcome["timed_out"] and outcome["stdout"].isdigit()
    time.sleep(0.8)
    assert not marker.exists()


def test_overloaded_declarations_preserve_ambiguity(analyzer: TypeScriptAnalyzer) -> None:
    text = (
        "function pick(x: string): string;\n"
        "function pick(x: number): number;\n"
        "function pick(x: unknown) { return x; }\n"
        "pick('x');\n"
    )
    result = analyzer.analyze({"overloads.ts": source("overloads.ts", text)})
    assert result["calls"][0]["resolution"] == "ambiguous"
    assert "target_id" not in result["calls"][0]


def test_parser_pin_changes_are_rejected(
    analyzer: TypeScriptAnalyzer, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(analyzer, "_identity", lambda: {})
    with pytest.raises(WorkbenchError, match="CONFLICT"):
        analyzer.analyze({"a.ts": source("a.ts", "const a = 1;")})


def test_optional_parser_fixture_skips_without_a_toolchain(monkeypatch) -> None:
    monkeypatch.delenv("AGENTIC_REQUIRE_TYPESCRIPT", raising=False)
    monkeypatch.setattr(shutil, "which", lambda _: None)
    with pytest.raises(pytest.skip.Exception):
        analyzer.__wrapped__()
    monkeypatch.setenv("AGENTIC_REQUIRE_TYPESCRIPT", "1")
    with pytest.raises(pytest.fail.Exception, match="Selected native integration"):
        analyzer.__wrapped__()
