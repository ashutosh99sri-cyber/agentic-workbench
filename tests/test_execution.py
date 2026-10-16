import sys
from pathlib import Path

import pytest

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
    validate_plan,
)
from agentic_workbench.models import Grant, text_hash
from agentic_workbench.policy import WorkspacePolicy
from agentic_workbench.runner import Runner
from agentic_workbench.state import StateStore


@pytest.mark.parametrize(
    "plan",
    [
        Plan(()),
        Plan((Step("a", "read"), Step("a", "read"))),
        Plan((Step("a", "read", dependencies=("a",)),)),
        Plan((Step("a", "read", dependencies=("missing",)),)),
        Plan((Step("a", "read", arguments={"value": float("nan")}),)),
        Plan((Step("../a", "read"),)),
    ],
)
def test_invalid_dependency_plans_are_rejected(plan: Plan) -> None:
    with pytest.raises(WorkbenchError):
        validate_plan(plan)


def test_limits_and_dependency_plan() -> None:
    ExecutionLimits().validate()
    validate_plan(Plan((Step("a", "read"), Step("b", "verify", dependencies=("a",)))))
    with pytest.raises(WorkbenchError):
        ExecutionLimits(deadline_seconds=float("inf")).validate()


def fixed_plan(request: PlanRequest) -> Plan:
    return Plan((Step("inspect", "inspect", replay_safe=True),))


def observed(step: Step, context: ExecutionContext) -> Observation:
    return Observation(True, {"source": "host-fixture", "step": context.step_id})


def verified(request: VerificationRequest) -> Verification:
    return Verification(True, {"checked_steps": sorted(request.observations)})


def make_harness(store: StateStore, **options: object) -> Harness:
    defaults = {
        "planner": fixed_plan,
        "executor": observed,
        "verifier": verified,
        "pins": {"host_callbacks": "fixture-v1"},
    }
    return Harness(store, **(defaults | options))  # type: ignore[arg-type]


def test_verified_workflow_reopens_without_replay_and_exposes_trace(tmp_path: Path) -> None:
    policy = WorkspacePolicy(tmp_path)
    with StateStore(policy) as store:
        harness = make_harness(store)
        output = harness.execute("inspect the repository")
        assert output["state"] == "succeeded"
        assert output["verification"]["evidence"] == {"checked_steps": ["inspect"]}
        assert {entry["phase"] for entry in harness.trace(output["task_id"])} >= {
            "plan",
            "execute",
            "observe",
            "verify",
            "complete",
        }
        assert store.get_task(output["task_id"])["state"] == "succeeded"
    with StateStore(policy) as store:
        harness = make_harness(store)
        assert harness.resume(output["task_id"]) == output
        assert harness.status(output["task_id"])["steps"] == 1


def test_host_verifier_controls_completion_and_replans(tmp_path: Path) -> None:
    calls: list[str] = []

    def planner(request: PlanRequest) -> Plan:
        return Plan((Step("inspect", "inspect"),))

    def executor(step: Step, context: ExecutionContext) -> Observation:
        calls.append(step.id)
        return Observation(True, {"model_says_success": True})

    def verifier(request: VerificationRequest) -> Verification:
        return Verification(False, {"test_exit_code": 1}, "Actual tests still fail")

    with StateStore(WorkspacePolicy(tmp_path)) as store:
        harness = make_harness(store, planner=planner, executor=executor, verifier=verifier)
        with pytest.raises(WorkbenchError, match="REPLAN_EXHAUSTED"):
            harness.execute("repair")
        task_id = store.export()["tasks"][0]["id"]
        checkpoint = store.load("execution", task_id)
        assert store.get_task(task_id)["state"] == "failed"
        assert checkpoint["verification"]["success"] is False
        assert calls == ["inspect"]
        assert len(checkpoint["history"]) == 3


def test_safe_known_failures_retry_only_with_host_allowlist(tmp_path: Path) -> None:
    calls: list[int] = []

    def executor(step: Step, context: ExecutionContext) -> Observation:
        calls.append(context.attempt)
        return Observation(len(calls) > 1, {"attempt": context.attempt}, len(calls) == 1)

    with StateStore(WorkspacePolicy(tmp_path)) as store:
        harness = make_harness(store, executor=executor, replay_safe_actions=frozenset({"inspect"}))
        assert harness.execute("inspect")["state"] == "succeeded"
        assert calls == [1, 2]


