import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

from agentic_workbench import CommandConfig, Config, Grant, Workbench, WorkbenchError
from agentic_workbench.cli import main
from agentic_workbench.models import Usage, text_hash
from agentic_workbench.providers import ProviderRejected, ProviderResult

pytestmark = pytest.mark.skipif(os.name != "posix", reason="Approved mutations require POSIX")

BUGGY = "def double(x):\n    return x + 2\n"
FIXED = "def double(x):\n    return x * 2\n"
WRONG = "def double(x):\n    return x + x + 1\n"
# The check logs each real run outside the workspace, so the source snapshot never changes.
CHECK = (
    "import sys\n"
    "with open(sys.argv[1], 'a') as log:\n"
    "    log.write('run\\n')\n"
    "from app import double\n"
    "assert double(5) == 10, f'double(5) returned {double(5)}'\n"
)
GRANTS = Grant(network=True, write=True, execute=True, trusted_host=True)
INSTRUCTION = "Make double return twice its input"


class Candidates:
    """Offline provider: one scripted response per request, every request recorded.

    A response is {path: content} (replacements against current source), a raw edit
    list, None for no candidate, or an exception to raise.
    """

    def __init__(self, root: Path, *responses: Any) -> None:
        self.root, self.responses, self.requests = root, list(responses), []

    def analyze(self, request: str, context: dict, **kwargs: object) -> ProviderResult:
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        if isinstance(response, list):
            edits = response
        else:
            edits = [
                {
                    "path": path,
                    "base_hash": text_hash((self.root / path).read_text())
                    if (self.root / path).exists()
                    else None,
                    "content": content,
                    "delete": False,
                }
                for path, content in (response or {}).items()
            ]
        analysis = {
            "summary": "Fixture candidate",
            "findings": [],
            "recommendations": [],
            "candidate_edits": edits,
            "limitations": ["Offline fixture"],
        }
        return ProviderResult(analysis, Usage())


def make_workspace(tmp_path: Path, source: str = BUGGY, **command: Any) -> tuple[Path, Config]:
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "app.py").write_text(source)
    (root / "test_app.py").write_text(CHECK)
    argv = (sys.executable, "test_app.py", str(tmp_path / "runs.log"))
    return root, Config(commands={"unit": CommandConfig(argv, **command)})


def runs(tmp_path: Path) -> int:
    log = tmp_path / "runs.log"
    return len(log.read_text().splitlines()) if log.exists() else 0


def repair(wb: Workbench, task_id: str | None = None, **options: Any) -> dict[str, Any]:
    options = {"edit_paths": ["app.py"], "max_attempts": 2, **options}
    return wb.repair(
        INSTRUCTION, command_id="unit", backend="trusted-host", task_id=task_id, **options
    )


def approve_baseline(wb: Workbench, **options: Any) -> dict[str, Any]:
    first = repair(wb, **options)
    digest = first["reviews"]["baseline"]["digest"]
    return repair(wb, first["task_id"], baseline_approval=digest, **options)


