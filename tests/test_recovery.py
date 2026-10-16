import os
import subprocess
import sys
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from agentic_workbench.errors import WorkbenchError
from agentic_workbench.models import Grant, text_hash
from agentic_workbench.sdk import Workbench


def edits(paths):
    return [
        {
            "path": path,
            "base_hash": text_hash("original\n"),
            "content": "changed\n",
            "delete": False,
        }
        for path in paths
    ]


def test_ordinary_failure_restores_all_eligible_targets(tmp_path, monkeypatch):
    for path in ("a.py", "b.py"):
        (tmp_path / path).write_text("original\n")
    with Workbench(tmp_path, grants=Grant(write=True)) as wb:
        proposal = wb.propose(edits(("a.py", "b.py")), rationale="Two file change")
        from agentic_workbench.changes import replace_source

        calls = 0

        def fail_second(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise WorkbenchError("STATE_ERROR", "Injected source failure")
            return replace_source(*args, **kwargs)

        monkeypatch.setattr("agentic_workbench.changes.replace_source", fail_second)
        with pytest.raises(WorkbenchError, match="STATE_ERROR"):
            wb.apply(proposal["proposal_id"], approval=proposal["digest"], dry_run=False)
        assert all((tmp_path / path).read_text() == "original\n" for path in ("a.py", "b.py"))
        journal = wb.store.list_records("journal")[0]["value"]
        assert journal["state"] == "rolled_back" and journal["recovery_issues"] == []
        assert not list(tmp_path.glob(".agentic-stage-*"))


def test_later_edit_prevents_any_automatic_compensation(tmp_path, monkeypatch):
    for path in ("a.py", "b.py"):
        (tmp_path / path).write_text("original\n")
    with Workbench(tmp_path, grants=Grant(write=True)) as wb:
        proposal = wb.propose(edits(("a.py", "b.py")), rationale="Two file change")
        from agentic_workbench.changes import replace_source

        def fail_second(*args, **kwargs):
            if args[1] == "b.py":
                (tmp_path / "b.py").write_text("later user edit\n")
                raise WorkbenchError("STATE_ERROR", "Injected source failure")
            return replace_source(*args, **kwargs)

        monkeypatch.setattr("agentic_workbench.changes.replace_source", fail_second)
        with pytest.raises(WorkbenchError):
            wb.apply(proposal["proposal_id"], approval=proposal["digest"], dry_run=False)
        assert (tmp_path / "a.py").read_text() == "changed\n"
        assert (tmp_path / "b.py").read_text() == "later user edit\n"
        assert wb.store.list_records("journal")[0]["value"]["state"] == "recovery_required"


_CRASH = """
import os
import sys
from unittest.mock import patch
from agentic_workbench.sdk import Workbench
from agentic_workbench.models import Grant

phase = sys.argv[4]
def stop():
    os._exit(91)

with Workbench(sys.argv[1], grants=Grant(write=True)) as wb:
    original_save, original_update = wb.store.save, wb.store.update
    original_mkdir, original_open = os.mkdir, os.open
    original_write, original_replace = os.write, os.replace
    def save(kind, identifier, value):
        if phase == 'before_journal' and kind == 'journal':
            stop()
        original_save(kind, identifier, value)
        if phase == 'after_journal' and kind == 'journal':
            stop()
    def update(kind, identifier, value):
        original_update(kind, identifier, value)
        if kind == 'journal':
            directories = value.get('created_directories', [])
            if (phase == 'after_mkdir_receipt' and directories
                    and directories[-1]['state'] == 'created'):
                stop()
            stages = value.get('stages', [])
            if phase == 'before_stage' and stages and stages[-1]['state'] == 'pending':
                stop()
            if phase == 'before_write' and stages and stages[-1]['state'] == 'writing':
                stop()
    def mkdir(*args, **kwargs):
        if phase == 'before_mkdir' and args[0] == 'new':
            stop()
        original_mkdir(*args, **kwargs)
        if phase == 'after_mkdir':
            stop()
    def opened(path, *args, **kwargs):
        fd = original_open(path, *args, **kwargs)
        if phase == 'after_stage_open' and str(path).startswith('.agentic-stage-'):
            stop()
        return fd
    def write(fd, data):
        written = original_write(fd, data)
        if phase == 'after_write':
            stop()
        return written
    def replace(*args, **kwargs):
        original_replace(*args, **kwargs)
        if phase == 'after_replace':
            stop()
    with patch.object(wb.store, 'save', save), patch.object(wb.store, 'update', update), \
         patch('agentic_workbench.writer.os.mkdir', mkdir), \
         patch('agentic_workbench.writer.os.open', opened), \
         patch('agentic_workbench.writer.os.write', write), \
         patch('agentic_workbench.writer.os.replace', replace):
        wb.apply(sys.argv[2], approval=sys.argv[3], dry_run=False)
"""


@pytest.mark.parametrize(
    "phase",
    [
        "before_journal",
        "after_journal",
        "before_mkdir",
        "after_mkdir",
        "after_mkdir_receipt",
        "before_stage",
        "after_stage_open",
        "before_write",
        "after_write",
        "after_replace",
    ],
)
def test_process_crashes_have_durable_honest_recovery(tmp_path, phase):
    with Workbench(tmp_path, grants=Grant(write=True)) as wb:
        proposal = wb.propose(
            [{"path": "new/app.py", "base_hash": None, "content": "changed\n", "delete": False}],
            rationale="New source file",
        )
    process = subprocess.run(
        [
            sys.executable,
            "-c",
            _CRASH,
            str(tmp_path),
            proposal["proposal_id"],
            proposal["digest"],
            phase,
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert process.returncode == 91, process.stderr
    with Workbench(tmp_path, grants=Grant(write=True)) as wb:
        records = wb.store.list_records("journal")
        if phase == "before_journal":
            assert records == [] and not (tmp_path / "new").exists()
            return
        record = records[0]
        assert record["value"]["state"] == "applying"
        review = wb.review_rollback(record["id"])
        result = wb.rollback(record["id"], approval=review["digest"], dry_run=False)
        assert not (tmp_path / "new/app.py").exists()
        if phase in {"after_mkdir", "after_stage_open"}:
            assert result["state"] == "recovery_required" and result["recovery_issues"]
            assert (tmp_path / "new").exists()
        else:
            assert result["state"] == "rolled_back" and not (tmp_path / "new").exists()


@pytest.mark.parametrize("change", ["content", "symlink", "hardlink", "fifo"])
def test_changed_or_replaced_stage_is_not_deleted(tmp_path, change):
    with Workbench(tmp_path, grants=Grant(write=True)) as wb:
        proposal = wb.propose(
            [{"path": "new/app.py", "base_hash": None, "content": "changed\n", "delete": False}],
            rationale="New file",
        )
    process = subprocess.run(
        [
            sys.executable,
            "-c",
            _CRASH,
            str(tmp_path),
            proposal["proposal_id"],
            proposal["digest"],
            "after_write",
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert process.returncode == 91, process.stderr
    with Workbench(tmp_path, grants=Grant(write=True)) as wb:
        record = wb.store.list_records("journal")[0]
        stage = tmp_path / record["value"]["stages"][0]["path"]
        outside = tmp_path / "outside.py"
        outside.write_text("outside remains\n")
        if change == "content":
            stage.write_text("later stage edit\n")
        else:
            stage.unlink()
            if change == "symlink":
                stage.symlink_to(outside)
            elif change == "hardlink":
                os.link(outside, stage)
            else:
                os.mkfifo(stage)
        review = wb.review_rollback(record["id"])
        result = wb.rollback(record["id"], approval=review["digest"], dry_run=False)
        assert result["state"] == "recovery_required"
        assert stage.exists() or stage.is_symlink()
        if change == "content":
            assert stage.read_text() == "later stage edit\n"
        assert outside.read_text() == "outside remains\n"


def test_empty_replacement_directory_is_not_removed(tmp_path):
    with Workbench(tmp_path, grants=Grant(write=True)) as wb:
        proposal = wb.propose(
            [{"path": "new/app.py", "base_hash": None, "content": "changed\n", "delete": False}],
            rationale="New file",
        )
    process = subprocess.run(
        [
            sys.executable,
            "-c",
            _CRASH,
            str(tmp_path),
            proposal["proposal_id"],
            proposal["digest"],
            "after_mkdir_receipt",
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert process.returncode == 91, process.stderr
    (tmp_path / "new").rename(tmp_path / "original-created")
    (tmp_path / "new").mkdir()
    with Workbench(tmp_path, grants=Grant(write=True)) as wb:
        record = wb.store.list_records("journal")[0]
        review = wb.review_rollback(record["id"])
        result = wb.rollback(record["id"], approval=review["digest"], dry_run=False)
        assert result["state"] == "recovery_required" and (tmp_path / "new").is_dir()


def test_staging_edit_conflict_survives_apply_and_compensation(tmp_path):
    target = tmp_path / "app.py"
    target.write_text("original\n")
    with Workbench(tmp_path, grants=Grant(write=True)) as wb:
        proposal = wb.propose(edits(("app.py",)), rationale="Change source")
        original_write = os.write

        def editor_write(fd, data):
            target.write_text("later user edit\n")
            return original_write(fd, data)

        with patch("agentic_workbench.writer.os.write", editor_write):
            with pytest.raises(WorkbenchError, match="CONFLICT"):
                wb.apply(proposal["proposal_id"], approval=proposal["digest"], dry_run=False)
        assert target.read_text() == "later user edit\n"
        assert wb.store.list_records("journal")[0]["value"]["state"] == "recovery_required"


def test_compensation_failure_retains_recovery_evidence(tmp_path, monkeypatch):
    for path in ("a.py", "b.py"):
        (tmp_path / path).write_text("original\n")
    with Workbench(tmp_path, grants=Grant(write=True)) as wb:
        proposal = wb.propose(edits(("a.py", "b.py")), rationale="Two file change")
        from agentic_workbench.changes import replace_source

        calls = 0

        def fail_after_first(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls > 1:
                raise WorkbenchError("STATE_ERROR", "Injected write and restoration failure")
            return replace_source(*args, **kwargs)

        monkeypatch.setattr("agentic_workbench.changes.replace_source", fail_after_first)
        with pytest.raises(WorkbenchError):
            wb.apply(proposal["proposal_id"], approval=proposal["digest"], dry_run=False)
        journal = wb.store.list_records("journal")[0]["value"]
        assert journal["state"] == "recovery_required" and journal["recovery_issues"]
        assert (tmp_path / "a.py").read_text() == "changed\n"
        assert journal["edits"][0]["original"] == "original\n"


def test_keyboard_interrupt_keeps_partial_write_for_explicit_recovery(tmp_path, monkeypatch):
    for path in ("a.py", "b.py"):
        (tmp_path / path).write_text("original\n")
    with Workbench(tmp_path, grants=Grant(write=True)) as wb:
        proposal = wb.propose(edits(("a.py", "b.py")), rationale="Two file change")
        from agentic_workbench.changes import replace_source

        def interrupt_second(*args, **kwargs):
            if args[1] == "b.py":
                raise KeyboardInterrupt
            return replace_source(*args, **kwargs)

        monkeypatch.setattr("agentic_workbench.changes.replace_source", interrupt_second)
        with pytest.raises(KeyboardInterrupt):
            wb.apply(proposal["proposal_id"], approval=proposal["digest"], dry_run=False)
        record = wb.store.list_records("journal")[0]
        assert record["value"]["state"] == "recovery_required"
        assert (tmp_path / "a.py").read_text() == "changed\n"
        monkeypatch.setattr("agentic_workbench.changes.replace_source", replace_source)
        review = wb.review_rollback(record["id"])
        result = wb.rollback(record["id"], approval=review["digest"], dry_run=False)
        assert result["state"] == "rolled_back"
        assert all((tmp_path / path).read_text() == "original\n" for path in ("a.py", "b.py"))


def test_deleted_source_is_compensated_with_its_original_mode(tmp_path, monkeypatch):
    target = tmp_path / "a.py"
    target.write_text("original\n")
    target.chmod(0o640)
    (tmp_path / "b.py").write_text("original\n")
    with Workbench(tmp_path, grants=Grant(write=True)) as wb:
        proposal = wb.propose(
            [
                {
                    "path": "a.py",
                    "base_hash": text_hash("original\n"),
                    "content": None,
                    "delete": True,
                },
                *edits(("b.py",)),
            ],
            rationale="Delete and change source",
        )
        from agentic_workbench.changes import replace_source

        def fail_second(*args, **kwargs):
            if args[1] == "b.py":
                raise WorkbenchError("STATE_ERROR", "Injected source failure")
            return replace_source(*args, **kwargs)

        monkeypatch.setattr("agentic_workbench.changes.replace_source", fail_second)
        with pytest.raises(WorkbenchError):
            wb.apply(proposal["proposal_id"], approval=proposal["digest"], dry_run=False)
        assert target.read_text() == "original\n" and target.stat().st_mode & 0o777 == 0o640
        assert wb.store.list_records("journal")[0]["value"]["state"] == "rolled_back"


def test_rollback_rechecks_approval_digest_under_writer_lock(tmp_path, monkeypatch):
    target = tmp_path / "app.py"
    target.write_text("original\n")
    with Workbench(tmp_path, grants=Grant(write=True)) as wb:
        proposal = wb.propose(edits(("app.py",)), rationale="Change source")
        result = wb.apply(proposal["proposal_id"], approval=proposal["digest"], dry_run=False)
        review = wb.review_rollback(result["change_id"])

        @contextmanager
        def changed_journal_lock(policy):
            journal = wb.store.load("journal", result["change_id"])
            journal["state"] = "recovery_required"
            wb.store.update("journal", result["change_id"], journal)
            yield

        monkeypatch.setattr("agentic_workbench.changes.writer_lock", changed_journal_lock)
        with pytest.raises(WorkbenchError, match="STALE_APPROVAL"):
            wb.rollback(result["change_id"], approval=review["digest"], dry_run=False)
        assert target.read_text() == "changed\n"
