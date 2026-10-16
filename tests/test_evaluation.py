"""Evaluation success needs independent behavior checks, not provider claims."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import zipfile
from pathlib import Path

import pytest

from agentic_workbench.errors import WorkbenchError
from agentic_workbench.eval_corpus import CorpusTask
from agentic_workbench.evaluation import (
    ReplayProvider,
    check_source,
    drive_repair,
    summarize,
)

requires_posix = pytest.mark.skipif(os.name != "posix", reason="Runner execution requires POSIX")


def task(tmp_path: Path) -> CorpusTask:
    public, hidden = tmp_path / "public.py", tmp_path / "hidden.py"
    public.write_text("from sample import value\nassert value(0) == 1\n")
    hidden.write_text("from sample import value\nassert value(2) == 3\n")
    return CorpusTask(
        "sample",
        "https://github.com/example/sample",
        "a" * 40,
        "b" * 40,
        "value is one too small",
        "MIT",
        ("sample.py",),
        ".",
        public,
        hidden,
    )


@requires_posix
def test_hidden_grader_rejects_public_only_patch(tmp_path: Path) -> None:
    case = task(tmp_path)
    source = tmp_path / "project"
    source.mkdir()
    (source / "sample.py").write_text("def value(x):\n    return 1 if x == 0 else x\n")
    public = check_source(
        source,
        case,
        case.reproduction_file,
        tmp_path / "public-grade",
        backend="trusted-host",
        python_executable=sys.executable,
    )
    hidden = check_source(
        source,
        case,
        case.holdout_file,
        tmp_path / "hidden-grade",
        backend="trusted-host",
        python_executable=sys.executable,
    )
    assert public["classification"] == "passed"
    assert hidden["classification"] == "behavior_failure"
    assert not (source / "test_reproduction.py").exists()
    assert not (tmp_path / "public-grade" / "hidden.py").exists()


@requires_posix
def test_missing_dependency_is_setup_failure(tmp_path: Path) -> None:
    case = task(tmp_path)
    source = tmp_path / "project"
    source.mkdir()
    (source / "sample.py").write_text("import missing_eval_dependency_42\n")
    result = check_source(
        source,
        case,
        case.reproduction_file,
        tmp_path / "grade",
        backend="trusted-host",
        python_executable=sys.executable,
    )
    assert result["exit_code"] != 0
    assert result["classification"] == "setup_failure"


@requires_posix
@pytest.mark.parametrize(
    ("source_text", "expected"),
    [
        ("def value(:\n    return 1\n", "setup_failure"),
        (
            'import ast\ndef value(x):\n    return ast.literal_eval("\'unterminated")\n',
            "behavior_failure",
        ),
    ],
)
def test_file_syntax_error_and_dynamic_input_syntax_error_are_distinct(
    tmp_path: Path,
    source_text: str,
    expected: str,
) -> None:
    case = task(tmp_path)
    source = tmp_path / "project"
    source.mkdir()
    (source / "sample.py").write_text(source_text)
    result = check_source(
        source,
        case,
        case.reproduction_file,
        tmp_path / "grade",
        backend="trusted-host",
        python_executable=sys.executable,
    )
    assert result["classification"] == expected


@requires_posix
def test_candidate_cannot_print_a_pass_receipt_and_exit_before_checks(tmp_path: Path) -> None:
    case = task(tmp_path)
    source = tmp_path / "project"
    source.mkdir()
    (source / "sample.py").write_text(
        "import os\n"
        'print(\'AGENTIC_EVALUATION_RESULT={"classification": "passed"}\', flush=True)\n'
        "os._exit(0)\n"
    )
    result = check_source(
        source,
        case,
        case.holdout_file,
        tmp_path / "grade",
        backend="trusted-host",
        python_executable=sys.executable,
    )
    assert result["classification"] == "unusable"
    assert result["exit_code"] != 0


@requires_posix
@pytest.mark.parametrize("payload", [b"invalid", b'{"classification":"passed"} ' * 50])
def test_invalid_completion_pipe_record_is_unusable(tmp_path: Path, payload: bytes) -> None:
    case = task(tmp_path)
    source = tmp_path / "project"
    source.mkdir()
    (source / "sample.py").write_text(
        "import os\n"
        "original_write = os.write\n"
        f"os.write = lambda fd, data: original_write(fd, {payload!r})\n"
        "def value(x):\n    return x + 1\n"
    )
    result = check_source(
        source,
        case,
        case.holdout_file,
        tmp_path / "grade",
        backend="trusted-host",
        python_executable=sys.executable,
    )
    assert result["classification"] == "unusable"


def test_no_patch_provider_cannot_claim_success(tmp_path: Path) -> None:
    case = task(tmp_path)
    source = tmp_path / "project"
    source.mkdir()
    (source / "sample.py").write_text("def value(x):\n    return x\n")
    response = ReplayProvider(source, None, case).analyze(
        "repair", {}, executor=None, budget=None, intents=None
    )  # type: ignore[arg-type]
    assert response.analysis["candidate_edits"] == []
    assert response.usage.requests == 0
    assert response.usage.estimated_cost_usd == 0


def test_summary_keeps_failed_selection_and_unknown_metrics() -> None:
    rows = [
        {
            "mode": "provider",
            "qualified": True,
            "verified": True,
            "attempts": 1,
            "latency_seconds": 2,
            "usage": {
                "requests": 1,
                "input_tokens": 10,
                "output_tokens": 2,
                "estimated_cost_usd": 0.1,
            },
        },
        {
            "mode": "provider",
            "qualified": False,
            "verified": False,
            "attempts": 0,
            "latency_seconds": 4,
            "usage": {
                "requests": None,
                "input_tokens": None,
                "output_tokens": None,
                "estimated_cost_usd": None,
            },
        },
        {
            "mode": "known-patch-replay",
            "qualified": True,
            "verified": True,
            "attempts": 1,
            "latency_seconds": 1,
            "usage": {
                "requests": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "estimated_cost_usd": 0,
            },
        },
    ]
    scores = summarize(rows)
    assert scores["provider"]["selected"] == 2
    assert scores["provider"]["verified"] == 1
    assert scores["provider"]["success_rate_selected"] == 0.5
    assert scores["provider"]["usage"]["estimated_cost_usd"] is None
    assert scores["known-patch-replay"]["usage"]["estimated_cost_usd"] == 0


def test_driver_reopens_and_never_carries_old_approvals(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import agentic_workbench.evaluation as evaluation

    calls: list[dict[str, object]] = []
    opened: list[Path] = []

    class Fake:
        def __init__(self, root: Path, **kwargs: object) -> None:
            opened.append(root)

        def __enter__(self) -> Fake:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def repair(self, instruction: str, **kwargs: object) -> dict[str, object]:
            calls.append(kwargs)
            if len(calls) == 1:
                return {
                    "task_id": "task",
                    "state": "awaiting_approval",
                    "reviews": {"baseline": {"digest": "b"}},
                    "attempts": [],
                }
            if len(calls) == 2:
                return {
                    "task_id": "task",
                    "state": "awaiting_approval",
                    "reviews": {"change": {"digest": "c"}},
                    "attempts": [],
                }
            return {
                "task_id": "task",
                "state": "succeeded",
                "outcome": "repaired",
                "reviews": {},
                "attempts": [],
            }

        def trace(self, identifier: str) -> dict[str, object]:
            return {}

    monkeypatch.setattr(evaluation, "Workbench", Fake)
    result = drive_repair(
        tmp_path,
        task(tmp_path),
        evaluation.command_config(
            task(tmp_path), "trusted-host", evaluation.PYTHON_IMAGE, sys.executable
        ),
        mode="no-patch-control",
        backend="trusted-host",
        max_attempts=2,
    )
    assert result["result"]["outcome"] == "repaired"
    assert len(opened) == 3
    assert calls[1]["baseline_approval"] == "b"
    assert calls[2].get("baseline_approval") is None
    assert calls[2]["approval"] == "c"
    assert result["reopens"] == 2
    assert all(row["authority"] == "evaluation-host" for row in result["approvals"])


def test_live_config_requires_prices_and_provenance(tmp_path: Path) -> None:
    from agentic_workbench.evaluation import LiveConfig

    path = tmp_path / "live.json"
    path.write_text(json.dumps({"model": "configured-model", "maximum_cost_usd": 5}))
    with pytest.raises(WorkbenchError, match="CONFIG_ERROR"):
        LiveConfig.read(path)


def make_corpus(tmp_path: Path, count: int = 1) -> tuple[Path, Path]:
    case = task(tmp_path)
    cache = tmp_path / "cache"
    cache.mkdir()
    tasks, archives = [], []
    for number in range(count):
        buggy, fixed = f"{number * 2 + 1:040x}", f"{number * 2 + 2:040x}"
        tasks.append(
            {
                "id": f"case-{number}",
                "repo": case.repo,
                "buggy_commit": buggy,
                "fixed_commit": fixed,
                "summary": case.summary,
                "license": "MIT",
                "editable_paths": ["sample.py"],
                "source_subdir": ".",
                "reproduction_file": "public.py",
                "holdout_file": "hidden.py",
            }
        )
        for commit, expression in ((buggy, "x"), (fixed, "x + 1")):
            archive = tmp_path / f"{commit}.zip"
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr(
                    "sample-project/sample.py", f"def value(x):\n    return {expression}\n"
                )
            data = archive.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            (cache / f"{digest}.zip").write_bytes(data)
            archives.append(
                {
                    "repo": case.repo,
                    "commit": commit,
                    "url": f"https://codeload.github.com/example/sample/zip/{commit}",
                    "sha256": digest,
                    "bytes": len(data),
                }
            )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"schema_version": 1, "tasks": tasks}))
    (tmp_path / "archives.lock.json").write_text(
        json.dumps({"schema_version": 1, "archives": archives})
    )
    return manifest, cache


@pytest.mark.parametrize("candidate", ["public-only", "no-op", "test-tampering"])
@requires_posix
def test_full_grading_rejects_wrong_noop_and_test_tampering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    candidate: str,
) -> None:
    import agentic_workbench.evaluation as evaluation

    manifest, cache = make_corpus(tmp_path)

    def fake_drive(root: Path, *args: object, **kwargs: object) -> dict[str, object]:
        if candidate == "public-only":
            (root / "sample.py").write_text("def value(x):\n    return 1 if x == 0 else x\n")
        elif candidate == "test-tampering":
            (root / "sample.py").write_text("def value(x):\n    return x + 1\n")
            (root / "test_reproduction.py").write_text("assert True\n")
        return {
            "result": {"outcome": "repaired", "attempts": [{}]},
            "error": None,
            "usage": {
                "requests": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "estimated_cost_usd": 0,
            },
        }

    monkeypatch.setattr(evaluation, "drive_repair", fake_drive)
    report = evaluation.evaluate_corpus(
        manifest, cache, tmp_path / "output", mode="known-patch-replay", backend="trusted-host"
    )
    row = report["rows"][0]
    assert row["qualified"]
    assert not row["verified"]
    assert report["scorecards"]["known-patch-replay"]["selected"] == 1
    if candidate == "public-only":
        assert row["public_grade"]["classification"] == "passed"
        assert row["holdout_grade"]["classification"] == "behavior_failure"
    if candidate == "test-tampering":
        assert not row["source_only"]


@pytest.mark.parametrize("mode", ["no-patch-control", "known-patch-replay"])
def test_control_mode_cannot_run_or_mislabel_live_provider(tmp_path: Path, mode: str) -> None:
    from agentic_workbench.evaluation import LiveConfig, evaluate_corpus

    live = LiveConfig("model", 1, 1, "https://provider.example/pricing")
    with pytest.raises(WorkbenchError, match="CONFIG_ERROR"):
        evaluate_corpus(
            tmp_path / "unused",
            tmp_path / "unused-cache",
            tmp_path / "unused-output",
            mode=mode,
            live=live,
        )
    with pytest.raises(WorkbenchError, match="CONFIG_ERROR"):
        evaluate_corpus(
            tmp_path / "unused",
            tmp_path / "unused-cache",
            tmp_path / "unused-output",
            mode=mode,
            provider_factory=lambda _: None,
        )  # type: ignore[arg-type]
    assert not (tmp_path / "unused-output").exists()


def test_known_setup_failure_does_not_stop_unspent_live_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agentic_workbench.evaluation as evaluation

    manifest, cache = make_corpus(tmp_path, 2)
    live = evaluation.LiveConfig("model", 1, 1, "https://provider.example/pricing")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-never-used")
    dispatched = []

    def check(
        source: Path, case: CorpusTask, script: Path, destination: Path, **kwargs: object
    ) -> dict[str, object]:
        status = (
            "setup_failure"
            if case.id == "case-0"
            else "behavior_failure"
            if destination.name.startswith("buggy")
            else "passed"
        )
        return {"classification": status, "exit_code": int(status != "passed")}

    def drive(root: Path, case: CorpusTask, *args: object, **kwargs: object) -> dict[str, object]:
        from agentic_workbench.config import Config

        config = args[0]
        assert isinstance(config, Config)
        assert config.limits.provider_requests == 2 * (config.limits.tool_rounds + 1)
        dispatched.append(case.id)
        (root / "sample.py").write_text("def value(x):\n    return x + 1\n")
        return {
            "result": {"outcome": "repaired", "attempts": [{}]},
            "error": None,
            "usage": {
                "requests": 1,
                "input_tokens": 1,
                "output_tokens": 1,
                "estimated_cost_usd": 0.001,
            },
            "trace": {"resources": {"state": "known", "cost_known": True, "cost_microusd": 1000}},
        }

    monkeypatch.setattr(evaluation, "check_source", check)
    monkeypatch.setattr(evaluation, "drive_repair", drive)
    result = evaluation.evaluate_corpus(
        manifest, cache, tmp_path / "output", mode="provider", live=live
    )
    assert dispatched == ["case-1"]
    assert result["rows"][0]["error"]["code"] == "CORPUS_UNQUALIFIED"
    assert result["rows"][1]["verified"]
    assert result["scorecards"]["provider"]["selected"] == 2


@requires_posix
def test_replay_uses_actual_repair_api_and_reopens(tmp_path: Path) -> None:
    from agentic_workbench.evaluation import evaluate_corpus

    manifest, cache = make_corpus(tmp_path)
    result = evaluate_corpus(
        manifest,
        cache,
        tmp_path / "output",
        mode="known-patch-replay",
        backend="trusted-host",
    )
    row = result["rows"][0]
    assert row["qualified"]
    assert row["verified"], row
    assert row["attempts"] == 1
    assert row["execution"]["reopens"] == 3
    assert [item["kind"] for item in row["execution"]["approvals"]] == [
        "baseline",
        "change",
        "test",
    ]
    assert row["usage"]["requests"] == 0


def test_live_candidate_allows_bounded_multi_http_tool_use(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agentic_workbench.agents import Budget, Intents
    from agentic_workbench.config import Config, Limits, ProviderConfig
    from agentic_workbench.evaluation import LiveConfig
    from agentic_workbench.models import Usage
    from agentic_workbench.policy import WorkspacePolicy
    from agentic_workbench.providers import ProviderResult
    from agentic_workbench.routing import RoutedProvider
    from agentic_workbench.state import StateStore

    live = LiveConfig("model", 1, 1, "https://provider.example/pricing")
    limits = Limits(
        provider_requests=14,
        context_bytes=live.context_bytes,
        max_output_tokens=live.max_output_tokens,
    )
    policy = WorkspacePolicy(
        tmp_path, Config(provider=ProviderConfig(name="openai", model=live.model), limits=limits)
    )
    reserved = []

    class Adapter:
        def __init__(self, policy: WorkspacePolicy) -> None:
            self.policy = policy

        def analyze(
            self,
            request: str,
            context: dict[str, object],
            *,
            executor: object,
            budget: object,
            intents: object,
        ) -> ProviderResult:
            reserved.append(store.resource_usage(task_id)["tokens"])
            for _ in range(2):
                budget.reserve(limits.provider_requests)
                request_id = intents.intent("fixture.http", {"model": "model"})
                intents.receipt(
                    request_id, {"status": "received", "input_tokens": 10, "output_tokens": 5}
                )
            return ProviderResult(
                {
                    "summary": "Local fake tool-use candidate",
                    "findings": [],
                    "recommendations": [],
                    "candidate_edits": [],
                    "limitations": [],
                },
                Usage(requests=2, input_tokens=20, output_tokens=10),
            )

    monkeypatch.setattr("agentic_workbench.providers_openai.OpenAIProvider", Adapter)
    router = live.provider(policy)
    assert isinstance(router, RoutedProvider)
    spec, _ = router.registry.get("evaluation")
    assert spec.max_requests == limits.tool_rounds + 1
    bound = spec.max_requests * (spec.max_input_tokens + spec.max_output_tokens)
    assert live.maximum_tokens >= 2 * bound
    with StateStore(policy) as store:
        task_id = store.create_task("engineering", "Local tool-use fixture", {})
        response = router.analyze(
            "repair",
            {},
            executor=None,
            budget=Budget(store, task_id),
            intents=Intents(store, task_id),
        )
        assert response.usage.requests == 2
        assert reserved == [bound]
        assert store.resource_usage(task_id)["tokens"] == 30