def test_each_effect_waits_for_its_exact_approval_and_runs_once_across_reopen(
    tmp_path: Path,
) -> None:
    root, config = make_workspace(tmp_path)
    provider = Candidates(root, {"app.py": FIXED})

    def workbench() -> Workbench:
        return Workbench(root, config, grants=GRANTS, provider=provider)

    with workbench() as wb:
        first = repair(wb)
        assert first["state"] == "awaiting_approval" and first["outcome"] == "in_progress"
        assert set(first["reviews"]) == {"baseline"} and first["baseline"] is None
        assert first["edit_paths"] == ["app.py"] and first["max_attempts"] == 2
        task = first["task_id"]
        stale = repair(wb, task, baseline_approval="0" * 64)
        assert stale["state"] == "awaiting_approval" and runs(tmp_path) == 0
        assert not provider.requests
    with workbench() as wb:
        second = repair(wb, task, baseline_approval=first["reviews"]["baseline"]["digest"])
        assert second["state"] == "awaiting_approval" and second["outcome"] == "in_progress"
        assert runs(tmp_path) == 1 and len(provider.requests) == 1
        assert second["baseline"]["exit_code"] != 0 and second["baseline"]["run_id"]
        assert (root / "app.py").read_text() == BUGGY
        change = second["reviews"]["change"]
        assert [edit["path"] for edit in change["edits"]] == ["app.py"]
        [attempt] = second["attempts"]
        assert attempt["number"] == 1 and attempt["proposal_id"] == change["proposal_id"]
        assert attempt["analysis_task_id"] and attempt["change_id"] is None
    with workbench() as wb:
        third = repair(wb, task, approval=change["digest"])
        assert third["state"] == "awaiting_approval" and (root / "app.py").read_text() == FIXED
        assert runs(tmp_path) == 1 and len(provider.requests) == 1
        assert third["attempts"][0]["change_id"]
    with workbench() as wb:
        final = repair(wb, task, test_approval=third["reviews"]["test"]["digest"])
        assert final["state"] == "succeeded" and final["outcome"] == "repaired"
        assert runs(tmp_path) == 2 and len(provider.requests) == 1
        [attempt] = final["attempts"]
        assert attempt["verification"]["exit_code"] == 0 and attempt["failure"] is None
        assert wb.store.load("repair-run", attempt["verification"]["run_id"])["exit_code"] == 0
        assert len(wb.store.list_records("journal")) == 1
        assert repair(wb, task)["outcome"] == "repaired" and runs(tmp_path) == 2
        assert wb.resume(task)["outcome"] == "repaired"


def test_polling_a_paused_repair_does_not_spend_its_step_budget(tmp_path: Path) -> None:
    root, config = make_workspace(tmp_path)
    provider = Candidates(root, {"app.py": FIXED})
    with Workbench(root, config, grants=GRANTS, provider=provider) as wb:
        first = repair(wb)
        for _ in range(40):
            assert repair(wb, first["task_id"])["state"] == "awaiting_approval"
            assert wb.resume(first["task_id"])["outcome"] == "in_progress"
        second = repair(
            wb, first["task_id"], baseline_approval=first["reviews"]["baseline"]["digest"]
        )
        assert second["state"] == "awaiting_approval" and second["reviews"]["change"]


def test_a_passing_baseline_is_already_passing_without_provider_or_edit(tmp_path: Path) -> None:
    root, config = make_workspace(tmp_path, source=FIXED)
    provider = Candidates(root)
    with Workbench(root, config, grants=GRANTS, provider=provider) as wb:
        final = approve_baseline(wb)
        assert final["state"] == "succeeded" and final["outcome"] == "already_passing"
        assert final["baseline"]["exit_code"] == 0 and final["attempts"] == []
        assert set(final["reviews"]) == {"baseline"} and not provider.requests
        assert not wb.store.list_records("proposal") and runs(tmp_path) == 1


@pytest.mark.parametrize("code", [125, 126, 127])
def test_a_command_startup_failure_exit_is_an_unusable_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: int
) -> None:
    root, config = make_workspace(tmp_path)
    provider = Candidates(root, {"app.py": FIXED})
    real = Workbench.test

    def startup_failure(self: Workbench, *args: Any, **kwargs: Any) -> dict[str, Any]:
        # Docker reserves these exits for a container command that could not start.
        return {**real(self, *args, **kwargs), "exit_code": code}

    monkeypatch.setattr(Workbench, "test", startup_failure)
    with Workbench(root, config, grants=GRANTS, provider=provider) as wb:
        final = approve_baseline(wb)
        assert final["outcome"] == "failed" and final["error"]["code"] == "BASELINE_UNUSABLE"
        assert final["baseline"]["exit_code"] == code
        assert final["baseline"]["classification"] == "unusable"
        assert wb.store.load("repair-run", final["baseline"]["run_id"])["exit_code"] == code
        assert not provider.requests and final["attempts"] == []


def test_an_output_limited_baseline_is_unusable_with_known_evidence(tmp_path: Path) -> None:
    root, config = make_workspace(tmp_path, max_output_bytes=16)
    provider = Candidates(root)
    with Workbench(root, config, grants=GRANTS, provider=provider) as wb:
        final = approve_baseline(wb)
        assert final["state"] == "failed" and final["outcome"] == "failed"
        assert final["error"]["code"] == "BASELINE_UNUSABLE"
        assert final["baseline"]["output_limited"] and final["attempts"] == []
        assert not provider.requests and (root / "app.py").read_text() == BUGGY
        again = repair(wb, final["task_id"])
        assert again["error"]["code"] == "BASELINE_UNUSABLE" and runs(tmp_path) == 1


