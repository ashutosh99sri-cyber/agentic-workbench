from pathlib import Path

from agentic_workbench import Workbench


def test_readonly_public_interfaces(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("def answer():\n    return 42\n", encoding="utf-8")
    with Workbench(tmp_path) as wb:
        wb.init()
        assert wb.scan()["languages"] == ["python"]
        assert wb.explain("app.py")["mode"] == "static"
        assert wb.plan("Explain answer")["results"]
        assert wb.search("answer")["chunks"]
