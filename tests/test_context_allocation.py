"""Indivisible source windows can use spare capacity in the complete context."""

from pathlib import Path

from agentic_workbench.config import Config, Limits
from agentic_workbench.context import ContextManager
from agentic_workbench.impact import select_impact_chunks
from agentic_workbench.models import canonical_json
from agentic_workbench.policy import WorkspacePolicy
from agentic_workbench.repository import scan_workspace
from agentic_workbench.state import StateStore


def test_priority_quota_keeps_indivisible_source_when_complete_context_fits(
    tmp_path: Path,
) -> None:
    (tmp_path / "ledger.py").write_text(
        "def consolidate_balances(rows): return len(rows) # " + "x" * 1400 + "\n"
    )
    (tmp_path / "service.py").write_text(
        "from ledger import consolidate_balances\n"
        "def run_report(rows): return consolidate_balances(rows)\n"
    )
    (tmp_path / "test_ledger.py").write_text(
        "from ledger import consolidate_balances\n"
        "def test_balances(): assert consolidate_balances([1]) == 1\n"
    )
    maximum = 3500
    policy = WorkspacePolicy(tmp_path, Config(limits=Limits(context_bytes=maximum)))
    index = scan_workspace(policy)
    instruction = "Update consolidate_balances in ledger.py and show its callers and tests"
    selected = select_impact_chunks(index, instruction, index.current_chunks(policy))
    expected = {"ledger.py", "service.py", "test_ledger.py"}
    assert {chunk.evidence.path for chunk in selected} == expected
    with StateStore(policy) as store:
        context = ContextManager(policy, index, store).build(
            instruction, role="engineering", skills=[]
        )
    complete = {
        **context,
        "retrieval": [chunk.to_dict() for chunk in selected],
        "context_truncated": False,
    }
    assert len(canonical_json(complete).encode()) <= maximum
    assert len(canonical_json(context).encode()) <= maximum
    assert {chunk["evidence"]["path"] for chunk in context["retrieval"]} == expected
