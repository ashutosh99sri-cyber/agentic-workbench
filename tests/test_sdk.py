from pathlib import Path

from agentic_workbench.sdk import Workbench


def test_sdk_init_preserves_configuration_and_coordinates(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("def value():\n    return 1\n")
    with Workbench(tmp_path) as wb:
        assert wb.init()["configuration_created"]
        original = (tmp_path / ".agentic/config.toml").read_bytes()
        assert not wb.init()["configuration_created"]
        assert (tmp_path / ".agentic/config.toml").read_bytes() == original
        assert wb.scan()["languages"] == ["python"]
        assert wb.explain("app.py")["evidence"]
        plan = wb.plan("Improve value")
        assert len(plan["results"]) == 6
        assert wb.task_status(plan["task_id"])["state"] == "succeeded"
        assert wb.search("value")["mode"] == "lexical"


def test_explicit_resume_abandoned_claim(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("value=1\n")
    with Workbench(tmp_path) as wb:
        runtime = wb._runtime()
        identifier = wb.store.create_task("intelligence", "value", runtime.pins("intelligence"))
        assert wb.store.claim(identifier, "abandoned-fixture")
        wb.store._connection.execute(
            "UPDATE tasks SET heartbeat_at = ? WHERE id = ?",
            ("2000-01-01T00:00:00+00:00", identifier),
        )
        assert wb.resume(identifier)["mode"] == "static"
