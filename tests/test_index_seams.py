from pathlib import Path

from agentic_workbench.policy import WorkspacePolicy
from agentic_workbench.repository import (
    collect_workspace,
    index_source,
    merge_source,
    scan_workspace,
)


def test_derivation_seam_preserves_cold_scan_and_fresh_inventory(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("def double(x):\n    return x * 2\n\ndouble(3)\n")
    (tmp_path / "bad.py").write_text("def broken(\n")
    (tmp_path / "pyproject.toml").write_text('[project]\nname="demo"\ndependencies=["fastapi"]\n')
    (tmp_path / ".gitignore").write_text("ignored.py\n")
    (tmp_path / "ignored.py").write_text("def hidden(): pass\n")
    policy = WorkspacePolicy(tmp_path)
    collected = collect_workspace(policy)
    assert not collected.chunks and not collected.symbols and not collected.manifests
    assert collected.coverage["parse_errors"] == 0
    original_files = dict(collected.files)
    for source in collected.files.values():
        derived = index_source(source)
        assert not derived.files
        merge_source(collected, derived)
    cold = scan_workspace(policy)
    assert collected.files == original_files
    assert collected.to_dict() == cold.to_dict()
    assert collected.chunks == cold.chunks
    assert collected.coverage["parse_errors"] == 1


def test_optional_index_projection_corruption_does_not_block_fresh_scan(tmp_path: Path) -> None:
    from agentic_workbench import Workbench

    (tmp_path / "app.py").write_text("def value(): return 1\n")
    with Workbench(tmp_path) as wb:
        wb._scan()
        with wb.store._transaction() as connection:
            connection.execute(
                "UPDATE records SET value = ? WHERE kind = 'index' AND id = 'current'", ("{broken",)
            )
        (tmp_path / "app.py").write_text("def value(): return 2\n")
        current = wb._scan()
        assert "return 2" in current.files["app.py"].text
        assert current.cache_stats["projection_unavailable"] == 1
