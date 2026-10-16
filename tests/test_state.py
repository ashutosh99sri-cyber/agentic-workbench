import gc
import json
import os
import sqlite3
import subprocess
import sys
import weakref
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agentic_workbench.config import Config
from agentic_workbench.errors import WorkbenchError
from agentic_workbench.policy import WorkspacePolicy
from agentic_workbench.secrets import SecretRedactor
from agentic_workbench.state import StateStore

PINS = {"agent_contracts": "a" * 64, "skills": {"discovery": "b" * 64}}


def age(store, table, *, days=100):
    timestamp = (datetime.now(UTC) - timedelta(days=days)).isoformat(timespec="microseconds")
    queries = {
        "tasks": "UPDATE tasks SET updated_at = ?",
        "records": "UPDATE records SET updated_at = ?",
        "memory": "UPDATE memory SET updated_at = ?",
    }
    with closing(sqlite3.connect(store.path)) as connection, connection:
        connection.execute(queries[table], (timestamp,))


def test_tasks_events_and_redacted_results_survive_restart(tmp_path):
    secret = "sk-proj-abcdefghijklmnopqrstuvwxyz1234567890"
    policy = WorkspacePolicy(tmp_path, redactor=SecretRedactor(["private-credential"]))
    with StateStore(policy) as store:
        task = store.create_task("discovery", f"Analyze {secret}", PINS)
        assert store.claim(task, "worker")
        store.transition(task, "running", "succeeded", result={"text": "private-credential"})
        sequences = [store.event(task, "test.event", {"status": secret}) for _ in range(2)]
        assert sequences[0] < sequences[1]
        assert store.path.stat().st_mode & 0o777 == 0o600
        for suffix in ("-wal", "-shm"):
            sidecar = store.path.with_name(store.path.name + suffix)
            if sidecar.exists():
                assert sidecar.stat().st_mode & 0o077 == 0
    with StateStore(policy) as store:
        saved = store.get_task(task)
        assert saved["state"] == "succeeded" and saved["result"] == {"text": "[REDACTED]"}
        assert secret not in str(store.export()) and "private-credential" not in str(store.export())
        assert store.event(task, "test.event", {}) > sequences[-1]
        with pytest.raises(WorkbenchError, match="CONFLICT"):
            store.resume(task, PINS)


def test_explicit_resume_and_completed_steps_survive_a_new_python_process(tmp_path):
    policy = WorkspacePolicy(tmp_path)
    with StateStore(policy) as store:
        task = store.create_task("discovery", "Analyze source", PINS)
        store.claim(task, "original-worker")
        store.transition(task, "running", "interrupted", result={"completed_steps": ["inventory"]})
    script = """
import json
import sys
from agentic_workbench.policy import WorkspacePolicy
from agentic_workbench.state import StateStore
with StateStore(WorkspacePolicy(sys.argv[1])) as store:
    resumed = store.resume(sys.argv[2], json.loads(sys.argv[3]))
    assert resumed['result']['completed_steps'] == ['inventory']
    assert store.claim(sys.argv[2], 'restarted-worker')
    store.transition(sys.argv[2], 'running', 'succeeded')
"""
    process = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path), task, json.dumps(PINS)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert process.returncode == 0, process.stderr
    with StateStore(policy) as store:
        saved = store.get_task(task)
        assert saved["state"] == "succeeded"
        assert saved["result"] == {"completed_steps": ["inventory"]}


def test_concurrent_claims_events_and_budget_are_atomic(tmp_path):
    policy = WorkspacePolicy(tmp_path)
    with StateStore(policy) as store:
        task = store.create_task("discovery", "Analyze source", PINS)

        def claim(owner):
            with StateStore(policy) as concurrent:
                return concurrent.claim(task, owner)

        with ThreadPoolExecutor(max_workers=6) as executor:
            assert sum(executor.map(claim, [f"worker-{n}" for n in range(12)])) == 1

        def event(number):
            with StateStore(policy) as concurrent:
                return concurrent.event(task, "test.event", {"elapsed_ms": number})

        with ThreadPoolExecutor(max_workers=6) as executor:
            sequences = list(executor.map(event, range(12)))
        assert len(set(sequences)) == 12

        def reserve(_):
            with StateStore(policy) as concurrent:
                try:
                    concurrent.reserve(task, 3)
                    return True
                except WorkbenchError as error:
                    assert error.code == "LIMIT_EXCEEDED"
                    return False

        with ThreadPoolExecutor(max_workers=6) as executor:
            assert sum(executor.map(reserve, range(12))) == 3
        assert store.export()["budgets"][0]["reserved"] == 3
        with pytest.raises(WorkbenchError, match="CONFLICT"):
            store.reserve(task, 4)


