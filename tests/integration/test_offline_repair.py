import json
import os
import subprocess
import sys
import sysconfig
import venv
from pathlib import Path

import pytest

from agentic_workbench import Workbench

REPOSITORY = Path(__file__).resolve().parents[2]
SCRIPT = REPOSITORY / "examples/offline_repair/walkthrough.py"
FIXTURE = REPOSITORY / "examples/python_app"
POSIX_ONLY = pytest.mark.skipif(os.name != "posix", reason="Approved mutations require POSIX")


def run_walkthrough(
    cwd: Path, *arguments: str, approvals: str = "", **environment: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-B", str(SCRIPT), *arguments],
        input=approvals,
        text=True,
        capture_output=True,
        cwd=cwd,
        env={**os.environ, "PYTHONPATH": str(REPOSITORY / "src"), **environment},
        timeout=60,
        check=False,
    )


def output_value(output: str, prefix: str) -> str:
    return next(
        line.removeprefix(prefix) for line in output.splitlines() if line.startswith(prefix)
    )


@POSIX_ONLY
def test_approved_repair_retains_receipt_trace_and_exact_rollback(tmp_path: Path) -> None:
    workspace = tmp_path / "disposable"
    run = run_walkthrough(
        tmp_path,
        "--trusted-host",
        "--workspace",
        str(workspace),
        approvals="BASELINE\nAPPLY\nCHECK\nROLLBACK\n",
    )
    assert run.returncode == 0, run.stdout + run.stderr
    result = json.loads(output_value(run.stdout, "RESULT: "))
    assert result["baseline_exit_code"] != 0
    assert result["repaired_exit_code"] == 0
    assert result["rollback_state"] == "rolled_back"
    assert result["workspace"] == str(workspace.resolve())
    assert "weaker isolation than Docker" in run.stdout
    assert "awaiting_approval" in run.stdout
    assert "Baseline command review" in run.stdout
    assert "Exact patch review" in run.stdout
    assert "Repaired command review" in run.stdout
    assert "Exact rollback review" in run.stdout
    assert "Baseline receipt" in run.stdout
    assert "Retained task trace" in run.stdout
    assert "return amount_cents * (100 - discount_percent) // 100" in run.stdout
    for filename in ("app.py", "test_app.py"):
        assert (workspace / filename).read_bytes() == (FIXTURE / filename).read_bytes()
    assert not (workspace / "__pycache__").exists()
    with Workbench(workspace) as wb:
        assert wb.policy.config.provider.name == "none"
        assert wb.policy.config.commands["unit"].argv == (
            sys.executable,
            "-B",
            "-m",
            "unittest",
            "-q",
        )
        journals = wb.store.list_records("journal")
        assert len(journals) == 1
        assert journals[0]["value"]["state"] == "rolled_back"
        trace = wb.trace(result["task_id"])
        assert trace["state"] == "succeeded"
        assert {phase["phase"] for phase in trace["phases"]} >= {
            "plan",
            "execute",
            "observe",
            "verify",
            "complete",
        }
        verification = next(
            phase["verification"]
            for phase in trace["phases"]
            if phase["phase"] == "verify" and phase["verification"] is not None
        )
        assert verification["evidence"]["receipt"]["exit_code"] == 0
        assert verification["evidence"]["receipt"]["backend"] == "trusted-host"
    for command in ("trace", "status"):
        inspection = subprocess.run(
            [
                sys.executable,
                "-B",
                "-m",
                "agentic_workbench.cli",
                command,
                result["task_id"],
                "--root",
                str(workspace),
            ],
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONPATH": str(REPOSITORY / "src")},
            timeout=30,
            check=False,
        )
        assert inspection.returncode == 0, inspection.stdout + inspection.stderr
        assert json.loads(inspection.stdout)["data"]["state"] == "succeeded"


@pytest.mark.parametrize("kind", ["directory", "file", "symlink"])
def test_existing_workspace_is_refused_without_touching_it(tmp_path: Path, kind: str) -> None:
    workspace = tmp_path / "existing"
    if kind == "directory":
        workspace.mkdir()
        (workspace / "keep.txt").write_text("keep")
    elif kind == "file":
        workspace.write_text("keep")
    else:
        workspace.symlink_to(tmp_path / "missing", target_is_directory=True)
    before = workspace.lstat()
    run = run_walkthrough(tmp_path, "--trusted-host", "--workspace", str(workspace))
    assert run.returncode == 2, run.stdout + run.stderr
    assert "existing path or symlink" in run.stderr
    assert workspace.lstat() == before
    if kind == "directory":
        assert list(workspace.iterdir()) == [workspace / "keep.txt"]
        assert (workspace / "keep.txt").read_text() == "keep"
    elif kind == "file":
        assert workspace.read_text() == "keep"
    else:
        assert workspace.is_symlink()
        assert not (tmp_path / "missing").exists()