def test_repeated_actions_stop_even_if_replanner_renames_steps(tmp_path: Path) -> None:
    calls: list[str] = []

    def planner(request: PlanRequest) -> Plan:
        return Plan((Step(f"try{request.replan}", "same_operation", replay_safe=True),))

    def executor(step: Step, context: ExecutionContext) -> Observation:
        calls.append(step.id)
        return Observation(False, {"exit_code": 7})

    with StateStore(WorkspacePolicy(tmp_path)) as store:
        harness = make_harness(
            store,
            planner=planner,
            executor=executor,
            limits=ExecutionLimits(max_replans=5),
            replay_safe_actions=frozenset({"same_operation"}),
        )
        with pytest.raises(WorkbenchError, match="REPEATED_FAILURE"):
            harness.execute("repair")
        assert calls == ["try0", "try1", "try2"]


def test_unknown_effect_refuses_resume_after_restart(tmp_path: Path) -> None:
    calls = 0

    def executor(step: Step, context: ExecutionContext) -> Observation:
        nonlocal calls
        calls += 1
        raise RuntimeError("Transport connection vanished after dispatch")

    policy = WorkspacePolicy(tmp_path)
    with StateStore(policy) as store:
        harness = make_harness(store, executor=executor)
        with pytest.raises(RuntimeError):
            harness.execute("send externally")
        task_id = store.export()["tasks"][0]["id"]
        assert store.get_task(task_id)["state"] == "interrupted"
    with StateStore(policy) as store:
        harness = make_harness(store, executor=executor)
        with pytest.raises(WorkbenchError, match="OUTCOME_UNKNOWN"):
            harness.resume(task_id)
        assert calls == 1


def test_approval_is_host_supplied_and_resume_preserves_completed_steps(tmp_path: Path) -> None:
    approved = False
    calls: list[str] = []

    def planner(request: PlanRequest) -> Plan:
        return Plan(
            (
                Step("read", "inspect"),
                Step("write", "change", {"approval": "model-supplied"}, ("read",), "write"),
            )
        )

    def executor(step: Step, context: ExecutionContext) -> Observation:
        if step.effect == "write" and not approved:
            raise WorkbenchError("APPROVAL_REQUIRED", "Host approval is missing")
        calls.append(step.id)
        return observed(step, context)

    with StateStore(WorkspacePolicy(tmp_path)) as store:
        harness = make_harness(store, planner=planner, executor=executor)
        output = harness.execute("change")
        assert output["state"] == "awaiting_approval"
        assert output["completed_steps"] == ["read"]
        approved = True
        output = harness.resume(output["task_id"])
        assert output["state"] == "succeeded"
        assert calls == ["read", "write"]


def test_cancellation_records_inflight_result_and_prevents_next_dispatch(tmp_path: Path) -> None:
    calls: list[str] = []

    def planner(request: PlanRequest) -> Plan:
        return Plan((Step("first", "inspect"), Step("second", "inspect", dependencies=("first",))))

    with StateStore(WorkspacePolicy(tmp_path)) as store:

        def executor(step: Step, context: ExecutionContext) -> Observation:
            calls.append(step.id)
            harness.cancel(context.task_id)
            return observed(step, context)

        harness = make_harness(store, planner=planner, executor=executor)
        output = harness.execute("inspect")
        assert output["state"] == "cancelled" and calls == ["first"]
        assert output["observations"]["first"]["success"]
        assert store.export()["intents"][0]["state"] == "received"
        with pytest.raises(WorkbenchError, match="CONFLICT"):
            harness.resume(output["task_id"])


def test_step_and_deadline_budgets_survive_resume(tmp_path: Path) -> None:
    now = 100.0

    def executor(step: Step, context: ExecutionContext) -> Observation:
        nonlocal now
        now = 102.0
        return observed(step, context)

    with StateStore(WorkspacePolicy(tmp_path)) as store:
        harness = make_harness(
            store, executor=executor, clock=lambda: now, limits=ExecutionLimits(deadline_seconds=1)
        )
        with pytest.raises(WorkbenchError, match="DEADLINE_EXCEEDED"):
            harness.execute("inspect")
        task_id = store.export()["tasks"][0]["id"]
        assert store.load("execution", task_id)["results"]["inspect"]["success"]
        with pytest.raises(WorkbenchError, match="DEADLINE_EXCEEDED"):
            harness.resume(task_id)