def test_stale_transition_and_expired_owner_require_explicit_resume(tmp_path):
    with StateStore(WorkspacePolicy(tmp_path)) as store:
        task = store.create_task("discovery", "Analyze source", PINS)
        assert store.claim(task, "worker")
        with pytest.raises(WorkbenchError, match="CONFLICT"):
            store.transition(task, "pending", "cancelled")
        with pytest.raises(WorkbenchError, match="CONFLICT"):
            store.heartbeat(task, "someone-else")
        store.heartbeat(task, "worker")
        assert store.interrupt_expired(60) == []
        with closing(sqlite3.connect(store.path)) as connection, connection:
            connection.execute("UPDATE tasks SET heartbeat_at = '2000-01-01T00:00:00+00:00'")
        assert store.interrupt_expired(60) == [task]
        assert store.get_task(task)["state"] == "interrupted"
        assert not store.claim(task, "another-worker")
        assert store.resume(task, PINS)["state"] == "pending"
        assert store.claim(task, "another-worker")
        store.transition(task, "running", "succeeded", result={"completed": True})
        with pytest.raises(WorkbenchError, match="VALIDATION_ERROR"):
            store.transition(task, "succeeded", "running")


@pytest.mark.parametrize("drift", ["skills", "agent_contracts", "policy"])
def test_resume_rejects_exact_contract_skill_and_policy_drift(tmp_path, drift):
    with StateStore(WorkspacePolicy(tmp_path)) as store:
        task = store.create_task("discovery", "Analyze source", PINS)
        store.claim(task, "worker")
        store.transition(task, "running", "failed", result={"completed_steps": ["inventory"]})
    config = Config.from_dict({"scan": {"max_files": 9}}) if drift == "policy" else Config()
    changed = {**PINS, drift: "changed"} if drift != "policy" else PINS
    with StateStore(WorkspacePolicy(tmp_path, config)) as store:
        with pytest.raises(WorkbenchError, match="CONFLICT"):
            store.resume(task, changed)
        assert store.get_task(task)["result"] == {"completed_steps": ["inventory"]}
    with StateStore(WorkspacePolicy(tmp_path)) as store:
        assert store.resume(task, PINS)["result"] == {"completed_steps": ["inventory"]}


def test_crash_pending_intent_and_unknown_receipts_block_root_replay(tmp_path):
    policy = WorkspacePolicy(tmp_path)
    with StateStore(policy) as store:
        root = store.create_task("orchestrator", "Analyze source", PINS)
        child = store.create_task("discovery", "Read source", PINS, parent_id=root)
        store.claim(child, "worker")
        store.reserve(root, 1)
        intent = store.intent(child)
        store.transition(child, "running", "interrupted", result={"completed": ["read"]})
        store.transition(root, "pending", "failed")
    with StateStore(policy) as store:
        with pytest.raises(WorkbenchError, match="OUTCOME_UNKNOWN"):
            store.resume(root, PINS)
        with pytest.raises(WorkbenchError, match="OUTCOME_UNKNOWN"):
            store.resume(child, PINS)
        store.unknown(intent)
        with pytest.raises(WorkbenchError, match="OUTCOME_UNKNOWN"):
            store.resume(child, PINS)
        with pytest.raises(WorkbenchError, match="LIMIT_EXCEEDED"):
            store.reserve(root, 1)
        store.receipt(intent, {"requests": 1, "input_tokens": 42, "output_tokens": 3})
        assert store.resume(child, PINS)["result"] == {"completed": ["read"]}
        with pytest.raises(WorkbenchError, match="CONFLICT"):
            store.receipt(intent, {})
        with pytest.raises(WorkbenchError, match="CONFLICT"):
            store.unknown(intent)


def test_pending_intent_prevents_reporting_success(tmp_path):
    with StateStore(WorkspacePolicy(tmp_path)) as store:
        task = store.create_task("discovery", "Analyze", PINS)
        store.claim(task, "worker")
        intent = store.intent(task)
        with pytest.raises(WorkbenchError, match="OUTCOME_UNKNOWN"):
            store.transition(task, "running", "succeeded")
        store.receipt(intent, {"input_tokens": None, "output_tokens": 0})
        store.transition(task, "running", "succeeded")


