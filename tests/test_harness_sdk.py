import hashlib
import json
import sys
from pathlib import Path

import pytest

from agentic_workbench import (
    CommandConfig,
    Config,
    ExecutionLimits,
    Grant,
    Observation,
    Plan,
    Step,
    Verification,
    Workbench,
    WorkbenchError,
)
from agentic_workbench.cli import main


def test_builtin_sdk_analysis_is_explicitly_source_verified(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("def answer():\n    return 42\n")
    with Workbench(tmp_path) as wb:
        result = wb.execute("Explain answer and its callers")
        assert result["state"] == "succeeded"
        assert result["verification"]["evidence"]["scope"] == "source-contracts"
        trace = wb.trace(result["task_id"])
        assert {p["phase"] for p in trace["phases"]} >= {
            "plan",
            "execute",
            "observe",
            "verify",
            "complete",
        }
        assert wb.resume(result["task_id"])["state"] == "succeeded"


def test_builtin_sdk_apply_check_review_and_reopen(tmp_path: Path) -> None:
    original = "def answer():\n    return 41\n"
    (tmp_path / "app.py").write_text(original)
    (tmp_path / "test_app.py").write_text("from app import answer\nassert answer() == 42\n")
    config = Config(commands={"unit": CommandConfig((sys.executable, "test_app.py"))})
    grants = Grant(write=True, execute=True, trusted_host=True)
    with Workbench(tmp_path, config, grants=grants) as wb:
        proposal = wb.propose(
            [
                {
                    "path": "app.py",
                    "base_hash": hashlib.sha256(original.encode()).hexdigest(),
                    "content": original.replace("41", "42"),
                    "delete": False,
                }
            ],
            rationale="Correct regression",
        )
        first = wb.execute(
            "Repair answer",
            proposal_id=proposal["proposal_id"],
            command_id="unit",
            backend="trusted-host",
        )
        assert first["state"] == "awaiting_approval"
        assert (tmp_path / "app.py").read_text() == original
        change_digest = first["reviews"]["change"]["digest"]
    with Workbench(tmp_path, config, grants=grants) as wb:
        second = wb.execute(
            "Repair answer",
            proposal_id=proposal["proposal_id"],
            command_id="unit",
            backend="trusted-host",
            task_id=first["task_id"],
            approval=change_digest,
        )
        assert second["state"] == "awaiting_approval"
        assert (tmp_path / "app.py").read_text().endswith("42\n")
        test_digest = second["reviews"]["test"]["digest"]
    with Workbench(tmp_path, config, grants=grants) as wb:
        final = wb.execute(
            "Repair answer",
            proposal_id=proposal["proposal_id"],
            command_id="unit",
            backend="trusted-host",
            task_id=first["task_id"],
            approval=change_digest,
            test_approval=test_digest,
        )
        assert final["state"] == "succeeded"
        assert final["verification"]["evidence"]["receipt"]["exit_code"] == 0
        assert len(wb.store.list_records("journal")) == 1


def test_cli_harness_discovery_context_execute_trace(tmp_path: Path, capsys) -> None:
    (tmp_path / "app.py").write_text("def answer():\n    return 42\n")
    for command in (["tools"], ["skills"], ["context", "answer"], ["execute", "Explain answer"]):
        assert main([*command, "--root", str(tmp_path)]) == 0
        envelope = json.loads(capsys.readouterr().out)
        assert envelope["ok"]
    task_id = envelope["data"]["task_id"]
    assert main(["trace", task_id, "--root", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)["data"]["phases"]


def test_sdk_cancel_is_terminal_for_failed_execution(tmp_path: Path) -> None:
    with Workbench(tmp_path) as wb:
        harness = wb.harness(
            planner=lambda request: Plan((Step("read", "read"),)),
            executor=lambda step, context: Observation(True, {"read": True}),
            verifier=lambda request: Verification(False, {"check": False}),
            pins={"callbacks": "cancel-regression"},
            limits=ExecutionLimits(max_replans=0),
        )
        with pytest.raises(WorkbenchError, match="REPLAN_EXHAUSTED"):
            harness.execute("Verify failure cancellation")
        task_id = wb.store.export()["tasks"][0]["id"]
        assert wb.cancel(task_id)["task"]["state"] == "cancelled"
        assert harness.cancel(task_id)["state"] == "cancelled"
        with pytest.raises(WorkbenchError, match="CONFLICT"):
            harness.resume(task_id)


def test_cli_tools_supports_all_valid_command_names(tmp_path: Path, capsys) -> None:
    with Workbench(tmp_path) as wb:
        wb.init()
    names = ["unit-test", "unit_test", "long" + "x" * 60]
    with (tmp_path / ".agentic/config.toml").open("a") as output:
        for name in names:
            output.write(f'\n[commands.{name}]\nargv = ["python3", "-V"]\n')
    assert main(["tools", "--root", str(tmp_path)]) == 0
    tools = json.loads(capsys.readouterr().out)["data"]["tools"]
    commands = [tool for tool in tools if tool["backend"] == "cli"]
    assert len(commands) == len({tool["name"] for tool in commands}) == 3