def test_callback_pin_drift_and_empty_verifier_evidence_are_rejected(tmp_path: Path) -> None:
    with StateStore(WorkspacePolicy(tmp_path)) as store:
        harness = make_harness(store)
        output = harness.execute("inspect")
        changed = make_harness(store, pins={"host_callbacks": "fixture-v2"})
        with pytest.raises(WorkbenchError, match="CONFLICT"):
            changed.resume(output["task_id"])
        harness = make_harness(store, verifier=lambda request: Verification(True, {}))
        with pytest.raises(WorkbenchError, match="VALIDATION_ERROR"):
            harness.execute("empty evidence")


def test_real_repair_replans_then_resumes_exact_apply_and_runner_approvals(tmp_path: Path) -> None:
    before = "def discounted_total(price, rate):\n    return price * rate\n"
    after = "def discounted_total(price, rate):\n    return price * (1 - rate)\n"
    (tmp_path / "app.py").write_text(before)
    config = Config(
        commands={
            "unit": CommandConfig(
                (
                    sys.executable,
                    "-B",
                    "-c",
                    "from app import discounted_total; assert discounted_total(100, .2) == 80",
                )
            )
        }
    )
    policy = WorkspacePolicy(
        tmp_path, config, grants=Grant(write=True, execute=True, trusted_host=True)
    )
    approvals: dict[str, str] = {}
    effects: list[str] = []

    def planner(request: PlanRequest) -> Plan:
        steps = [Step("inspect", "inspect")]
        if request.replan:
            steps.append(
                Step("repair", "apply", {"proposal_id": proposal_id}, ("inspect",), "write")
            )
        return Plan(tuple(steps))

    def executor(step: Step, context: ExecutionContext) -> Observation:
        if step.action == "apply":
            result = changes.apply(step.arguments["proposal_id"], approval=approvals.get("apply"))
            effects.append(result["change_id"])
            return Observation(True, result)
        source = policy.read_source("app.py")
        return Observation(True, {"path": source.path, "source_hash": source.source_hash})

    def verifier(request: VerificationRequest) -> Verification:
        result = runner.execute("unit", approvals.get("unit"), "trusted-host")
        return Verification(result["exit_code"] == 0 and not result["timed_out"], result)

    with StateStore(policy) as store:
        changes, runner = ChangeWorkflow(policy, store), Runner(policy, store)
        proposal = changes.propose(
            [{"path": "app.py", "base_hash": text_hash(before), "content": after, "delete": False}],
            rationale="Apply the discount to the original total",
        )
        proposal_id = proposal["proposal_id"]
        approvals["unit"] = runner.review("unit", "trusted-host")["digest"]
        harness = make_harness(store, planner=planner, executor=executor, verifier=verifier)
        result = harness.execute("repair discounted_total")
        task_id = result["task_id"]
        assert result["state"] == "awaiting_approval"
        assert result["replans"] == 1 and not result["verification"]
        assert (tmp_path / "app.py").read_text() == before
        assert (
            store.load("execution", task_id)["history"][0]["verification"]["evidence"]["exit_code"]
            == 1
        )
        approvals["apply"] = proposal["digest"]
    with StateStore(policy) as store:
        changes, runner = ChangeWorkflow(policy, store), Runner(policy, store)
        harness = make_harness(store, planner=planner, executor=executor, verifier=verifier)
        result = harness.resume(task_id)
        assert result["state"] == "awaiting_approval"
        assert result["error"]["code"] == "STALE_APPROVAL"
        assert (tmp_path / "app.py").read_text() == after
        approvals["unit"] = runner.review("unit", "trusted-host")["digest"]
    with StateStore(policy) as store:
        changes, runner = ChangeWorkflow(policy, store), Runner(policy, store)
        harness = make_harness(store, planner=planner, executor=executor, verifier=verifier)
        result = harness.resume(task_id)
        assert result["state"] == "succeeded"
        assert result["verification"]["evidence"]["exit_code"] == 0
        assert len(effects) == 1
        assert harness.resume(task_id) == result and len(effects) == 1