def test_memory_and_projections_are_workspace_scoped_and_immutable(tmp_path):
    original = tmp_path / "original"
    copied = tmp_path / "copied"
    original.mkdir()
    copied.mkdir()
    secret = "ghp_abcdefghijklmnopqrstuvwxyz1234567890"
    with StateStore(WorkspacePolicy(original)) as store:
        store.put_memory("source", "same-key", {"text": secret})
        store.put_memory("workflow", "same-key", {"text": "workflow"})
        assert store.get_memory("source", "same-key") == {"text": "[REDACTED]"}
        assert store.get_memory("workflow", "same-key") == {"text": "workflow"}
        store.save("proposal", "proposal-id", {"content": secret})
        with pytest.raises(WorkbenchError, match="CONFLICT"):
            store.save("proposal", "proposal-id", {"content": "replacement"})
        with pytest.raises(WorkbenchError, match="POLICY_DENIED"):
            store.update("proposal", "proposal-id", {})
        store.save("index", "latest", {"version": 1})
        store.update("index", "latest", {"version": 2})
        assert store.load("index", "latest") == {"version": 2}
        assert store.list_records("proposal")[0]["value"] == {"content": "[REDACTED]"}
        task = store.create_task("discovery", "Analyze", PINS)
    # Copying the DB into another root must not make another workspace's records visible.
    destination = WorkspacePolicy(copied).prepare_state_dir() / "state.sqlite3"
    destination.write_bytes((original / ".agentic/state.sqlite3").read_bytes())
    destination.chmod(0o600)
    with StateStore(WorkspacePolicy(copied)) as store:
        assert store.get_memory("source", "same-key") is None
        assert store.load("proposal", "proposal-id") is None
        assert store.list_records("proposal") == [] and store.export()["tasks"] == []
        with pytest.raises(WorkbenchError, match="VALIDATION_ERROR"):
            store.get_task(task)
        with pytest.raises(WorkbenchError, match="CONFLICT"):
            store.create_task("discovery", "Analyze", {**PINS, "workspace_id": "wrong"})


def test_prune_review_is_exact_and_preserves_recovery_and_active_task_trees(tmp_path):
    source = tmp_path / "source.py"
    source.write_text("print('source remains')\n")
    with StateStore(WorkspacePolicy(tmp_path)) as store:
        completed = store.create_task("discovery", "Completed", PINS)
        store.claim(completed, "worker")
        store.transition(completed, "running", "succeeded")
        active_root = store.create_task("orchestrator", "Active tree", PINS)
        child = store.create_task("discovery", "Completed child", PINS, parent_id=active_root)
        store.claim(child, "worker")
        store.transition(child, "running", "succeeded")
        protected_task = store.create_task("engineering", "Recovery", PINS)
        store.claim(protected_task, "worker")
        store.transition(protected_task, "running", "succeeded")
        store.save("journal", "recovery", {"state": "recovery_required", "task_id": protected_task})
        store.save("journal", "applied", {"state": "applied"})
        store.save("journal", "rolled-back", {"state": "rolled_back"})
        store.save("container", "uncleaned", {"state": "cleanup_required"})
        store.save("container", "cleaned", {"state": "cleaned"})
        store.save("index", "old-index", {"chunks": []})
        store.put_memory("source", "old-source", "content")
        for table in ("tasks", "records", "memory"):
            age(store, table, days=40)
        review = store.review_prune(30)
        assert review["tasks"] == [completed]
        ids = {row["id"] for row in review["records"]}
        assert ids == {"rolled-back", "cleaned", "old-index"}
        store.event(completed, "test.late", {})
        with pytest.raises(WorkbenchError, match="STALE_APPROVAL"):
            store.prune(review["digest"], 30)
        review = store.review_prune(30)
        store.update("index", "old-index", {"chunks": ["new"]})
        with pytest.raises(WorkbenchError, match="STALE_APPROVAL"):
            store.prune(review["digest"], 30)
        review = store.review_prune(30)
        assert store.prune(review["digest"], 30) == review
        with pytest.raises(WorkbenchError):
            store.get_task(completed)
        assert store.get_task(child)["state"] == "succeeded"
        assert store.get_task(protected_task)["state"] == "succeeded"
        assert store.load("journal", "recovery") is not None
        assert store.load("journal", "applied") is not None
        assert store.load("container", "uncleaned") is not None
        assert store.get_memory("source", "old-source") is None
        age(store, "records", days=100)
        review = store.review_prune(30)
        assert "applied" in {row["id"] for row in review["records"]}
        store.prune(review["digest"], 30)
    assert source.read_text() == "print('source remains')\n"