@pytest.mark.parametrize(
    "path",
    [
        "test_app.py",
        "tests/helper.py",
        "app_test.py",
        "conftest.py",
        "setup.py",
        "README.md",
        "missing.py",
        "../app.py",
    ],
)
def test_edit_paths_must_be_existing_non_test_python_sources(tmp_path: Path, path: str) -> None:
    root, config = make_workspace(tmp_path)
    (root / "tests").mkdir()
    for name in ("tests/helper.py", "app_test.py", "conftest.py", "setup.py"):
        (root / name).write_text("VALUE = 1\n")
    (root / "README.md").write_text("# Fixture\n")
    with Workbench(root, config, grants=GRANTS, provider=Candidates(root)) as wb:
        with pytest.raises(WorkbenchError) as raised:
            repair(wb, edit_paths=[path])
        assert raised.value.code in {"VALIDATION_ERROR", "POLICY_DENIED"}
        assert not wb.store.export()["tasks"]


@pytest.mark.parametrize(
    ("options", "code"),
    [
        ({"edit_paths": []}, "VALIDATION_ERROR"),
        ({"edit_paths": ["app.py", "app.py"]}, "VALIDATION_ERROR"),
        ({"edit_paths": "app.py"}, "VALIDATION_ERROR"),
        ({"max_attempts": 0}, "VALIDATION_ERROR"),
        ({"max_attempts": 5}, "VALIDATION_ERROR"),
        ({"max_attempts": True}, "VALIDATION_ERROR"),
        ({"command_id": "missing"}, "CONFIG_ERROR"),
        ({"backend": "ssh"}, "VALIDATION_ERROR"),
    ],
)
def test_invalid_options_are_refused_before_any_task(
    tmp_path: Path, options: dict[str, Any], code: str
) -> None:
    root, config = make_workspace(tmp_path)
    arguments = {
        "command_id": "unit",
        "edit_paths": ["app.py"],
        "backend": "trusted-host",
        **options,
    }
    with Workbench(root, config, grants=GRANTS, provider=Candidates(root)) as wb:
        with pytest.raises(WorkbenchError, match=code):
            wb.repair(INSTRUCTION, **arguments)
        assert not wb.store.export()["tasks"] and runs(tmp_path) == 0


@pytest.mark.parametrize(
    ("grants", "provider", "code"),
    [
        (GRANTS, False, "INTEGRATION_UNAVAILABLE"),
        (Grant(write=True, execute=True, trusted_host=True), True, "POLICY_DENIED"),
        (Grant(network=True, execute=True, trusted_host=True), True, "POLICY_DENIED"),
        (Grant(network=True, write=True, trusted_host=True), True, "POLICY_DENIED"),
        (Grant(network=True, write=True, execute=True), True, "POLICY_DENIED"),
    ],
    ids=["no-provider", "no-network", "no-write", "no-execute", "no-trusted-host"],
)
def test_provider_and_grants_are_required_before_any_task(
    tmp_path: Path, grants: Grant, provider: bool, code: str
) -> None:
    root, config = make_workspace(tmp_path)
    adapter = Candidates(root) if provider else None
    with Workbench(root, config, grants=grants, provider=adapter) as wb:
        with pytest.raises(WorkbenchError, match=code):
            repair(wb)
        assert not wb.store.export()["tasks"] and runs(tmp_path) == 0