@pytest.mark.parametrize("phase", ["observe", "complete"])
def test_crash_after_durable_receipt_reuses_completed_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    calls: list[str] = []
    stopped = False

    def executor(step: Step, context: ExecutionContext) -> Observation:
        calls.append(step.id)
        return observed(step, context)

    with StateStore(WorkspacePolicy(tmp_path)) as store:
        harness = make_harness(store, executor=executor)
        original = harness._checkpoint

        def stop(checkpoint: dict, current_phase: str, **changes: object) -> None:
            nonlocal stopped
            original(checkpoint, current_phase, **changes)
            if not stopped and current_phase == phase:
                stopped = True
                raise KeyboardInterrupt

        monkeypatch.setattr(harness, "_checkpoint", stop)
        with pytest.raises(KeyboardInterrupt):
            harness.execute("inspect")
        task_id = store.export()["tasks"][0]["id"]
        assert store.get_task(task_id)["state"] == "interrupted"
        assert harness.resume(task_id)["state"] == "succeeded"
        assert calls == ["inspect"]


def test_retryable_exception_is_not_proof_of_a_known_receipt(tmp_path: Path) -> None:
    def executor(step: Step, context: ExecutionContext) -> Observation:
        raise WorkbenchError("TRANSPORT_TIMEOUT", "The response was lost", retryable=True)

    with StateStore(WorkspacePolicy(tmp_path)) as store:
        harness = make_harness(store, executor=executor, replay_safe_actions=frozenset({"inspect"}))
        with pytest.raises(WorkbenchError, match="OUTCOME_UNKNOWN"):
            harness.execute("inspect")
        task_id = store.export()["tasks"][0]["id"]
        with pytest.raises(WorkbenchError, match="OUTCOME_UNKNOWN"):
            harness.resume(task_id)


def test_failed_unsafe_effect_cannot_replay_through_a_replan(tmp_path: Path) -> None:
    calls: list[str] = []

    def planner(request: PlanRequest) -> Plan:
        return Plan((Step(f"write{request.replan}", "write", effect="write"),))

    def executor(step: Step, context: ExecutionContext) -> Observation:
        calls.append(step.id)
        return Observation(False, {"status": "known_failure"}, retryable=True)

    with StateStore(WorkspacePolicy(tmp_path)) as store:
        harness = make_harness(store, planner=planner, executor=executor)
        with pytest.raises(WorkbenchError, match="REPLAY_DENIED"):
            harness.execute("write")
        assert calls == ["write0"]


def test_completed_effect_is_reused_even_when_replanner_renames_it(tmp_path: Path) -> None:
    calls: list[str] = []
    verifications = 0

    def planner(request: PlanRequest) -> Plan:
        return Plan((Step(f"write{request.replan}", "write", effect="write"),))

    def executor(step: Step, context: ExecutionContext) -> Observation:
        calls.append(step.id)
        return Observation(True, {"receipt": "actual_effect"})

    def verifier(request: VerificationRequest) -> Verification:
        nonlocal verifications
        verifications += 1
        return Verification(verifications == 2, {"checks": verifications})

    with StateStore(WorkspacePolicy(tmp_path)) as store:
        harness = make_harness(store, planner=planner, executor=executor, verifier=verifier)
        outcome = harness.execute("write")
        assert outcome["state"] == "succeeded"
        assert calls == ["write0"] and outcome["completed_steps"] == ["write1"]


def test_unknown_child_effect_blocks_successful_root_verification(tmp_path: Path) -> None:
    with StateStore(WorkspacePolicy(tmp_path)) as store:

        def executor(step: Step, context: ExecutionContext) -> Observation:
            child = store.create_task(
                "specialist", "read externally", {}, context.task_id, context.task_id
            )
            store.unknown(store.intent(child))
            return observed(step, context)

        harness = make_harness(store, executor=executor)
        with pytest.raises(WorkbenchError, match="OUTCOME_UNKNOWN"):
            harness.execute("inspect")
        task_id = next(task["id"] for task in store.export()["tasks"] if task["parent_id"] is None)
        assert store.get_task(task_id)["state"] == "failed"
        with pytest.raises(WorkbenchError, match="OUTCOME_UNKNOWN"):
            harness.resume(task_id)


def test_sensitive_observations_are_redacted_before_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    credential = "secret-observation-fixture-123456789"
    monkeypatch.setenv("OPENAI_API_KEY", credential)
    with StateStore(WorkspacePolicy(tmp_path)) as store:

        def executor(step: Step, context: ExecutionContext) -> Observation:
            return Observation(True, {"untrusted_output": credential})

        def verifier(request: VerificationRequest) -> Verification:
            assert credential not in str(request.observations)
            return verified(request)

        harness = make_harness(store, executor=executor, verifier=verifier)
        result = harness.execute("inspect")
        assert credential not in str(result) + str(harness.trace(result["task_id"]))


