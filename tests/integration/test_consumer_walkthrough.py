import json
import os
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

WALKTHROUGH = Path(__file__).resolve().parents[2] / "examples" / "sdk_walkthrough.py"


def run_walkthrough(tmp_path: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    assert Path(sys.executable).is_absolute()
    return subprocess.run(
        [sys.executable, "-I", str(WALKTHROUGH), *arguments],
        cwd=tmp_path,
        env={**os.environ, "OPENAI_API_KEY": "walkthrough-environment-sentinel"},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_installed_sdk_walkthrough_is_offline_and_preserves_source(tmp_path: Path) -> None:
    result = run_walkthrough(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["executed"] is False
    assert report["scan_files"] == 2
    assert report["explanation_mode"] == "static"
    assert report["provider_requests"] == 0
    assert report["source_unchanged"] is True
    assert report["original_sha256"] == report["final_sha256"]
    assert "discount_percent" in report["review"]["diff"]
    assert len(report["review"]["digest"]) == 64
    assert report["dry_run"]["digest"] == report["review"]["digest"]
    assert report["tests"] == {}
    assert not Path(report["temporary_root"]).exists()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.skipif(os.name != "posix", reason="Approved mutation/execution requires POSIX")
def test_installed_sdk_walkthrough_fails_then_passes_and_rolls_back(tmp_path: Path) -> None:
    result = run_walkthrough(tmp_path, "--execute")
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["executed"] is True
    assert report["tests"]["before"]["exit_code"] != 0
    assert "990 != 900" in report["tests"]["before"]["stderr"]
    assert report["tests"]["after"]["exit_code"] == 0
    assert "Ran 2 tests" in report["tests"]["after"]["stderr"]
    assert report["rollback"]["change_id"] == report["applied"]["change_id"]
    assert report["source_unchanged"] is True
    assert report["original_sha256"] == report["final_sha256"]
    assert not Path(report["temporary_root"]).exists()
    assert list(tmp_path.iterdir()) == []


def test_walkthrough_rejects_existing_application_root(tmp_path: Path) -> None:
    application = tmp_path / "app.py"
    original = b"private_application = True\n"
    application.write_bytes(original)
    result = run_walkthrough(tmp_path, "--root", str(tmp_path))
    assert result.returncode == 2
    assert "unrecognized arguments" in result.stderr
    assert application.read_bytes() == original
    assert not (tmp_path / ".agentic").exists()


@pytest.mark.skipif(os.name != "posix", reason="Approved mutation/execution requires POSIX")
def test_walkthrough_rolls_back_when_postapply_evidence_fails(monkeypatch) -> None:
    namespace = runpy.run_path(str(WALKTHROUGH))
    walkthrough = namespace["walkthrough"]
    run_tests = namespace["run_tests"]
    workbench = namespace["Workbench"]
    rollback = workbench.rollback
    roots = []
    calls = 0

    def rejected_after_receipt(wb):
        nonlocal calls
        calls += 1
        receipt = run_tests(wb)
        return {**receipt, "exit_code": 1} if calls == 2 else receipt

    def observed_rollback(wb, *args, **kwargs):
        receipt = rollback(wb, *args, **kwargs)
        root = wb.policy.root
        roots.append(root)
        assert (root / "app.py").read_bytes() == namespace["SOURCE"].encode()
        assert (root / "test_app.py").read_bytes() == namespace["TESTS"].encode()
        return receipt

    monkeypatch.setitem(walkthrough.__globals__, "run_tests", rejected_after_receipt)
    monkeypatch.setattr(workbench, "rollback", observed_rollback)
    with pytest.raises(RuntimeError, match="did not pass both tests"):
        walkthrough(execute=True)
    assert calls == 2
    assert len(roots) == 1 and not roots[0].exists()