@pytest.mark.parametrize(
    "candidate",
    [
        {"test_app.py": "assert True\n"},
        {"app.py": FIXED, "test_app.py": "assert True\n"},
        {"helper.py": "VALUE = 1\n"},
        [{"path": "app.py", "base_hash": text_hash(BUGGY), "content": None, "delete": True}],
    ],
    ids=["test-file", "test-file-with-fix", "new-file", "deletion"],
)
def test_candidates_outside_the_allowlist_are_known_failed_attempts(
    tmp_path: Path, candidate: Any
) -> None:
    root, config = make_workspace(tmp_path)
    provider = Candidates(root, candidate, {"app.py": FIXED})
    with Workbench(root, config, grants=GRANTS, provider=provider) as wb:
        second = approve_baseline(wb)
        assert second["state"] == "awaiting_approval" and len(provider.requests) == 2
        assert [a["failure"] for a in second["attempts"]] == ["INVALID_CANDIDATE", None]
        assert second["attempts"][0]["change_id"] is None
        assert [edit["path"] for edit in second["reviews"]["change"]["edits"]] == ["app.py"]
        assert (root / "test_app.py").read_text() == CHECK and not (root / "helper.py").exists()
        assert (root / "app.py").read_text() == BUGGY


def test_attempts_without_a_candidate_exhaust_the_bounded_budget(tmp_path: Path) -> None:
    root, config = make_workspace(tmp_path)
    provider = Candidates(root, None, None)
    with Workbench(root, config, grants=GRANTS, provider=provider) as wb:
        final = approve_baseline(wb)
        assert final["state"] == "failed" and final["outcome"] == "failed"
        assert final["error"]["code"] == "REPLAN_EXHAUSTED"
        assert [a["failure"] for a in final["attempts"]] == ["NO_CANDIDATE", "NO_CANDIDATE"]
        assert len(provider.requests) == 2 and not wb.store.list_records("proposal")
        assert repair(wb, final["task_id"])["error"]["code"] == "REPLAN_EXHAUSTED"
        assert len(provider.requests) == 2


def test_a_failed_check_revises_from_the_latest_source_and_its_evidence(tmp_path: Path) -> None:
    root, config = make_workspace(tmp_path)
    provider = Candidates(root, {"app.py": WRONG}, {"app.py": FIXED})
    with Workbench(root, config, grants=GRANTS, provider=provider) as wb:
        second = approve_baseline(wb)
        task = second["task_id"]
        third = repair(wb, task, approval=second["reviews"]["change"]["digest"])
        fourth = repair(wb, task, test_approval=third["reviews"]["test"]["digest"])
        # The first candidate failed its check; the next request sees that output.
        assert fourth["state"] == "awaiting_approval" and len(provider.requests) == 2
        assert "untrusted" in provider.requests[1].lower()
        assert "double(5) returned 11" in provider.requests[1]
        assert "double(5) returned 7" in provider.requests[0]
        revision = fourth["reviews"]["change"]
        assert revision["edits"][0]["base_hash"] == text_hash(WRONG)
        fifth = repair(wb, task, approval=revision["digest"])
        final = repair(wb, task, test_approval=fifth["reviews"]["test"]["digest"])
        assert final["state"] == "succeeded" and final["outcome"] == "repaired"
        first, last = final["attempts"]
        assert first["verification"]["exit_code"] != 0 and first["failure"] == "CHECK_FAILED"
        assert last["verification"]["exit_code"] == 0 and last["failure"] is None
        assert first["change_id"] != last["change_id"] and runs(tmp_path) == 3


def test_an_exhausted_repair_leaves_the_last_candidate_for_explicit_rollback(
    tmp_path: Path,
) -> None:
    root, config = make_workspace(tmp_path)
    provider = Candidates(root, {"app.py": WRONG})
    with Workbench(root, config, grants=GRANTS, provider=provider) as wb:
        second = approve_baseline(wb, max_attempts=1)
        task = second["task_id"]
        third = repair(wb, task, approval=second["reviews"]["change"]["digest"], max_attempts=1)
        final = repair(wb, task, test_approval=third["reviews"]["test"]["digest"], max_attempts=1)
        assert final["outcome"] == "failed" and final["error"]["code"] == "REPLAN_EXHAUSTED"
        assert (root / "app.py").read_text() == WRONG
        rollback = wb.review_rollback(final["attempts"][0]["change_id"])
        assert rollback["state"] == "applied"
        wb.rollback(rollback["change_id"], approval=rollback["digest"], dry_run=False)
        assert (root / "app.py").read_text() == BUGGY


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (ProviderRejected("Request declined"), "PROVIDER_REJECTED"),
        (WorkbenchError("PROVIDER_REFUSAL", "Provider refused the request"), "PROVIDER_REFUSAL"),
        (WorkbenchError("PROVIDER_INCOMPLETE", "Response did not complete"), "PROVIDER_INCOMPLETE"),
    ],
)
def test_a_known_provider_outcome_is_a_failed_attempt(
    tmp_path: Path, error: WorkbenchError, code: str
) -> None:
    root, config = make_workspace(tmp_path)
    provider = Candidates(root, error, {"app.py": FIXED})
    with Workbench(root, config, grants=GRANTS, provider=provider) as wb:
        second = approve_baseline(wb)
        assert second["state"] == "awaiting_approval" and len(provider.requests) == 2
        assert [a["failure"] for a in second["attempts"]] == [code, None]