def test_step_budget_prevents_additional_dispatch(tmp_path: Path) -> None:
    calls: list[str] = []

    def planner(request: PlanRequest) -> Plan:
        return Plan((Step(f"read{request.replan}", "inspect", {"revision": request.replan}),))

    def executor(step: Step, context: ExecutionContext) -> Observation:
        calls.append(step.id)
        return observed(step, context)

    with StateStore(WorkspacePolicy(tmp_path)) as store:
        harness = make_harness(
            store,
            planner=planner,
            executor=executor,
            verifier=lambda request: Verification(False, {"exit_code": 1}),
            limits=ExecutionLimits(max_steps=1),
        )
        with pytest.raises(WorkbenchError, match="STEP_EXHAUSTED"):
            harness.execute("inspect")
        assert calls == ["read0"]


@pytest.mark.parametrize("effect", ["read", "write"])
def test_replan_recomputes_steps_whose_dependencies_changed(tmp_path: Path, effect: str) -> None:
    calls: list[list[object]] = []

    def planner(request: PlanRequest) -> Plan:
        return Plan(
            (
                Step("input", "read", {"value": 1 if request.replan == 0 else 2}),
                Step("double", "double", dependencies=("input",), effect=effect),
            )
        )

    def executor(step: Step, context: ExecutionContext) -> Observation:
        calls.append([step.id, step.arguments])
        if step.id == "input":
            return Observation(True, {"value": step.arguments["value"]})
        return Observation(True, {"double": context.dependencies["input"].evidence["value"] * 2})

    def verifier(request: VerificationRequest) -> Verification:
        value = request.observations["double"].evidence["double"]
        return Verification(value == 4, {"double": value})

    with StateStore(WorkspacePolicy(tmp_path)) as store:
        harness = make_harness(store, planner=planner, executor=executor, verifier=verifier)
        assert harness.execute("Read 2 and double it")["state"] == "succeeded"
        assert calls == [
            ["input", {"value": 1}],
            ["double", {}],
            ["input", {"value": 2}],
            ["double", {}],
        ]


def test_effect_reuse_binds_the_whole_upstream_operation_chain(tmp_path: Path) -> None:
    calls: list[str] = []
    current = {"value": 0}

    def planner(request: PlanRequest) -> Plan:
        return Plan(
            (
                Step("input", "read", {"value": 1 if request.replan == 0 else 2}),
                Step("write", "apply", dependencies=("input",), effect="write"),
                Step("check", "test", dependencies=("write",), effect="external"),
                Step("report", "notify", dependencies=("check",), effect="external"),
            )
        )

    def executor(step: Step, context: ExecutionContext) -> Observation:
        calls.append(step.id)
        if step.id == "input":
            return Observation(True, {"value": step.arguments["value"]})
        if step.id == "write":
            current["value"] = context.dependencies["input"].evidence["value"]
            return Observation(True, {"receipt": "applied"})
        if step.id == "check":
            return Observation(True, {"checked_value": current["value"]})
        return Observation(True, {"sent": context.dependencies["check"].evidence["checked_value"]})

    def verifier(request: VerificationRequest) -> Verification:
        sent = request.observations["report"].evidence["sent"]
        return Verification(sent == 2, {"sent": sent})

    with StateStore(WorkspacePolicy(tmp_path)) as store:
        harness = make_harness(store, planner=planner, executor=executor, verifier=verifier)
        assert harness.execute("Write, check and report 2")["state"] == "succeeded"
        assert calls == ["input", "write", "check", "report"] * 2


