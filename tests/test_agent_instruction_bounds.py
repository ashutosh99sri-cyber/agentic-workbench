"""Valid agent instructions retain their wider bound than public search queries."""

from pathlib import Path

import pytest

from agentic_workbench import Workbench
from agentic_workbench.skills import ROLES


@pytest.mark.parametrize("role", ROLES)
def test_long_valid_instruction_succeeds_statically_and_persists(tmp_path: Path, role: str) -> None:
    (tmp_path / "app.py").write_text("def invoice(value):\n    return value * 2\n")
    instruction = "Review invoice in app.py. " + "additional context " * 260
    assert 4096 < len(instruction) <= 8192
    with Workbench(tmp_path) as wb:
        result = wb.run_agent(role, instruction)
        task = wb.store.get_task(result["task_id"])
        assert result["agent"] == role and result["mode"] == "static"
        assert result["usage"]["requests"] == 0
        assert task["state"] == "succeeded"
        assert task["instruction"] == instruction
        assert task["result"] == result
