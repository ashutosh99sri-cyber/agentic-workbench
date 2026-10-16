"""Pinned historical repairs with separate plumbing controls and hidden grading."""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import statistics
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .config import CommandConfig, Config, Limits, ProviderConfig
from .errors import WorkbenchError
from .eval_corpus import CorpusTask, fetch_archive, load_corpus, materialize
from .models import Grant, Usage, canonical_hash, strict_json, text_hash
from .policy import WorkspacePolicy
from .providers import BudgetLedger, IntentSink, Provider, ProviderResult, ToolExecutor
from .sdk import Workbench

PYTHON_IMAGE = "python@sha256:e88e9763f943ec1834f992a4b51e0f24500486803e8bc534e5767af9ea65f6ce"
MODES = ("no-patch-control", "known-patch-replay", "provider")
_MARKER = "AGENTIC_EVALUATION_RESULT="
ProviderFactory = Callable[[WorkspacePolicy], Provider]


@dataclass(frozen=True)
class LiveConfig:
    """Explicit host prices are estimates, not a provider billing guarantee."""

    model: str
    input_price_per_million_usd: float
    output_price_per_million_usd: float
    price_source: str
    maximum_cost_usd: float = 5.0
    maximum_tokens: int = 1_000_000
    max_output_tokens: int = 8_000
    context_bytes: int = 32_000

    def __post_init__(self) -> None:
        from .routing import ModelSpec, RoutingLimits

        ProviderConfig(name="openai", model=self.model)
        ModelSpec(
            "evaluation",
            input_price_per_million_usd=self.input_price_per_million_usd,
            output_price_per_million_usd=self.output_price_per_million_usd,
        )
        RoutingLimits(self.maximum_tokens, self.maximum_cost_usd)
        Limits(context_bytes=self.context_bytes, max_output_tokens=self.max_output_tokens)
        if (
            not isinstance(self.price_source, str)
            or not self.price_source.startswith("https://")
            or len(self.price_source) > 2_000
        ):
            raise WorkbenchError("CONFIG_ERROR", "Live evaluation requires price provenance")
        if not 0 < self.maximum_cost_usd <= 5:
            raise WorkbenchError(
                "CONFIG_ERROR", "Initial live evaluation budget must be at most USD 5"
            )

    @classmethod
    def read(cls, path: Path) -> LiveConfig:
        try:
            raw = strict_json(path.read_text(), 16_384)
            return cls(**raw)
        except (TypeError, OSError, ValueError) as error:
            raise WorkbenchError("CONFIG_ERROR", "Invalid live evaluation configuration") from error

    def provider(self, policy: WorkspacePolicy) -> Provider:
        from .providers_openai import OpenAIProvider
        from .routing import ModelRegistry, ModelSpec, RoutedProvider, RoutingLimits

        registry = ModelRegistry()
        registry.register(
            ModelSpec(
                "evaluation",
                max_input_tokens=self.context_bytes + 16_000,
                max_output_tokens=self.max_output_tokens,
                max_requests=policy.config.limits.tool_rounds + 1,
                input_price_per_million_usd=self.input_price_per_million_usd,
                output_price_per_million_usd=self.output_price_per_million_usd,
                model=self.model,
            ),
            OpenAIProvider(policy),
        )
        return RoutedProvider(
            registry,
            ("evaluation",),
            limits=RoutingLimits(self.maximum_tokens, self.maximum_cost_usd),
        )


class ReplayProvider:
    """Trusted host control. Reference content is never sent to an actual model."""

    def __init__(self, root: Path, reference: Path | None, task: CorpusTask) -> None:
        self.root, self.reference, self.task = root, reference, task
        self.fingerprint = canonical_hash(
            {
                "mode": "no-patch" if reference is None else "reference-replay",
                "task": task.id,
                "reference": task.fixed_commit if reference else None,
            }
        )

    def analyze(
        self,
        request: str,
        context: dict[str, Any],
        *,
        executor: ToolExecutor,
        budget: BudgetLedger,
        intents: IntentSink,
    ) -> ProviderResult:
        edits = (
            []
            if self.reference is None
            else [
                {
                    "path": relative,
                    "base_hash": text_hash((self.root / relative).read_text()),
                    "content": (self.reference / relative).read_text(),
                    "delete": False,
                }
                for relative in self.task.editable_paths
                if (self.root / relative).read_bytes() != (self.reference / relative).read_bytes()
            ]
        )
        return ProviderResult(
            {
                "summary": "Evaluation host control; this does not measure model intelligence.",
                "findings": [],
                "recommendations": [],
                "candidate_edits": edits,
                "limitations": ["No live model was called."],
            },
            Usage(requests=0, input_tokens=0, output_tokens=0, estimated_cost_usd=0),
        )