@pytest.mark.parametrize("contract", [1, 2, 3])
def test_checkpoints_from_an_earlier_execution_contract_are_refused_before_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, contract: int
) -> None:
    from agentic_workbench import execution

    effects: list[str] = []
    gate = {"open": False}

    def planner(request: PlanRequest) -> Plan:
        name = "write0" if request.replan == 0 else "write1"
        return Plan(
            (
                Step("input", "read", {"value": 1}),
                Step(name, "write", dependencies=("input",), effect="write"),
                Step("gate", "gate", dependencies=(name,)),
            )
        )

    def executor(step: Step, context: ExecutionContext) -> Observation:
        if step.id == "input":
            return Observation(True, {"value": 1})
        if step.action == "write":
            effects.append(step.id)
            return Observation(True, {"receipt": "sent"})
        if not gate["open"]:
            raise WorkbenchError("APPROVAL_REQUIRED", "Resume gate")
        return Observation(True, {"gate": True})

    def verifier(request: VerificationRequest) -> Verification:
        return Verification(bool(request.history), {"verified": bool(request.history)})

    options = {"planner": planner, "executor": executor, "verifier": verifier}
    with StateStore(WorkspacePolicy(tmp_path)) as store:
        monkeypatch.setattr(execution, "EXECUTION_CONTRACT", contract)
        try:
            make_harness(store, **options).execute("Send one write")
        except WorkbenchError as error:
            assert error.code == "APPROVAL_REQUIRED"
        task = store.export()["tasks"][0]["id"]
        before = make_harness(store, **options).trace(task)
        monkeypatch.undo()
        gate["open"] = True
        current = make_harness(store, **options)
        with pytest.raises(WorkbenchError, match="CONFLICT") as raised:
            current.execute("Send one write", task_id=task)
        assert f"execution contract {contract}" in raised.value.message
        assert effects == ["write0"] and current.trace(task) == before


def test_returning_to_an_earlier_input_reapplies_and_rechecks(tmp_path: Path) -> None:
    world = {"value": 0}
    calls: list[str] = []

    def planner(request: PlanRequest) -> Plan:
        value = (1, 2, 1)[request.replan]
        return Plan(
            (
                Step("input", "read", {"value": value}),
                Step("write", "apply", dependencies=("input",), effect="write"),
                Step("check", "test", dependencies=("write",), effect="external"),
            )
        )

    def executor(step: Step, context: ExecutionContext) -> Observation:
        calls.append(step.id)
        if step.id == "input":
            return Observation(True, {"value": step.arguments["value"]})
        if step.id == "write":
            world["value"] = context.dependencies["input"].evidence["value"]
            return Observation(True, {"receipt": "applied"})
        return Observation(True, {"checked": world["value"]})

    def verifier(request: VerificationRequest) -> Verification:
        checked = request.observations["check"].evidence["checked"]
        return Verification(len(request.history) == 2 and checked == world["value"], {"c": checked})

    with StateStore(WorkspacePolicy(tmp_path)) as store:
        harness = make_harness(store, planner=planner, executor=executor, verifier=verifier)
        assert harness.execute("Apply 1, then 2, then 1")["state"] == "succeeded"
        assert world["value"] == 1 and calls == ["input", "write", "check"] * 3


def test_renaming_an_upstream_step_reuses_the_whole_completed_chain(tmp_path: Path) -> None:
    sent = {"charge": 0, "email": 0, "ship": 0}

    def planner(request: PlanRequest) -> Plan:
        first = "charge" if request.replan == 0 else "charge_renamed"
        return Plan(
            (
                Step(first, "charge", {"amount": 5}, effect="write"),
                Step("email", "email", dependencies=(first,), effect="external"),
                Step("ship", "ship", dependencies=("email",), effect="write"),
            )
        )

    def executor(step: Step, context: ExecutionContext) -> Observation:
        sent[step.action] += 1
        return Observation(True, {"done": step.action})

    def verifier(request: VerificationRequest) -> Verification:
        return Verification(len(request.history) == 1, {"rounds": len(request.history)})

    with StateStore(WorkspacePolicy(tmp_path)) as store:
        harness = make_harness(store, planner=planner, executor=executor, verifier=verifier)
        assert harness.execute("Charge, email and ship once")["state"] == "succeeded"
        assert sent == {"charge": 1, "email": 1, "ship": 1}


def test_preserved_effect_stays_reusable_when_a_later_round_renames_it(tmp_path: Path) -> None:
    calls: list[str] = []

    def planner(request: PlanRequest) -> Plan:
        name = "send" if request.replan < 2 else "send_renamed"
        return Plan((Step(name, "send", {"message": "once"}, effect="external"),))

    def executor(step: Step, context: ExecutionContext) -> Observation:
        calls.append(step.id)
        return Observation(True, {"receipt": "sent"})

    def verifier(request: VerificationRequest) -> Verification:
        return Verification(len(request.history) == 2, {"round": len(request.history)})

    with StateStore(WorkspacePolicy(tmp_path)) as store:
        harness = make_harness(store, planner=planner, executor=executor, verifier=verifier)
        result = harness.execute("Send one message and verify on the third round")
        assert result["state"] == "succeeded" and calls == ["send"]
        assert {intent["state"] for intent in store.export()["intents"]} == {"received"}