def test_future_and_unversioned_schema_are_refused_and_v1_is_migrated(tmp_path):
    policy = WorkspacePolicy(tmp_path)
    with StateStore(policy) as store:
        task = store.create_task("discovery", "Analyze", PINS)
        path = store.path
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("DROP TABLE intents")
        connection.execute("PRAGMA user_version = 1")
    with StateStore(policy) as store:
        assert store.get_task(task)["state"] == "pending"
        assert store.intent(task)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("PRAGMA user_version = 999")
    with pytest.raises(WorkbenchError, match="CONFIG_ERROR"):
        StateStore(policy)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("PRAGMA user_version = 0")
    with pytest.raises(WorkbenchError, match="CONFIG_ERROR"):
        StateStore(policy)


@pytest.mark.parametrize("alias", ["symlink", "hardlink", "fifo", "wal"])
def test_database_and_sidecar_aliases_are_denied_without_touching_targets(tmp_path, alias):
    policy = WorkspacePolicy(tmp_path)
    directory = policy.prepare_state_dir()
    outside = tmp_path / "outside"
    outside.write_text("outside untouched")
    outside.chmod(0o600)
    path = directory / "state.sqlite3"
    if alias == "symlink":
        path.symlink_to(outside)
    elif alias == "hardlink":
        os.link(outside, path)
    elif alias == "fifo":
        os.mkfifo(path, mode=0o600)
    else:
        (directory / "state.sqlite3-wal").symlink_to(outside)
    with pytest.raises(WorkbenchError):
        StateStore(policy)
    assert outside.read_text() == "outside untouched"


@pytest.mark.parametrize("swap", ["database", "directory"])
def test_replacing_database_or_state_directory_is_detected(tmp_path, swap):
    with StateStore(WorkspacePolicy(tmp_path)) as store:
        task = store.create_task("discovery", "Analyze", PINS)
        if swap == "database":
            store.path.rename(store.path.with_suffix(".old"))
            store.path.write_bytes(b"")
            store.path.chmod(0o600)
        else:
            store.path.parent.rename(tmp_path / ".agentic-original")
            store.path.parent.mkdir(mode=0o700)
        with pytest.raises(WorkbenchError, match="CONFLICT|POLICY_DENIED"):
            store.get_task(task)


def test_non_posix_owner_state_does_not_require_posix_directory_api(tmp_path, monkeypatch):
    policy = WorkspacePolicy(tmp_path)
    with monkeypatch.context() as patch:
        patch.setattr(os, "name", "nt")
        with StateStore(policy) as store:
            task = store.create_task("discovery", "Analyze", PINS)
            assert store.get_task(task)["state"] == "pending"
    with StateStore(policy) as store:
        assert store.get_task(task)["state"] == "pending"


@pytest.mark.parametrize(
    "usage",
    [
        {"input_tokens": -1},
        {"requests": True},
        {"estimated_cost_usd": float("nan")},
        {"unknown_receipts": 1},
        {"raw_provider_body": "bad"},
    ],
)
def test_invalid_receipt_does_not_resolve_intent(tmp_path, usage):
    with StateStore(WorkspacePolicy(tmp_path)) as store:
        task = store.create_task("discovery", "Analyze", PINS)
        intent = store.intent(task)
        with pytest.raises(WorkbenchError, match="VALIDATION_ERROR"):
            store.receipt(intent, usage)
        assert store.export()["intents"][0]["state"] == "pending"


def test_payload_limits_namespace_and_metadata_validation(tmp_path):
    with StateStore(WorkspacePolicy(tmp_path)) as store:
        task = store.create_task("discovery", "Analyze", PINS)
        with pytest.raises(WorkbenchError, match="LIMIT_EXCEEDED"):
            store.put_memory("source", "oversized", "x" * 1_048_577)
        with pytest.raises(WorkbenchError, match="VALIDATION_ERROR"):
            store.put_memory("training", "preferences", {})
        with pytest.raises(WorkbenchError, match="VALIDATION_ERROR"):
            store.put_memory([], "invalid-type", {})
        with pytest.raises(WorkbenchError, match="VALIDATION_ERROR"):
            store.transition(task, [], "cancelled")
        with pytest.raises(WorkbenchError, match="POLICY_DENIED"):
            store.update([], "invalid-type", {})
        with pytest.raises(WorkbenchError, match="VALIDATION_ERROR"):
            store.event(task, "test.event", {"prompt": "source"})
        with pytest.raises(WorkbenchError, match="VALIDATION_ERROR"):
            store.event(task, "test.event", {"elapsed_ms": float("inf")})
        with pytest.raises(WorkbenchError, match="VALIDATION_ERROR"):
            store.reserve(task, True)
        with pytest.raises(WorkbenchError, match="VALIDATION_ERROR"):
            store.save("proposal", "bad\x00id", {})