def command_config(task: CorpusTask, backend: str, image: str, python_executable: str) -> Config:
    # Child diagnostics cannot masquerade as the supervisor's completion receipt.
    child = (
        "import json,os,runpy,sys,traceback\nfrom pathlib import Path\n"
        "completion_fd=int(sys.argv[1])\n"
        f"sys.path.insert(0,str((Path.cwd()/{task.source_subdir!r}).resolve()))\n"
        "status='passed'\ntry:\n runpy.run_path('test_reproduction.py',run_name='__main__')\n"
        "except BaseException as error:\n traceback.print_exc()\n"
        " filename=getattr(error,'filename',None)\n"
        " virtual=not isinstance(filename,str) or "
        "(filename.startswith('<') and filename.endswith('>'))\n"
        " setup=isinstance(error,(ImportError,FileNotFoundError,SystemExit)) or "
        "(isinstance(error,SyntaxError) and not virtual)\n"
        " status='setup_failure' if setup else 'behavior_failure'\n"
        "os.write(completion_fd,json.dumps({'classification':status}).encode())\n"
        "os.close(completion_fd)\n"
        "sys.exit(0 if status=='passed' else 1)\n"
    )
    bootstrap = (
        "import json,os,subprocess,sys\n"
        "reader,writer=os.pipe()\n"
        "try:\n"
        f" child=subprocess.Popen([sys.executable,'-B','-c',{child!r},str(writer)],"
        "stdout=sys.stderr,stderr=sys.stderr,pass_fds=(writer,))\n"
        "finally:\n os.close(writer)\n"
        "data=bytearray()\n"
        "try:\n"
        " while len(data)<=1024:\n"
        "  chunk=os.read(reader,1025-len(data))\n"
        "  if not chunk: break\n"
        "  data.extend(chunk)\n"
        "finally:\n os.close(reader)\n"
        "if len(data)>1024: child.kill()\n"
        "exit_code=child.wait()\nstatus='unusable'\n"
        "try:\n"
        " record=json.loads(data)\n"
        " value=record.get('classification') if isinstance(record,dict) else None\n"
        " if len(data)<=1024 and set(record)=={'classification'} and value in "
        "{'passed','behavior_failure','setup_failure'} and "
        "exit_code==(0 if value=='passed' else 1): status=value\n"
        "except (ValueError,TypeError):\n pass\n"
        f"print({_MARKER!r}+json.dumps({{'classification':status}}))\n"
        "sys.exit(0 if status=='passed' else 1)\n"
    )
    return Config(
        commands={
            "reproduce": CommandConfig(
                (
                    ("python3" if backend == "docker" else python_executable),
                    "-B",
                    "-c",
                    f"exec({bootstrap!r})",
                ),
                image=image if backend == "docker" else None,
            )
        }
    )


def _copy(source: Path, destination: Path) -> None:
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns(".agentic", ".git", "__pycache__", ".venv"),
    )


def check_source(
    source: Path,
    task: CorpusTask,
    check: Path,
    destination: Path,
    *,
    backend: str = "docker",
    image: str = PYTHON_IMAGE,
    python_executable: str = sys.executable,
) -> dict[str, Any]:
    """Copy into a separate owned grading root; no holdout enters the repair root."""
    _copy(source, destination)
    target = destination / "test_reproduction.py"
    if target.exists():
        target.unlink()  # Only the evaluator's visible reproduction copy is replaced.
    target.write_bytes(check.read_bytes())
    config = command_config(task, backend, image, python_executable)
    with Workbench(
        destination,
        config=config,
        grants=Grant(execute=True, trusted_host=backend == "trusted-host"),
    ) as wb:
        review = wb.test_review("reproduce", backend=backend)
        receipt = wb.test("reproduce", approval=review["digest"], backend=backend, dry_run=False)
    classification = "unusable"
    if not receipt["timed_out"] and not receipt["output_limited"]:
        markers = [
            line.removeprefix(_MARKER)
            for line in receipt["stdout"].splitlines()
            if line.startswith(_MARKER)
        ]
        if len(markers) == 1:
            try:
                value = json.loads(markers[0])["classification"]
                if value in {"passed", "behavior_failure", "setup_failure"} and (
                    receipt["exit_code"] == 0
                ) == (value == "passed"):
                    classification = value
            except (ValueError, KeyError, TypeError):
                pass
    return {**receipt, "classification": classification, "approval_authority": "evaluation-host"}


