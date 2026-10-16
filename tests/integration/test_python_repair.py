import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

from agentic_workbench import CommandConfig, Config, Grant, Workbench
from agentic_workbench.models import Usage, text_hash
from agentic_workbench.providers import ProviderResult

REPOSITORY = Path(__file__).resolve().parents[2]
FIXTURE = REPOSITORY / "examples/python_app"
BUG = "    return amount_cents - discount_percent\n"
FIX = "    return amount_cents * (100 - discount_percent) // 100\n"


class ReproductionProvider:
    """Offline provider that proposes the fix only when it is shown the reproduced failure."""

    def __init__(self, root: Path) -> None:
        self.root, self.requests = root, []

    def analyze(self, request: str, context: dict, **kwargs: object) -> ProviderResult:
        self.requests.append(request)
        source = (self.root / "app.py").read_text()
        edits = []
        if "990 != 900" in request:
            edits = [
                {
                    "path": "app.py",
                    "base_hash": text_hash(source),
                    "content": source.replace(BUG, FIX),
                    "delete": False,
                }
            ]
        analysis = {
            "summary": "The discount subtracts percentage points instead of a percentage",
            "findings": [],
            "recommendations": [],
            "candidate_edits": edits,
            "limitations": ["Deterministic offline provider"],
        }
        return ProviderResult(analysis, Usage())


@pytest.mark.skipif(os.name != "posix", reason="Approved mutations require POSIX")
def test_sdk_repairs_a_reproduced_python_failure_across_reopened_approvals(
    tmp_path: Path,
) -> None:
    root = tmp_path / "python_app"
    shutil.copytree(FIXTURE, root)
    config = Config(commands={"unit": CommandConfig((sys.executable, "-B", "-m", "unittest"))})
    grants = Grant(network=True, write=True, execute=True, trusted_host=True)
    provider = ReproductionProvider(root)
    task_id: str | None = None

    def call(**approvals: str) -> dict[str, Any]:
        with Workbench(root, config, grants=grants, provider=provider) as wb:
            return wb.repair(
                "Fix the percentage discount",
                command_id="unit",
                edit_paths=["app.py"],
                backend="trusted-host",
                task_id=task_id,
                **approvals,
            )

    first = call()
    task_id = first["task_id"]
    assert first["outcome"] == "in_progress" and not provider.requests
    second = call(baseline_approval=first["reviews"]["baseline"]["digest"])
    assert second["baseline"]["exit_code"] != 0 and len(provider.requests) == 1
    assert "untrusted" in provider.requests[0].lower()
    assert FIX.strip() in second["reviews"]["change"]["diff"]
    assert (root / "app.py").read_text().endswith(BUG)
    third = call(approval=second["reviews"]["change"]["digest"])
    assert (root / "app.py").read_text().endswith(FIX)
    final = call(test_approval=third["reviews"]["test"]["digest"])

    assert final["state"] == "succeeded" and final["outcome"] == "repaired"
    assert set(final["reviews"]) == {"baseline", "change", "test"}
    [attempt] = final["attempts"]
    assert attempt["verification"]["exit_code"] == 0 and len(provider.requests) == 1
    with Workbench(root, config, grants=grants, provider=provider) as wb:
        baseline = wb.store.load("repair-run", final["baseline"]["run_id"])
        check = wb.store.load("repair-run", attempt["verification"]["run_id"])
        assert baseline["exit_code"] != 0 and "990 != 900" in baseline["stderr"]
        assert check["exit_code"] == 0 and not check["timed_out"]
        assert (
            check["snapshot_hash"]
            == wb.test_review("unit", backend="trusted-host")["snapshot_hash"]
        )
        journal = wb.store.load("journal", attempt["change_id"])
        assert journal["state"] == "applied" and journal["proposal_id"] == attempt["proposal_id"]
        phases = {phase["phase"] for phase in wb.trace(task_id)["phases"]}
        assert {"plan", "execute", "observe", "verify", "reflect", "complete"} <= phases
    for name in ("test_app.py", "pyproject.toml"):
        assert (root / name).read_bytes() == (FIXTURE / name).read_bytes()


@pytest.mark.docker
def test_an_unstartable_docker_command_is_an_unusable_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image = os.environ.get("AGENTIC_DOCKER_IMAGE")
    assert image and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/:+-]*@sha256:[a-f0-9]{64}", image), (
        "Set AGENTIC_DOCKER_IMAGE to an explicitly approved, already-local digest image; "
        "Docker acceptance requirements are not silently skipped."
    )
    if os.environ.get("AGENTIC_DOCKER_ENDPOINT"):
        monkeypatch.setenv("DOCKER_HOST", os.environ["AGENTIC_DOCKER_ENDPOINT"])
    root = tmp_path / "python_app"
    shutil.copytree(FIXTURE, root)
    # The image has no such entrypoint, so Docker itself exits 127 before any test runs.
    config = Config(commands={"unit": CommandConfig(("no-such-test-executable",), image=image)})
    provider = ReproductionProvider(root)
    grants = Grant(network=True, write=True, execute=True)
    with Workbench(root, config, grants=grants, provider=provider) as wb:
        options: dict[str, Any] = {"command_id": "unit", "edit_paths": ["app.py"]}
        first = wb.repair("Fix the percentage discount", **options)
        final = wb.repair(
            "Fix the percentage discount",
            task_id=first["task_id"],
            baseline_approval=first["reviews"]["baseline"]["digest"],
            **options,
        )
        assert final["outcome"] == "failed" and final["error"]["code"] == "BASELINE_UNUSABLE"
        assert final["baseline"]["exit_code"] == 127
        assert final["baseline"]["classification"] == "unusable"
        assert not provider.requests and final["attempts"] == []
    assert (root / "app.py").read_bytes() == (FIXTURE / "app.py").read_bytes()