@pytest.mark.parametrize(
    "error",
    [
        WorkbenchError("CONFIG_ERROR", "Set the configured API key environment variable"),
        WorkbenchError("INTEGRATION_UNAVAILABLE", "Install the openai extra"),
    ],
)
def test_a_provider_configuration_error_stops_without_replay(
    tmp_path: Path, error: WorkbenchError
) -> None:
    root, config = make_workspace(tmp_path)
    provider = Candidates(root, error, {"app.py": FIXED})
    with Workbench(root, config, grants=GRANTS, provider=provider) as wb:
        stopped = approve_baseline(wb)
        assert stopped["outcome"] == "failed" and stopped["error"]["code"] == "OUTCOME_UNKNOWN"
        assert [a["failure"] for a in stopped["attempts"]] == [error.code]
        again = repair(wb, stopped["task_id"])
        assert again["error"]["code"] == "OUTCOME_UNKNOWN" and len(provider.requests) == 1


def test_a_configuration_error_after_a_sent_request_never_replays_it(tmp_path: Path) -> None:
    pytest.importorskip("openai")
    httpx = pytest.importorskip("httpx2")
    from dataclasses import replace

    from test_providers import KEY, call, response

    from agentic_workbench.config import ProviderConfig
    from agentic_workbench.policy import WorkspacePolicy
    from agentic_workbench.providers_openai import OpenAIProvider

    root, config = make_workspace(tmp_path)
    config = replace(config, provider=ProviderConfig(name="openai", model="fixture-model"))
    sent: list[Any] = []

    def handle(request: Any) -> Any:
        sent.append(request)
        read = '{"path":"app.py","start_line":1,"end_line":2,"source_hash":null}'
        return httpx.Response(200, json=response([call(arguments=read)]))

    # The first request is sent and asks for a tool; the credential is gone for the follow-up.
    keys = iter([KEY])
    adapter = OpenAIProvider(
        WorkspacePolicy(root, config, grants=GRANTS),
        credential_resolver=lambda: next(keys, None),
        transport=httpx.MockTransport(handle),
    )
    with Workbench(root, config, grants=GRANTS, provider=adapter) as wb:
        stopped = approve_baseline(wb, max_attempts=1)
        assert len(sent) == 1 and stopped["outcome"] == "failed"
        assert stopped["error"]["code"] == "OUTCOME_UNKNOWN"
        assert [a["failure"] for a in stopped["attempts"]] == ["CONFIG_ERROR"]
        again = repair(wb, stopped["task_id"], max_attempts=1)
        assert again["error"]["code"] == "OUTCOME_UNKNOWN" and len(sent) == 1


def test_an_unknown_provider_outcome_is_never_retried(tmp_path: Path) -> None:
    root, config = make_workspace(tmp_path)
    unknown = WorkbenchError("OUTCOME_UNKNOWN", "Provider transport outcome is unknown")
    provider = Candidates(root, unknown, {"app.py": FIXED})
    with Workbench(root, config, grants=GRANTS, provider=provider) as wb:
        final = approve_baseline(wb)
        assert final["state"] == "failed" and final["outcome"] == "failed"
        assert final["error"]["code"] == "OUTCOME_UNKNOWN" and len(provider.requests) == 1
        again = repair(wb, final["task_id"])
        assert again["error"]["code"] == "OUTCOME_UNKNOWN" and len(provider.requests) == 1
        assert (root / "app.py").read_text() == BUGGY