@pytest.mark.parametrize("approval_restart", [False, True])
def test_compacted_effect_chain_reuses_receipts_after_rename_and_restart(
    tmp_path: Path, approval_restart: bool
) -> None:
    calls = {"prepare": 0, "email": 0, "ship": 0, "fill": 0}
    gate = {"open": not approval_restart}
    last_round = 2 if approval_restart else 1

    def planner(request: PlanRequest) -> Plan:
        first = "prepare" if request.replan < last_round else "prepare_renamed"
        steps = [
            Step(first, "prepare", {"id": 1}, effect="write"),
            Step("email", "email", dependencies=(first,), effect="external"),
            Step("ship", "ship", dependencies=("email",), effect="external"),
            *(Step(f"fill{n}", "fill", {"n": n}, effect="write") for n in range(8)),
        ]
        if approval_restart:
            steps.append(Step("gate", "gate", dependencies=("ship",)))
        return Plan(tuple(steps))

    def executor(step: Step, context: ExecutionContext) -> Observation:
        if step.action == "gate":
            if not gate["open"]:
                raise WorkbenchError("APPROVAL_REQUIRED", "Host approval is missing")
            return Observation(True, {"approved": True})
        calls[step.action] += 1
        evidence = {"receipt": "done"}
        if step.action in {"prepare", "fill"}:
            evidence["log"] = "x" * 60_000
        return Observation(True, evidence)

    def verifier(request: VerificationRequest) -> Verification:
        return Verification(len(request.history) == last_round, {"round": len(request.history)})

    options = {"planner": planner, "executor": executor, "verifier": verifier}
    policy = WorkspacePolicy(tmp_path)
    with StateStore(policy) as store:
        result = make_harness(store, **options).execute("Prepare, email and ship once")
        if approval_restart:
            assert result["state"] == "awaiting_approval"
            assert result["observations"]["prepare"]["truncated"]
            task_id = result["task_id"]
    if approval_restart:
        gate["open"] = True
        with StateStore(policy) as store:
            result = make_harness(store, **options).resume(task_id)
    assert result["state"] == "succeeded"
    assert calls == {"prepare": 1, "email": 1, "ship": 1, "fill": 8}
    assert result["observations"]["prepare_renamed"]["truncated"]
    with StateStore(policy) as store:
        assert {intent["state"] for intent in store.export()["intents"]} == {"received"}


@pytest.mark.parametrize("identity_map", ["result_digests", "effect_result_digests"])
@pytest.mark.parametrize("damage", ["missing", "empty", "invalid"])
def test_resume_refuses_unavailable_result_identity_before_dispatch(
    tmp_path: Path, identity_map: str, damage: str
) -> None:
    calls: list[str] = []
    gate = {"open": False}

    def planner(request: PlanRequest) -> Plan:
        return Plan(
            (
                Step("write", "write", effect="write"),
                Step("gate", "gate", dependencies=("write",)),
            )
        )

    def executor(step: Step, context: ExecutionContext) -> Observation:
        if step.action == "gate" and not gate["open"]:
            raise WorkbenchError("APPROVAL_REQUIRED", "Host approval is missing")
        calls.append(step.id)
        return Observation(True, {"receipt": "done"})

    options = {"planner": planner, "executor": executor}
    policy = WorkspacePolicy(tmp_path)
    with StateStore(policy) as store:
        result = make_harness(store, **options).execute("Write once")
        assert result["state"] == "awaiting_approval"
        task_id = result["task_id"]
        checkpoint = store.load("execution", task_id)
        if damage == "missing":
            checkpoint.pop(identity_map, None)
        else:
            source = "results" if identity_map == "result_digests" else "completed_effects"
            checkpoint[identity_map] = (
                {} if damage == "empty" else dict.fromkeys(checkpoint[source], "invalid")
            )
        store.update("execution", task_id, checkpoint)
        before = make_harness(store, **options).trace(task_id)
    gate["open"] = True
    with StateStore(policy) as store:
        harness = make_harness(store, **options)
        with pytest.raises(WorkbenchError, match="CONFLICT"):
            harness.resume(task_id)
        assert calls == ["write"] and harness.trace(task_id) == before
        assert store.get_task(task_id)["state"] == "awaiting_approval"


