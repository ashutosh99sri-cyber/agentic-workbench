"""Evaluate offline harness control flow on disposable, exactly approved repair fixtures.

These are deterministic host callbacks, not an evaluation of live model intelligence.
The only source writes and trusted-host commands occur inside temporary fixture directories.
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from agentic_workbench.changes import ChangeWorkflow
from agentic_workbench.config import CommandConfig, Config
from agentic_workbench.errors import WorkbenchError
from agentic_workbench.execution import (
    ExecutionContext,
    ExecutionLimits,
    Harness,
    Observation,
    Plan,
    PlanRequest,
    Step,
    Verification,
    VerificationRequest,
)
from agentic_workbench.models import Grant, text_hash
from agentic_workbench.policy import WorkspacePolicy
from agentic_workbench.runner import Runner
from agentic_workbench.state import StateStore


def _case(root: Path, name: str, *, broken: bool, repair: bool) -> dict[str, Any]:
    before = f"value = {1 if broken else 2}\n"
    (root / "app.py").write_text(before)
    config = Config(
        commands={
            "unit": CommandConfig((sys.executable, "-B", "-c", "import app; assert app.value == 2"))
        }
    )
    policy = WorkspacePolicy(
        root, config, grants=Grant(write=True, execute=True, trusted_host=True)
    )
    approvals: dict[str, str] = {}
    repairs = 0

    def planner(request: PlanRequest) -> Plan:
        steps = [Step("inspect", "inspect")]
        if repair and request.replan:
            steps.append(
                Step("repair", "apply", {"proposal_id": proposal_id}, ("inspect",), "write")
            )
        return Plan(tuple(steps))

    def executor(step: Step, context: ExecutionContext) -> Observation:
        nonlocal repairs
        if step.action == "apply":
            result = changes.apply(step.arguments["proposal_id"], approval=approvals.get("apply"))
            repairs += 1
            return Observation(True, result)
        source = policy.read_source("app.py")
        return Observation(True, {"path": source.path, "source_hash": source.source_hash})

    def verifier(request: VerificationRequest) -> Verification:
        # The evaluation host approves only this declared command in its own disposable fixture.
        approval = runner.review("unit", "trusted-host")["digest"]
        result = runner.execute("unit", approval, "trusted-host")
        return Verification(
            result["exit_code"] == 0 and not result["timed_out"] and not result["output_limited"],
            result,
        )

    def create_harness(store: StateStore) -> Harness:
        return Harness(
            store,
            planner=planner,
            executor=executor,
            verifier=verifier,
            pins={"callbacks": "offline-repair-v1", "case": name},
            limits=ExecutionLimits(max_replans=1 if repair else 0),
        )

    started = time.perf_counter()
    recovered = False
    error_code = None
    with StateStore(policy) as store:
        changes, runner = ChangeWorkflow(policy, store), Runner(policy, store)
        proposal = changes.propose(
            [
                {
                    "path": "app.py",
                    "base_hash": text_hash(before),
                    "content": "value = 2\n",
                    "delete": False,
                }
            ],
            rationale="Repair the declared offline fixture",
        )
        proposal_id = proposal["proposal_id"]
        harness = create_harness(store)
        try:
            outcome = harness.execute("verify value and repair when required")
        except WorkbenchError as error:
            error_code = error.code
            task_id = store.export()["tasks"][0]["id"]
            outcome = harness.status(task_id)
    if outcome["state"] == "awaiting_approval" and repair:
        approvals["apply"] = proposal["digest"]
        with StateStore(policy) as store:
            changes, runner = ChangeWorkflow(policy, store), Runner(policy, store)
            harness = create_harness(store)
            outcome = harness.resume(outcome["task_id"])
            recovered = outcome["state"] == "succeeded"
    return {
        "id": name,
        "state": outcome["state"],
        "solved": outcome["state"] == "succeeded",
        "recovered": recovered,
        "error_code": error_code,
        "steps": outcome["steps"],
        "replans": outcome["replans"],
        "source_mutations": repairs,
        "verification_exit_code": (outcome.get("verification") or {})
        .get("evidence", {})
        .get("exit_code"),
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        "model_requests": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "estimated_cost_usd": 0,
    }


def run() -> dict[str, Any]:
    cases = (
        ("already-correct", False, False),
        ("repair-resume", True, True),
        ("unrepaired", True, False),
    )
    rows = []
    for name, broken, repair in cases:
        with tempfile.TemporaryDirectory(prefix="agentic-harness-evaluation-") as directory:
            rows.append(_case(Path(directory), name, broken=broken, repair=repair))
    assert [row["solved"] for row in rows] == [True, True, False]
    assert rows[1]["recovered"] and rows[1]["source_mutations"] == 1
    assert rows[2]["error_code"] == "REPLAN_EXHAUSTED"
    return {
        "schema_version": 1,
        "mode": "offline-host-fixtures",
        "live_model_quality_evaluated": False,
        "tasks": rows,
        "summary": {
            "total": len(rows),
            "solved": sum(row["solved"] for row in rows),
            "failed": sum(not row["solved"] for row in rows),
            "recovered": sum(row["recovered"] for row in rows),
            "model_requests": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "estimated_cost_usd": 0,
            "elapsed_ms": round(sum(row["elapsed_ms"] for row in rows), 3),
        },
    }


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, sort_keys=True))