def test_source_drift_before_apply_is_refused_without_overwriting(tmp_path: Path) -> None:
    root, config = make_workspace(tmp_path)
    provider = Candidates(root, {"app.py": FIXED})
    with Workbench(root, config, grants=GRANTS, provider=provider) as wb:
        second = approve_baseline(wb)
        edited = BUGGY + "# user edit\n"
        (root / "app.py").write_text(edited)
        final = repair(wb, second["task_id"], approval=second["reviews"]["change"]["digest"])
        assert final["outcome"] == "failed" and final["error"]["code"] == "STALE"
        assert (root / "app.py").read_text() == edited
        assert not wb.store.list_records("journal")


def test_a_check_whose_source_changed_afterwards_is_not_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, config = make_workspace(tmp_path)
    provider = Candidates(root, {"app.py": FIXED})
    with Workbench(root, config, grants=GRANTS, provider=provider) as wb:
        second = approve_baseline(wb, max_attempts=1)
        task = second["task_id"]
        third = repair(wb, task, approval=second["reviews"]["change"]["digest"], max_attempts=1)
        real = Workbench.test

        def drifting(self: Workbench, *args: Any, **kwargs: Any) -> dict[str, Any]:
            receipt = real(self, *args, **kwargs)
            (root / "app.py").write_text(FIXED + "# edited after the check\n")
            return receipt

        monkeypatch.setattr(Workbench, "test", drifting)
        final = repair(wb, task, test_approval=third["reviews"]["test"]["digest"], max_attempts=1)
        assert final["outcome"] == "failed" and final["error"]["code"] == "REPLAN_EXHAUSTED"
        assert final["attempts"][0]["verification"]["exit_code"] == 0


def test_changed_options_or_configuration_are_refused_on_resume(tmp_path: Path) -> None:
    root, config = make_workspace(tmp_path)
    (root / "util.py").write_text("VALUE = 1\n")
    with Workbench(root, config, grants=GRANTS, provider=Candidates(root)) as wb:
        task = repair(wb)["task_id"]
        for options in ({"edit_paths": ["app.py", "util.py"]}, {"max_attempts": 3}):
            with pytest.raises(WorkbenchError, match="CONFLICT"):
                repair(wb, task, **options)
    changed = Config(commands={"unit": CommandConfig(config.commands["unit"].argv, timeout=30)})
    with Workbench(root, changed, grants=GRANTS, provider=Candidates(root)) as wb:
        with pytest.raises(WorkbenchError, match="CONFLICT"):
            repair(wb, task)
        assert runs(tmp_path) == 0


def test_a_cancelled_repair_stops_before_its_next_effect(tmp_path: Path) -> None:
    root, config = make_workspace(tmp_path)
    provider = Candidates(root, {"app.py": FIXED})
    with Workbench(root, config, grants=GRANTS, provider=provider) as wb:
        first = repair(wb)
        wb.cancel(first["task_id"])
        final = repair(
            wb, first["task_id"], baseline_approval=first["reviews"]["baseline"]["digest"]
        )
        assert final["state"] == "cancelled" and final["outcome"] == "failed"
        assert runs(tmp_path) == 0 and not provider.requests


def test_cli_repair_accepts_its_options_and_validates_before_work(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, config = make_workspace(tmp_path)
    (root / ".agentic").mkdir(mode=0o700)
    argv = json.dumps(list(config.commands["unit"].argv))
    (root / ".agentic" / "config.toml").write_text(f"[commands.unit]\nargv = {argv}\n")
    code = main(
        [
            "repair",
            INSTRUCTION,
            "--command-id",
            "unit",
            "--edit-path",
            "app.py",
            "--max-attempts",
            "2",
            "--trusted-host",
            "--root",
            str(root),
        ]
    )
    envelope = json.loads(capsys.readouterr().out)
    assert code == 4 and envelope["error"]["code"] == "INTEGRATION_UNAVAILABLE"
    with Workbench(root) as wb:
        assert not wb.store.export()["tasks"]
    assert runs(tmp_path) == 0
