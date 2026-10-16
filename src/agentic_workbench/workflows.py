"""Built-in verified engineering workflow; host SDK retains all authority."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .errors import WorkbenchError
from .execution import (
    ExecutionContext,
    ExecutionLimits,
    Observation,
    Plan,
    PlanRequest,
    Step,
    Verification,
    VerificationRequest,
)
from .models import Evidence, canonical_hash

if TYPE_CHECKING:
    from .sdk import Workbench


def execute(
    wb: Workbench,
    instruction: str,
    *,
    proposal_id: str | None = None,
    command_id: str | None = None,
    approval: str | None = None,
    test_approval: str | None = None,
    backend: str = "docker",
    task_id: str | None = None,
) -> dict[str, Any]:
    """Bounded engineering analysis, optional approved change and required check.

    Custom recovery/planning belongs in harness(); this default never interprets
    model success as verification or applies a candidate without host selection.
    """
    if proposal_id is not None and command_id is None:
        raise WorkbenchError("VALIDATION_ERROR", "Applied workflows require a verification command")
    if backend not in {"docker", "trusted-host"}:
        raise WorkbenchError("VALIDATION_ERROR", "Unknown execution backend")
    if command_id is not None and command_id not in wb.policy.config.commands:
        raise WorkbenchError("CONFIG_ERROR", "Verification command is not configured")
    options = {"proposal_id": proposal_id, "command_id": command_id, "backend": backend}

    def planner(request: PlanRequest) -> Plan:
        if wb.store.load("execution-options", request.task_id) is None:
            wb.store.save("execution-options", request.task_id, options)
        steps = [Step("analysis", "engineering", {"instruction": instruction}, replay_safe=True)]
        previous = "analysis"
        if proposal_id is not None:
            steps.append(Step("apply", "apply", {"proposal_id": proposal_id}, (previous,), "write"))
            previous = "apply"
        if command_id is not None:
            steps.append(
                Step("check", "check", {"command_id": command_id}, (previous,), "external")
            )
        return Plan(tuple(steps))

    def executor(step: Step, context: ExecutionContext) -> Observation:
        if step.action == "engineering":
            runtime = wb._runtime()
            result = runtime.run(
                "engineering", instruction, root_id=context.task_id, parent_id=context.task_id
            )
            return Observation(True, {"analysis": result})
        if step.action == "apply":
            assert proposal_id is not None
            reviewed = wb.review(proposal_id)
            _save_review(wb, context.task_id, "change", reviewed)
            return Observation(
                True, {"change": wb.apply(proposal_id, approval=approval, dry_run=False)}
            )
        if step.action == "check":
            assert command_id is not None
            reviewed = wb.test_review(command_id, backend=backend)
            _save_review(wb, context.task_id, "test", reviewed)
            receipt = wb.test(command_id, approval=test_approval, backend=backend, dry_run=False)
            passed = (
                receipt["exit_code"] == 0
                and not receipt["timed_out"]
                and not receipt["output_limited"]
            )
            return Observation(
                passed, {"test": receipt}, error_code=None if passed else "TEST_FAILED"
            )
        raise WorkbenchError("POLICY_DENIED", "Execution action is not supported")

    def verifier(request: VerificationRequest) -> Verification:
        if command_id is not None:
            observation = request.observations.get("check")
            if observation is None or not observation.success:
                return Verification(False, {"scope": "command", "command_id": command_id})
            receipt = observation.evidence["test"]
            # Approval binds the source snapshot; later source drift invalidates completion.
            current = wb.test_review(command_id, backend=backend)
            passed = (
                receipt["snapshot_hash"] == current["snapshot_hash"]
                and receipt["exit_code"] == 0
                and not receipt["timed_out"]
                and not receipt["output_limited"]
            )
            return Verification(
                passed, {"scope": "approved-command", "receipt": receipt}, "Actual test outcome"
            )
        analysis = request.observations["analysis"].evidence["analysis"]
        index = wb._scan()
        citations = analysis["evidence"] + [e for f in analysis["findings"] for e in f["evidence"]]
        valid = all(index.current_evidence(wb.policy, [Evidence(**e) for e in citations]))
        return Verification(
            valid,
            {
                "scope": "source-contracts",
                "source_fingerprint": index.fingerprint,
                "citations": len(citations),
            },
            "Analysis verified against current source; changes and runtime behavior are unverified",
        )

    selected_provider = wb._provider()
    pins = {
        "builtin_workflow": 1,
        "options": options,
        "provider": wb.policy.config.provider.name,
        "adapter": None
        if selected_provider is None
        else {
            "type": f"{type(selected_provider).__module__}.{type(selected_provider).__qualname__}",
            "fingerprint": getattr(selected_provider, "fingerprint", None),
        },
        "skills": [s.pin() for s in wb._registry().skills],
    }
    if task_id is None:
        # Options persist independently of approval values; approval is host authority.
        harness = wb.harness(
            planner=planner,
            executor=executor,
            verifier=verifier,
            pins=pins,
            limits=ExecutionLimits(max_replans=0),
        )
        result = harness.execute(instruction)
    else:
        harness = wb.harness(
            planner=planner,
            executor=executor,
            verifier=verifier,
            pins=pins,
            limits=ExecutionLimits(max_replans=0),
        )
        result = harness.execute(instruction, task_id=task_id)
    result["reviews"] = wb.store.load("execution-review", result["task_id"]) or {}
    return result


def _save_review(wb: Workbench, task_id: str, kind: str, review: dict[str, Any]) -> None:
    saved = wb.store.load("execution-review", task_id)
    payload = {**(saved or {}), kind: review}
    if saved == payload:
        return
    if saved is None:
        wb.store.save("execution-review", task_id, payload)
    else:
        # Reviews are immutable per digest; retain a new version rather than overwrite.
        history_id = canonical_hash({"task_id": task_id, "reviews": payload})
        if wb.store.load("execution-review-history", history_id) is None:
            wb.store.save("execution-review-history", history_id, {"task_id": task_id, **payload})
        wb.store.update("execution-review", task_id, payload)