def test_renaming_an_upstream_step_cannot_unblock_a_failed_unsafe_effect(tmp_path: Path) -> None:
    payments: list[int] = []

    def planner(request: PlanRequest) -> Plan:
        source = "source" if request.replan == 0 else "source_renamed"
        return Plan(
            (
                Step(source, "read", {"invoice": 7}),
                Step("pay", "pay", dependencies=(source,), effect="write"),
            )
        )

    def executor(step: Step, context: ExecutionContext) -> Observation:
        if step.action == "read":
            return Observation(True, {"invoice": 7})
        payments.append(1)
        return Observation(False, {"status": "declined"})

    with StateStore(WorkspacePolicy(tmp_path)) as store:
        harness = make_harness(store, planner=planner, executor=executor)
        with pytest.raises(WorkbenchError, match="REPLAY_DENIED"):
            harness.execute("Pay invoice 7")
        assert payments == [1]


def test_resumed_approval_then_renamed_replan_keeps_one_completed_write(tmp_path: Path) -> None:
    effects: list[str] = []
    gate = {"open": False}

    def planner(request: PlanRequest) -> Plan:
        name = "write0" if request.replan == 0 else "write1"
        return Plan(
            (
                Step("input", "read", {"value": 1}),
                Step(name, "write", dependencies=("input",), effect="write"),
                Step("gate", "gate", dependencies=(name,)),
            )
        )

    def executor(step: Step, context: ExecutionContext) -> Observation:
        if step.id == "input":
            return Observation(True, {"value": 1})
        if step.action == "write":
            effects.append(step.id)
            return Observation(True, {"receipt": "sent"})
        if not gate["open"]:
            raise WorkbenchError("APPROVAL_REQUIRED", "Resume gate")
        return Observation(True, {"gate": True})

    def verifier(request: VerificationRequest) -> Verification:
        return Verification(bool(request.history), {"verified": bool(request.history)})

    options = {"planner": planner, "executor": executor, "verifier": verifier}
    with StateStore(WorkspacePolicy(tmp_path)) as store:
        try:
            make_harness(store, **options).execute("Send one write")
        except WorkbenchError as error:
            assert error.code == "APPROVAL_REQUIRED"
        task = store.export()["tasks"][0]["id"]
        gate["open"] = True
        result = make_harness(store, **options).execute("Send one write", task_id=task)
        assert result["state"] == "succeeded" and effects == ["write0"]


def test_an_oversized_observation_keeps_a_known_bounded_receipt(tmp_path: Path) -> None:
    def planner(request: PlanRequest) -> Plan:
        return Plan((Step("check", "test", effect="external"),))

    def executor(step: Step, context: ExecutionContext) -> Observation:
        return Observation(True, {"exit_code": 0, "stdout": "\x01" * 20_000})

    def verifier(request: VerificationRequest) -> Verification:
        observation = request.observations["check"]
        return Verification(
            observation.evidence["exit_code"] == 0 and observation.truncated, {"exit_code": 0}
        )

    with StateStore(WorkspacePolicy(tmp_path)) as store:
        harness = make_harness(store, planner=planner, executor=executor, verifier=verifier)
        assert harness.execute("Run the check")["state"] == "succeeded"
        assert {intent["state"] for intent in store.export()["intents"]} == {"received"}


def test_many_large_observations_keep_every_receipt_known(tmp_path: Path) -> None:
    def planner(request: PlanRequest) -> Plan:
        return Plan(tuple(Step(f"write{n}", "write", {"n": n}, effect="write") for n in range(12)))

    def executor(step: Step, context: ExecutionContext) -> Observation:
        return Observation(True, {"n": step.arguments["n"], "log": "x" * 60_000})

    def verifier(request: VerificationRequest) -> Verification:
        return Verification(len(request.observations) == 12, {"writes": len(request.observations)})

    with StateStore(WorkspacePolicy(tmp_path)) as store:
        harness = make_harness(store, planner=planner, executor=executor, verifier=verifier)
        assert harness.execute("Write twelve logs")["state"] == "succeeded"
        assert {intent["state"] for intent in store.export()["intents"]} == {"received"}


def test_a_completed_execution_reports_its_result_under_any_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agentic_workbench import execution

    with StateStore(WorkspacePolicy(tmp_path)) as store:
        monkeypatch.setattr(execution, "EXECUTION_CONTRACT", 1)
        first = make_harness(store).execute("Inspect")
        monkeypatch.undo()
        task = store.export()["tasks"][0]["id"]
        assert make_harness(store).execute("Inspect", task_id=task) == first