def test_unreferenced_store_releases_its_database(tmp_path: Path) -> None:
    store = StateStore(WorkspacePolicy(tmp_path))
    connection = store._connection
    reference = weakref.ref(store)
    del store
    gc.collect()
    assert reference() is None
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")


def test_cancelled_task_or_root_cannot_record_new_external_intents(tmp_path):
    with StateStore(WorkspacePolicy(tmp_path)) as store:
        root = store.create_task("orchestrator", "Root", PINS)
        child = store.create_task("intelligence", "Child", PINS, root_id=root, parent_id=root)
        sibling = store.create_task("testing", "Sibling", PINS, root_id=root, parent_id=root)
        store.intent(child)
        store.cancel_tree(child)
        with pytest.raises(WorkbenchError, match="CANCELLED"):
            store.intent(child)
        store.intent(sibling)
        store.cancel_tree(root)
        with pytest.raises(WorkbenchError, match="CANCELLED"):
            store.intent(sibling)


def test_cancelling_a_root_reaches_root_linked_tasks_and_blocks_new_ones(tmp_path):
    with StateStore(WorkspacePolicy(tmp_path)) as store:
        root = store.create_task("orchestrator", "Root", PINS)
        linked = store.create_task("reviewer", "Linked", PINS, root_id=root)
        child = store.create_task("reviewer", "Child", PINS, parent_id=linked)
        assert set(store.cancel_tree(root)) == {root, linked, child}
        assert store.cancelled(linked) and store.cancelled(child)
        for options in ({"root_id": root}, {"parent_id": root}, {"parent_id": linked}):
            with pytest.raises(WorkbenchError, match="CANCELLED"):
                store.create_task("reviewer", "Late", PINS, **options)


def test_root_cancellation_holds_for_a_task_left_pending(tmp_path):
    with StateStore(WorkspacePolicy(tmp_path)) as store:
        root = store.create_task("orchestrator", "Root", PINS)
        linked = store.create_task("reviewer", "Linked", PINS, root_id=root)
        store.cancel_tree(root)
        with closing(sqlite3.connect(store.path)) as connection, connection:
            connection.execute("UPDATE tasks SET state = 'pending' WHERE id = ?", (linked,))
        assert store.get_task(linked)["state"] == "pending" and store.cancelled(linked)
        assert not store.cancelled(store.create_task("reviewer", "Other root", PINS))


def test_a_cancelled_intermediate_task_blocks_work_anywhere_beneath_it(tmp_path):
    with StateStore(WorkspacePolicy(tmp_path)) as store:
        root = store.create_task("orchestrator", "Root", PINS)
        middle = store.create_task("reviewer", "Middle", PINS, parent_id=root)
        leaf = store.create_task("reviewer", "Leaf", PINS, parent_id=middle)
        assert store.claim(leaf, "worker")
        store.transition(leaf, "running", "succeeded", result={"done": True})
        store.cancel_tree(middle)
        with pytest.raises(WorkbenchError, match="CANCELLED"):
            store.create_task("reviewer", "Late", PINS, parent_id=leaf)
        assert store.cancelled(leaf) and not store.cancelled(root)


def test_root_trace_includes_root_linked_tasks(tmp_path):
    with StateStore(WorkspacePolicy(tmp_path)) as store:
        root = store.create_task("orchestrator", "Root", PINS)
        linked = store.create_task("reviewer", "Linked", PINS, root_id=root)
        store.event(linked, "linked.work", {"status": "observed"})
        store.cancel_tree(root)
        traced = {event["task_id"] for event in store.task_events(root)}
        assert linked in traced and root in traced


def test_operation_fingerprints_are_validated_before_release_or_finish(tmp_path):
    with StateStore(WorkspacePolicy(tmp_path)) as store:
        root = store.create_task("orchestrator", "Root", PINS)
        reservation = store.reserve_resources(root, 100, 0, 1_000, 1_000)
        with pytest.raises(WorkbenchError, match="VALIDATION_ERROR"):
            store.release_operation("resource-reservation", reservation, None)
        with pytest.raises(WorkbenchError, match="VALIDATION_ERROR"):
            store.finish_operation("resource-reservation", reservation, None, {})
        store.settle_resources(reservation, 10, 0)
        assert store.resource_usage(root)["tokens"] == 10