def test_trusted_host_is_required_before_workspace_creation(tmp_path: Path) -> None:
    workspace = tmp_path / "not-created"
    run = run_walkthrough(tmp_path, "--workspace", str(workspace))
    assert run.returncode == 2, run.stdout + run.stderr
    assert "requires --trusted-host" in run.stderr
    assert not workspace.exists()
    assert not list(tmp_path.iterdir())


@POSIX_ONLY
@pytest.mark.parametrize("decision", ["no", "BASELINE", ""])
def test_declined_or_missing_patch_approval_preserves_original(
    tmp_path: Path, decision: str
) -> None:
    workspace = tmp_path / "paused"
    run = run_walkthrough(
        tmp_path,
        "--trusted-host",
        "--workspace",
        str(workspace),
        approvals=f"BASELINE\n{decision}\n" if decision else "BASELINE\n",
    )
    assert run.returncode == 1, run.stdout + run.stderr
    assert "Paused before APPLY" in run.stdout
    assert (workspace / "app.py").read_bytes() == (FIXTURE / "app.py").read_bytes()
    with Workbench(workspace) as wb:
        assert not wb.store.list_records("journal")
        assert wb.trace(output_value(run.stdout, "TASK: "))["state"] == "awaiting_approval"


@POSIX_ONLY
def test_default_workspace_is_retained_on_missing_baseline_approval(tmp_path: Path) -> None:
    run = run_walkthrough(tmp_path, "--trusted-host", TMPDIR=str(tmp_path))
    assert run.returncode == 1, run.stdout + run.stderr
    assert "Paused before BASELINE" in run.stdout
    workspace = Path(output_value(run.stdout, "WORKSPACE: "))
    assert workspace.parent == tmp_path.resolve()
    assert (workspace / ".agentic/config.toml").is_file()
    assert (workspace / "app.py").read_bytes() == (FIXTURE / "app.py").read_bytes()
    assert not (workspace / "__pycache__").exists()


@POSIX_ONLY
@pytest.mark.parametrize(
    ("approvals", "stage", "state"),
    [
        ("BASELINE\nAPPLY\n", "CHECK", "awaiting_approval"),
        ("BASELINE\nAPPLY\nCHECK\n", "ROLLBACK", "succeeded"),
    ],
)
def test_missing_later_approval_retains_approved_patch(
    tmp_path: Path, approvals: str, stage: str, state: str
) -> None:
    workspace = tmp_path / "paused"
    run = run_walkthrough(
        tmp_path, "--trusted-host", "--workspace", str(workspace), approvals=approvals
    )
    assert run.returncode == 1, run.stdout + run.stderr
    assert f"Paused before {stage}" in run.stdout
    assert (
        "return amount_cents * (100 - discount_percent) // 100"
        in (workspace / "app.py").read_text()
    )
    with Workbench(workspace) as wb:
        journals = wb.store.list_records("journal")
        assert len(journals) == 1
        assert journals[0]["value"]["state"] == "applied"
        assert wb.trace(output_value(run.stdout, "TASK: "))["state"] == state


@POSIX_ONLY
def test_approved_repair_uses_python_from_venv_with_spaces(tmp_path: Path) -> None:
    environment = tmp_path / "My Project" / ".venv"
    venv.EnvBuilder(with_pip=False, symlinks=True).create(environment)
    python = environment / "bin" / "python"
    workspace = tmp_path / "disposable"
    run = subprocess.run(
        [str(python), "-B", str(SCRIPT), "--trusted-host", "--workspace", str(workspace)],
        input="BASELINE\nAPPLY\nCHECK\nROLLBACK\n",
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env={
            **os.environ,
            "PYTHONPATH": os.pathsep.join((str(REPOSITORY / "src"), sysconfig.get_path("purelib"))),
        },
        timeout=60,
        check=False,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    result = json.loads(output_value(run.stdout, "RESULT: "))
    assert result["baseline_exit_code"] != 0
    assert result["repaired_exit_code"] == 0
    assert result["rollback_state"] == "rolled_back"
    for filename in ("app.py", "test_app.py"):
        assert (workspace / filename).read_bytes() == (FIXTURE / filename).read_bytes()
    with Workbench(workspace) as wb:
        assert wb.policy.config.commands["unit"].argv == (
            str(python),
            "-B",
            "-m",
            "unittest",
            "-q",
        )
        journals = wb.store.list_records("journal")
        assert len(journals) == 1
        assert journals[0]["value"]["state"] == "rolled_back"
        assert wb.trace(result["task_id"])["state"] == "succeeded"
