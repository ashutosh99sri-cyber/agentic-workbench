from pathlib import Path

import pytest

from agentic_workbench.changes import ChangeWorkflow
from agentic_workbench.errors import WorkbenchError
from agentic_workbench.models import Grant, text_hash
from agentic_workbench.policy import WorkspacePolicy
from agentic_workbench.state import StateStore


def setup_workflow(root: Path, request: pytest.FixtureRequest) -> ChangeWorkflow:
    policy = WorkspacePolicy(root, grants=Grant(write=True))
    store = StateStore(policy)
    request.addfinalizer(store.close)
    return ChangeWorkflow(policy, store)


def test_exact_apply_dryrun_and_conflict_safe_rollback(
    tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    (tmp_path / "app.py").write_text("value = 1\n")
    workflow = setup_workflow(tmp_path, request)
    review = workflow.propose(
        [
            {
                "path": "app.py",
                "base_hash": text_hash("value = 1\n"),
                "content": "value = 2\n",
                "delete": False,
            }
        ],
        rationale="Fix value",
    )
    assert "-value = 1" in review["diff"]
    with pytest.raises(WorkbenchError):
        workflow.apply(review["proposal_id"], approval="0" * 64)
    workflow.apply(review["proposal_id"], dry_run=True)
    assert (tmp_path / "app.py").read_text() == "value = 1\n"
    applied = workflow.apply(review["proposal_id"], approval=review["digest"])
    assert (tmp_path / "app.py").read_text() == "value = 2\n"
    rollback = workflow.review_rollback(applied["change_id"])
    (tmp_path / "app.py").write_text("value = 3\n")
    with pytest.raises(WorkbenchError):
        workflow.rollback(applied["change_id"], approval=rollback["digest"])
    assert (tmp_path / "app.py").read_text() == "value = 3\n"
    (tmp_path / "app.py").write_text("value = 2\n")
    workflow.rollback(applied["change_id"], approval=rollback["digest"])
    assert (tmp_path / "app.py").read_text() == "value = 1\n"


def test_forbidden_secret_stale_and_new_directory(
    tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    workflow = setup_workflow(tmp_path, request)
    for path in ("../escape", ".env", ".agentic/x"):
        with pytest.raises(WorkbenchError):
            workflow.propose(
                [{"path": path, "base_hash": None, "content": "x", "delete": False}],
                rationale="Unsafe",
            )
    (tmp_path / "app.py").write_text('password="example-secret"')
    with pytest.raises(WorkbenchError):
        workflow.propose(
            [
                {
                    "path": "app.py",
                    "base_hash": text_hash('password="example-secret"'),
                    "content": "clean",
                    "delete": False,
                }
            ],
            rationale="Cannot expose backup",
        )
    review = workflow.propose(
        [{"path": "new/module.py", "base_hash": None, "content": "value=1\n", "delete": False}],
        rationale="Create module",
    )
    applied = workflow.apply(review["proposal_id"], approval=review["digest"])
    assert (tmp_path / "new" / "module.py").is_file()
    rollback = workflow.review_rollback(applied["change_id"])
    workflow.rollback(applied["change_id"], approval=rollback["digest"])
    assert not (tmp_path / "new").exists()