def drive_repair(
    root: Path,
    task: CorpusTask,
    config: Config,
    *,
    mode: str,
    backend: str,
    max_attempts: int,
    reference: Path | None = None,
    provider_factory: ProviderFactory | None = None,
) -> dict[str, Any]:
    """Reopen after each exact review boundary; approval strings are never persisted authority."""
    grants = Grant(network=True, write=True, execute=True, trusted_host=backend == "trusted-host")
    policy = WorkspacePolicy(root, config, grants=grants)
    provider = (
        provider_factory(policy)
        if provider_factory
        else ReplayProvider(root, reference if mode == "known-patch-replay" else None, task)
    )
    result: dict[str, Any] = {}
    approvals: list[dict[str, Any]] = []
    seen: set[str] = set()
    next_approvals: dict[str, str] = {}
    task_id: str | None = None
    trace: dict[str, Any] = {}
    usage: list[dict[str, Any]] = []
    missing_usage = False
    error: dict[str, str] | None = None
    reopens = 0
    for boundary in range(3 + max_attempts * 3):
        with Workbench(root, config=config, grants=grants, provider=provider) as wb:
            try:
                result = wb.repair(
                    "Repair this Python defect using only the allowed source files: "
                    + task.summary,
                    command_id="reproduce",
                    edit_paths=list(task.editable_paths),
                    backend=backend,
                    max_attempts=max_attempts,
                    task_id=task_id,
                    **next_approvals,
                )
                task_id = result["task_id"]
            except WorkbenchError as failure:
                error = {"code": failure.code, "message": str(failure)}
            if task_id:
                trace = wb.trace(task_id)
                if hasattr(wb, "store"):
                    export = wb.store.export()
                    usage = [
                        row["result"]["usage"]
                        for row in export["tasks"]
                        if row["root_id"] == task_id
                        and row.get("result")
                        and row["result"].get("usage")
                    ]
                    missing_usage = any(
                        row["root_id"] == task_id
                        and row["id"] != task_id
                        and not (row.get("result") or {}).get("usage")
                        for row in export["tasks"]
                    )
            if error or result.get("state") != "awaiting_approval":
                break
            next_approvals = {}
            for key, argument in (
                ("baseline", "baseline_approval"),
                ("change", "approval"),
                ("test", "test_approval"),
            ):
                review = result.get("reviews", {}).get(key)
                if isinstance(review, dict) and isinstance(review.get("digest"), str):
                    digest = review["digest"]
                    if digest not in seen:
                        next_approvals[argument] = digest
                        approvals.append(
                            {
                                "kind": key,
                                "digest": digest,
                                "authority": "evaluation-host",
                                "boundary": boundary,
                            }
                        )
                        seen.add(digest)
            if not next_approvals:
                error = {
                    "code": "EVALUATION_STALLED",
                    "message": "No fresh concrete approval boundary",
                }
                break
        reopens += 1
    else:
        error = {"code": "EVALUATION_STALLED", "message": "Approval boundary limit exceeded"}
    if mode != "provider":
        metrics: dict[str, Any] = {
            "requests": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "estimated_cost_usd": 0,
            "unknown_receipts": 0,
        }
    else:
        metrics = {
            key: _sum_known(usage, key) if usage else None
            for key in (
                "requests",
                "input_tokens",
                "output_tokens",
                "estimated_cost_usd",
                "unknown_receipts",
            )
        }
        failure_code = (error or result.get("error") or {}).get("code")
        if missing_usage or failure_code in {"OUTCOME_UNKNOWN", "INTERRUPTED"}:
            metrics = dict.fromkeys(metrics)
    return {
        "result": result,
        "error": error,
        "trace": trace,
        "approvals": approvals,
        "reopens": reopens,
        "usage": metrics,
    }


def _sum_known(rows: list[dict[str, Any]], key: str) -> int | float | None:
    total: int | float = 0
    for row in rows:
        value = row.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        total += value
    return total


