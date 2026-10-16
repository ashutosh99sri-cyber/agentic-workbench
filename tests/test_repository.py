import ast
from pathlib import Path

import pytest

from agentic_workbench.config import Config, ScanConfig
from agentic_workbench.policy import WorkspacePolicy
from agentic_workbench.repository import scan_workspace


def test_scan_evidence_ignores_symbols_and_secrets(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname="demo"\ndependencies=["fastapi"]')
    (tmp_path / "app.py").write_text(
        "def double(x):\n    return x * 2\n\ndef main():\n    return double(3)\n"
    )
    (tmp_path / ".gitignore").write_text("ignored/\n")
    (tmp_path / "ignored").mkdir()
    (tmp_path / "ignored" / "danger.py").write_text('raise RuntimeError("never execute")')
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / ".gitignore").write_text("private.txt\n")
    (tmp_path / "nested" / "private.txt").write_text("private")
    (tmp_path / ".env").write_text('password="test-secret"')
    index = scan_workspace(WorkspacePolicy(tmp_path))
    assert "fastapi" in index.frameworks
    assert index.languages == ["python"]
    assert "ignored/danger.py" not in index.files
    assert "nested/private.txt" not in index.files
    assert ".env" not in index.files
    assert any(item["name"] == "double" for item in index.symbols)
    assert any(item["callee"] == "double" for item in index.calls)
    assert index.coverage["excluded"] >= 3


def test_node_manifest_and_stale_citations(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"dependencies":{"next":"1","react":"1"}}')
    (tmp_path / "app.tsx").write_text('export function Page() { return <img src="x" />; }')
    policy = WorkspacePolicy(tmp_path)
    index = scan_workspace(policy)
    assert "next" in index.frameworks and "typescript" in index.languages
    found = index.search("Page img", policy=policy)
    assert found and found[0].evidence.path == "app.tsx"
    (tmp_path / "app.tsx").write_text("changed")
    assert not index.search("Page img", policy=policy)


def test_nested_ignore_negation_overrides_parent_file_rule(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("*.py\n")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / ".gitignore").write_text("!keep.py\n")
    (nested / "keep.py").write_text("value = 1\n")
    (nested / "drop.py").write_text("value = 2\n")
    index = scan_workspace(WorkspacePolicy(tmp_path))
    assert "nested/keep.py" in index.files
    assert "nested/drop.py" not in index.files


def test_ignore_negation_cannot_override_protected_paths(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("!.env\n!private.key\n")
    (tmp_path / ".env").write_text("DEMO_VALUE=fixture\n")
    (tmp_path / "private.key").write_text("fixture key\n")
    index = scan_workspace(WorkspacePolicy(tmp_path))
    assert ".env" not in index.files
    assert "private.key" not in index.files


@pytest.mark.parametrize(
    "manifest,content,language,framework",
    [
        ("go.mod", "module example.com/app\nrequire example.com/lib v1.0.0\n", "go", None),
        ("Cargo.toml", '[package]\nname="app"\n[dependencies]\nserde="1"\n', "rust", None),
        (
            "pom.xml",
            "<project><dependencies><dependency>"
            "<artifactId>spring-boot-starter-web</artifactId>"
            "</dependency></dependencies></project>",
            "java",
            "spring",
        ),
        (
            "app.csproj",
            '<Project><ItemGroup><PackageReference Include="Example" Version="1"/>'
            "</ItemGroup></Project>",
            "csharp",
            None,
        ),
        ("Gemfile", 'gem "rails", "8"\n', "ruby", "rails"),
        ("composer.json", '{"require":{"laravel/framework":"1"}}', "php", "laravel"),
    ],
)
def test_supported_manifest_stacks(
    tmp_path: Path, manifest: str, content: str, language: str, framework: str | None
) -> None:
    (tmp_path / manifest).write_text(content)
    index = scan_workspace(WorkspacePolicy(tmp_path))
    assert language in index.languages and index.manifests[0]["dependencies"]
    if framework:
        assert framework in index.frameworks


def test_valid_deeply_chained_call_records_a_gap_and_scanning_continues(tmp_path):
    deep = "a" + ".a" * 500 + "()\n"
    ast.parse(deep)
    (tmp_path / "deep.py").write_text(deep + "def kept():\n    return 1\n")
    (tmp_path / "other.py").write_text("def other():\n    return 2\n")
    index = scan_workspace(WorkspacePolicy(tmp_path))
    assert {symbol["name"] for symbol in index.symbols} == {"kept", "other"}
    assert set(index.files) == {"deep.py", "other.py"}
    assert index.coverage["scanned"] == 2
    assert index.coverage["parse_errors"] == 1


def test_file_limit_indexes_a_full_prefix_of_collected_entries(tmp_path):
    for number in range(10):
        (tmp_path / f"{number}.py").write_text("value = 1\n")
    index = scan_workspace(WorkspacePolicy(tmp_path, Config(scan=ScanConfig(max_files=2))))
    assert len(index.files) == 2
    assert index.coverage["scanned"] == 2
    assert index.coverage["bytes"] == sum(source.size for source in index.files.values())
    assert index.coverage["limit_reached"] == 1


@pytest.mark.parametrize("manifest", ["pyproject.toml", "Cargo.toml", "package.json"])
def test_deeply_nested_manifest_records_a_gap_and_scanning_continues(tmp_path, manifest):
    nested = (
        "[" * 1_000 + "]" * 1_000
        if manifest.endswith(".json")
        else "opaque = " + "{x=" * 500 + "1" + "}" * 500 + "\n"
    )
    (tmp_path / manifest).write_text(nested)
    (tmp_path / "ordinary.py").write_text("def kept():\n    return 1\n")
    index = scan_workspace(WorkspacePolicy(tmp_path))
    assert any(symbol["name"] == "kept" for symbol in index.symbols)
    assert index.coverage["parse_errors"] == 1 and index.manifests == []


def test_parser_stack_overflow_records_a_gap_and_scanning_continues(tmp_path):
    (tmp_path / "power.py").write_text("LIMIT = " + "**".join(["2"] * 3_000) + "\n")
    (tmp_path / "ordinary.py").write_text("def kept():\n    return 1\n")
    index = scan_workspace(WorkspacePolicy(tmp_path))
    assert any(symbol["name"] == "kept" for symbol in index.symbols)
    assert index.coverage["parse_errors"] == 1


def test_parseable_deep_call_chains_scan_quickly_and_record_a_gap(tmp_path):
    import time

    # Deep enough to exceed ast.unparse's recursion limit, shallow enough to parse.
    (tmp_path / "chains.py").write_text(("x = f" + "()" * 600 + "\n") * 100)
    (tmp_path / "ordinary.py").write_text("def kept():\n    return helper()\n")
    started = time.perf_counter()
    index = scan_workspace(WorkspacePolicy(tmp_path))
    assert time.perf_counter() - started < 2
    assert index.coverage["parse_errors"] == 1
    assert any(call["callee"] == "helper" for call in index.calls)