def _hashes(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file() and path.relative_to(root).parts[0] != ".agentic"
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    scores = {}
    for mode in sorted({row["mode"] for row in rows}):
        selected = [row for row in rows if row["mode"] == mode]
        verified = [row for row in selected if row["verified"]]
        latencies = sorted(row["latency_seconds"] for row in selected)
        usage = {
            key: _sum_known([row["usage"] for row in selected], key)
            for key in ("requests", "input_tokens", "output_tokens", "estimated_cost_usd")
        }
        scores[mode] = {
            "selected": len(selected),
            "qualified": sum(bool(row["qualified"]) for row in selected),
            "verified": len(verified),
            "within_budget_verified": len(verified),
            "attempted": sum(row["attempts"] > 0 for row in selected),
            "first_attempt_verified": sum(row["attempts"] == 1 for row in verified),
            "success_rate_selected": len(verified) / len(selected),
            "blocked": sum(not row["qualified"] for row in selected),
            "failed_qualified": sum(row["qualified"] and not row["verified"] for row in selected),
            "reopened_trials": sum(
                row.get("execution", {}).get("reopens", 0) > 0 for row in selected
            ),
            "approval_reopens": sum(row.get("execution", {}).get("reopens", 0) for row in selected),
            "median_latency_seconds": statistics.median(latencies),
            "p95_latency_seconds": latencies[math.ceil(len(latencies) * 0.95) - 1],
            "usage": usage,
            "estimated_cost_per_verified_usd": usage["estimated_cost_usd"] / len(verified)
            if verified and usage["estimated_cost_usd"] is not None
            else None,
        }
    return scores


def evaluate_corpus(
    manifest: Path,
    cache: Path,
    output: Path,
    *,
    mode: str = "no-patch-control",
    task_ids: list[str] | None = None,
    trials: int = 1,
    max_attempts: int = 2,
    backend: str = "docker",
    image: str = PYTHON_IMAGE,
    python_executable: str = sys.executable,
    download: bool = False,
    live: LiveConfig | None = None,
    provider_factory: ProviderFactory | None = None,
) -> dict[str, Any]:
    """Run every selected trial, retaining setup failures in the selection denominator."""
    if (
        mode not in MODES
        or backend not in {"docker", "trusted-host"}
        or type(trials) is not int
        or not 1 <= trials <= 10
        or type(max_attempts) is not int
        or not 1 <= max_attempts <= 4
    ):
        raise WorkbenchError("CONFIG_ERROR", "Invalid bounded evaluation options")
    if mode == "provider" and live is None and provider_factory is None:
        raise WorkbenchError(
            "CONFIG_ERROR",
            "Provider mode requires explicit live configuration or trusted host adapter",
        )
    if (mode != "provider" and (live is not None or provider_factory is not None)) or (
        live is not None and provider_factory is not None
    ):
        raise WorkbenchError("CONFIG_ERROR", "Conflicting evaluation provider mode/configuration")
    corpus = load_corpus(manifest)
    ids = task_ids if task_ids is not None else [task.id for task in corpus.tasks]
    if not ids or len(set(ids)) != len(ids) or set(ids) - {task.id for task in corpus.tasks}:
        raise WorkbenchError("CORPUS_INVALID", "Selection contains unknown or duplicate task IDs")
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    rows: list[dict[str, Any]] = []
    remaining = live.maximum_cost_usd if live else None
    stop_live = False
    report: dict[str, Any] = {
        "schema_version": 1,
        "mode": mode,
        "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "archives_lock_sha256": hashlib.sha256(
            (manifest.parent / "archives.lock.json").read_bytes()
        ).hexdigest(),
        "backend": backend,
        "image": image if backend == "docker" else None,
        "approval_mode": "evaluation-host in owned disposable roots",
        "human_review_seconds": None,
        "live_config": asdict(live) if live else None,
        "provider_origin": "configured-openai"
        if live
        else "trusted-host-adapter"
        if provider_factory
        else mode,
        "rows": rows,
    }
    for task in corpus.tasks:
        if task.id not in ids:
            continue
        for trial in range(1, trials + 1):
            started = time.monotonic()
            directory = output / f"{task.id}-{trial}"
            directory.mkdir()
            row: dict[str, Any] = {
                "task_id": task.id,
                "repo": task.repo,
                "buggy_commit": task.buggy_commit,
                "fixed_commit": task.fixed_commit,
                "public_sha256": hashlib.sha256(task.reproduction_file.read_bytes()).hexdigest(),
                "holdout_sha256": hashlib.sha256(task.holdout_file.read_bytes()).hexdigest(),
                "trial": trial,
                "mode": mode,
                "qualified": False,
                "verified": False,
                "attempts": 0,
                "usage": {
                    key: 0
                    for key in ("requests", "input_tokens", "output_tokens", "estimated_cost_usd")
                },
            }
            live_dispatch_possible = False
            try:
                if stop_live:
                    raise WorkbenchError(
                        "LIMIT_EXCEEDED",
                        "Previous live result has unknown usage/outcome or exhausted budget",
                    )
                buggy = materialize(
                    fetch_archive(
                        corpus.archives[(task.repo, task.buggy_commit)], cache, download=download
                    ),
                    directory / "buggy",
                )
                fixed = materialize(
                    fetch_archive(
                        corpus.archives[(task.repo, task.fixed_commit)], cache, download=download
                    ),
                    directory / "reference",
                )
                checks: dict[str, Any] = {}
                row["qualification"] = checks
                for label, source, check in (
                    ("buggy_public", buggy, task.reproduction_file),
                    ("buggy_holdout", buggy, task.holdout_file),
                    ("fixed_public", fixed, task.reproduction_file),
                    ("fixed_holdout", fixed, task.holdout_file),
                ):
                    checks[label] = check_source(
                        source,
                        task,
                        check,
                        directory / label,
                        backend=backend,
                        image=image,
                        python_executable=python_executable,
                    )
                row["qualification"] = checks
                row["qualified"] = all(
                    checks[label]["classification"]
                    == ("behavior_failure" if label.startswith("buggy") else "passed")
                    for label in checks
                )
                if not row["qualified"]:
                    raise WorkbenchError(
                        "CORPUS_UNQUALIFIED",
                        "Buggy/fixed checks did not establish the expected behavior",
                    )
                workspace = directory / "workspace"
                _copy(buggy, workspace)
                if (workspace / "test_reproduction.py").exists():
                    raise WorkbenchError(
                        "CORPUS_INVALID", "Upstream source collides with reproduction path"
                    )
                (workspace / "test_reproduction.py").write_bytes(
                    task.reproduction_file.read_bytes()
                )
                before = _hashes(workspace)
                config = command_config(task, backend, image, python_executable)
                factory = provider_factory
                if live is not None:
                    if not os.environ.get("OPENAI_API_KEY"):
                        raise WorkbenchError(
                            "INTEGRATION_UNAVAILABLE",
                            "OPENAI_API_KEY is unavailable; no live request made",
                        )
                    assert remaining is not None
                    trial_live = LiveConfig(**{**asdict(live), "maximum_cost_usd": remaining})
                    config = Config(
                        commands=config.commands,
                        provider=ProviderConfig(name="openai", model=live.model),
                        limits=Limits(
                            provider_requests=max_attempts * (config.limits.tool_rounds + 1),
                            context_bytes=live.context_bytes,
                            max_output_tokens=live.max_output_tokens,
                        ),
                    )
                    factory = trial_live.provider
                live_dispatch_possible = live is not None
                if mode == "provider":
                    row["usage"] = dict.fromkeys(row["usage"])
                execution = drive_repair(
                    workspace,
                    task,
                    config,
                    mode=mode,
                    backend=backend,
                    max_attempts=max_attempts,
                    reference=fixed,
                    provider_factory=factory,
                )
                row["execution"] = execution
                row["usage"] = execution["usage"]
                row["attempts"] = len(execution["result"].get("attempts", []))
                after = _hashes(workspace)
                changed = {
                    path
                    for path in before.keys() | after.keys()
                    if before.get(path) != after.get(path)
                }
                row["changed_paths"] = sorted(changed)
                row["source_only"] = (
                    bool(changed)
                    and changed <= set(task.editable_paths)
                    and before.keys() == after.keys()
                )
                row["public_grade"] = check_source(
                    workspace,
                    task,
                    task.reproduction_file,
                    directory / "final_public",
                    backend=backend,
                    image=image,
                    python_executable=python_executable,
                )
                row["holdout_grade"] = check_source(
                    workspace,
                    task,
                    task.holdout_file,
                    directory / "final_holdout",
                    backend=backend,
                    image=image,
                    python_executable=python_executable,
                )
                row["verified"] = bool(
                    row["source_only"]
                    and execution["error"] is None
                    and execution["result"].get("outcome") == "repaired"
                    and row["public_grade"]["classification"]
                    == row["holdout_grade"]["classification"]
                    == "passed"
                )
                if live is not None:
                    resources = execution["trace"].get("resources")
                    if (
                        not resources
                        or resources.get("state") != "known"
                        or not resources.get("cost_known")
                        or row["usage"].get("estimated_cost_usd") is None
                    ):
                        stop_live = True
                    else:
                        remaining = max(0.0, remaining - resources["cost_microusd"] / 1_000_000)
                        stop_live = remaining <= 0
            except (WorkbenchError, OSError, UnicodeError) as failure:
                row["error"] = {
                    "code": failure.code
                    if isinstance(failure, WorkbenchError)
                    else "EVALUATION_SETUP_ERROR",
                    "message": str(failure),
                }
                if live_dispatch_possible:
                    stop_live = True
            row["latency_seconds"] = time.monotonic() - started
            rows.append(row)
            (directory / "result.json").write_text(json.dumps(row, indent=2) + "\n")
            report["scorecards"] = summarize(rows)
            (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report
