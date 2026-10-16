"""Host-controlled engineering loops with durable observations and verified completion."""

from __future__ import annotations

import math
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from .agents import WorkerLease
from .errors import WorkbenchError
from .models import bounded_json, canonical_hash, canonical_json
from .state import StateStore


@dataclass(frozen=True)
class Step:
    id: str
    action: str
    arguments: dict[str, Any] = field(default_factory=dict)
    dependencies: tuple[str, ...] = ()
    effect: Literal["read", "write", "external"] = "read"
    replay_safe: bool = False


@dataclass(frozen=True)
class Plan:
    steps: tuple[Step, ...]


@dataclass(frozen=True)
class Observation:
    success: bool
    evidence: dict[str, Any] = field(default_factory=dict)
    retryable: bool = False
    unknown: bool = False
    error_code: str | None = None
    # Set by the harness when evidence was bounded to fit an observation or checkpoint.
    truncated: bool = False


@dataclass(frozen=True)
class Verification:
    success: bool
    evidence: dict[str, Any]
    reason: str = ""


# Bump when effect identity or checkpoint semantics change. Resume refuses checkpoints from
# another contract, so completed effects keyed under an older identity can never replay.
# Contract 4: dependency result digests survive evidence compaction, and preserved effects
# remain members of the current round. Step IDs never bind operation identity.
EXECUTION_CONTRACT = 4
_OBSERVATION_BYTES = 65_536
_CHECKPOINT_BYTES = 1_000_000


@dataclass(frozen=True)
class ExecutionLimits:
    max_steps: int = 32
    max_replans: int = 2
    max_attempts: int = 2
    repeated_failure_limit: int = 3
    deadline_seconds: float = 3600

    def validate(self) -> None:
        for name, maximum, minimum in (
            ("max_steps", 256, 1),
            ("max_replans", 16, 0),
            ("max_attempts", 8, 1),
            ("repeated_failure_limit", 16, 1),
        ):
            value = getattr(self, name)
            if type(value) is not int or not minimum <= value <= maximum:
                raise WorkbenchError("VALIDATION_ERROR", "Invalid execution loop limit")
        if (
            type(self.deadline_seconds) not in (int, float)
            or not math.isfinite(self.deadline_seconds)
            or not 0 < self.deadline_seconds <= 604_800
        ):
            raise WorkbenchError("VALIDATION_ERROR", "Invalid execution deadline")


@dataclass(frozen=True)
class PlanRequest:
    task_id: str
    instruction: str
    history: tuple[dict[str, Any], ...]
    replan: int


@dataclass(frozen=True)
class ExecutionContext:
    task_id: str
    step_id: str
    attempt: int
    dependencies: dict[str, Observation]


@dataclass(frozen=True)
class VerificationRequest:
    task_id: str
    instruction: str
    observations: dict[str, Observation]
    history: tuple[dict[str, Any], ...]


def validate_plan(plan: Plan, maximum: int = 32) -> None:
    if (
        not isinstance(plan, Plan)
        or not isinstance(plan.steps, tuple)
        or not 1 <= len(plan.steps) <= maximum
        or any(not isinstance(step, Step) for step in plan.steps)
    ):
        raise WorkbenchError("VALIDATION_ERROR", "Plan requires bounded typed steps")
    identifiers = {step.id for step in plan.steps if isinstance(step.id, str)}
    if len(identifiers) != len(plan.steps):
        raise WorkbenchError("VALIDATION_ERROR", "Plan step identifiers must be unique")
    for step in plan.steps:
        if (
            not isinstance(step.id, str)
            or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", step.id)
            or not isinstance(step.action, str)
            or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", step.action)
            or not isinstance(step.arguments, dict)
            or not isinstance(step.dependencies, tuple)
            or any(not isinstance(dep, str) for dep in step.dependencies)
            or len(set(step.dependencies)) != len(step.dependencies)
            or not set(step.dependencies) <= identifiers
            or step.effect not in ("read", "write", "external")
            or type(step.replay_safe) is not bool
        ):
            raise WorkbenchError("VALIDATION_ERROR", "Invalid execution step")
        if len(canonical_json(step.arguments).encode()) > 65_536:
            raise WorkbenchError("LIMIT_EXCEEDED", "Execution arguments exceed byte limit")
    completed: set[str] = set()
    while len(completed) != len(plan.steps):
        ready = {
            step.id
            for step in plan.steps
            if step.id not in completed and set(step.dependencies) <= completed
        }
        if not ready:
            raise WorkbenchError("VALIDATION_ERROR", "Execution plan contains a cycle")
        completed.update(ready)
    if len(canonical_json(asdict(plan)).encode()) > 262_144:
        raise WorkbenchError("LIMIT_EXCEEDED", "Execution plan exceeds byte limit")


def _observation(value: Observation) -> dict[str, Any]:
    if (
        not isinstance(value, Observation)
        or any(
            type(getattr(value, key)) is not bool
            for key in ("success", "retryable", "unknown", "truncated")
        )
        or not isinstance(value.evidence, dict)
        or value.success
        and (value.unknown or value.retryable or value.error_code is not None)
        or value.unknown
        and value.retryable
        or value.error_code is not None
        and (
            not isinstance(value.error_code, str)
            or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", value.error_code)
        )
    ):
        raise WorkbenchError("VALIDATION_ERROR", "Invalid execution observation")
    rendered = asdict(value)
    if len(canonical_json(rendered).encode()) > _OBSERVATION_BYTES:
        # The operation already ran: keep a known receipt with bounded evidence.
        rendered["evidence"] = bounded_json(rendered["evidence"], _OBSERVATION_BYTES - 1_024) or {}
        rendered["truncated"] = True
    return rendered


def _verification(value: Verification) -> dict[str, Any]:
    if (
        not isinstance(value, Verification)
        or type(value.success) is not bool
        or not isinstance(value.evidence, dict)
        or not value.evidence
        or not isinstance(value.reason, str)
        or len(value.reason) > 4096
    ):
        raise WorkbenchError("VALIDATION_ERROR", "Host verification requires actual evidence")
    rendered = asdict(value)
    if len(canonical_json(rendered).encode()) > 65_536:
        raise WorkbenchError("LIMIT_EXCEEDED", "Verification evidence exceeds byte limit")
    return rendered


class Harness:
    """Callbacks are trusted host code; plans, arguments and results confer no authority.

    Cancellation and deadlines stop dispatch at callback boundaries. Host transports must
    enforce operation timeouts; Python callbacks are not an operating-system sandbox.
    """

    def __init__(
        self,
        store: StateStore,
        *,
        planner: Callable[[PlanRequest], Plan],
        executor: Callable[[Step, ExecutionContext], Observation],
        verifier: Callable[[VerificationRequest], Verification],
        pins: dict[str, Any],
        limits: ExecutionLimits | None = None,
        replay_safe_actions: frozenset[str] = frozenset(),
        clock: Callable[[], float] = time.time,
    ) -> None:
        limits = limits or ExecutionLimits()
        limits.validate()
        if not isinstance(pins, dict) or not pins:
            raise WorkbenchError(
                "VALIDATION_ERROR", "Host callbacks require explicit contract pins"
            )
        if (
            not isinstance(replay_safe_actions, frozenset)
            or any(
                not isinstance(action, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", action)
                for action in replay_safe_actions
            )
            or any(not callable(callback) for callback in (planner, executor, verifier, clock))
        ):
            raise WorkbenchError("VALIDATION_ERROR", "Invalid host execution callbacks")
        self.store, self.planner, self.executor, self.verifier = store, planner, executor, verifier
        self.limits, self.replay_safe_actions, self.clock = limits, replay_safe_actions, clock
        self.pins = {
            "execution_contract": EXECUTION_CONTRACT,
            "host": pins,
            "limits": asdict(limits),
            "replay_safe_actions": sorted(replay_safe_actions),
            "workspace_id": store.policy.workspace_id,
            "policy_fingerprint": store.policy.fingerprint,
        }
        canonical_json(self.pins)

    def _task(self, task_id: str) -> dict[str, Any]:
        task = self.store.get_task(task_id)
        if task["agent"] != "harness" or task["parent_id"] is not None:
            raise WorkbenchError("VALIDATION_ERROR", "Task is not an engineering execution root")
        return task

    def status(self, task_id: str) -> dict[str, Any]:
        task = self._task(task_id)
        checkpoint = self.store.load("execution", task_id)
        if checkpoint is None:
            raise WorkbenchError("STATE_ERROR", "Execution checkpoint is unavailable")
        return {
            "task_id": task_id,
            "state": task["state"],
            "phase": checkpoint["phase"],
            "completed_steps": [
                identifier
                for identifier, observation in checkpoint["results"].items()
                if observation["success"]
            ],
            "observations": checkpoint["results"],
            "verification": checkpoint["verification"],
            "steps": checkpoint["steps"],
            "replans": checkpoint["plan_round"],
            "error": None if task["state"] == "succeeded" else task["error"],
        }

    def trace(self, task_id: str) -> list[dict[str, Any]]:
        self._task(task_id)
        return [
            record["value"]
            for record in self.store.list_records("execution_trace")
            if record["value"]["task_id"] == task_id
        ]

    def cancel(self, task_id: str) -> dict[str, Any]:
        task = self._task(task_id)
        if task["state"] == "succeeded":
            raise WorkbenchError("CONFLICT", "Completed execution cannot be cancelled")
        if task["state"] != "cancelled":
            self.store.cancel_tree(task_id)
        return self.status(task_id)

    def resume(self, task_id: str) -> dict[str, Any]:
        return self.execute(self._task(task_id)["instruction"], task_id=task_id)

    def _checkpoint(
        self,
        checkpoint: dict[str, Any],
        phase: str,
        *,
        receipt_intent: str | None = None,
        receipt: dict[str, Any] | None = None,
        **changes: Any,
    ) -> None:
        checkpoint.update(changes)
        checkpoint["phase"] = phase
        checkpoint["sequence"] += 1
        self._compact(checkpoint)
        try:
            self.store.execution_checkpoint(
                checkpoint["task_id"], checkpoint["owner"], checkpoint, receipt_intent, receipt
            )
        except WorkbenchError as error:
            if (
                error.code != "CONFLICT"
                or self._task(checkpoint["task_id"])["state"] != "cancelled"
            ):
                raise
            if receipt_intent is None or receipt is None:
                raise WorkbenchError("CANCELLED", "Execution was cancelled by the host") from None
            # A completed callback still needs its known receipt after cancellation.
            self.store.receipt(receipt_intent, receipt)
            checkpoint["state"] = "cancelled"
            self.store.update("execution", checkpoint["task_id"], checkpoint)
        self.store.save(
            "execution_trace",
            f"{checkpoint['task_id']}:{checkpoint['sequence']:06d}",
            {
                "task_id": checkpoint["task_id"],
                "sequence": checkpoint["sequence"],
                "phase": phase,
                "elapsed_ms": round(max(0, self.clock() - checkpoint["started_at"]) * 1000, 3),
                "step": checkpoint["current_step"],
                "steps": checkpoint["steps"],
                "replans": checkpoint["plan_round"],
                "observation": (
                    checkpoint["results"].get(checkpoint["current_step"])
                    if phase == "observe"
                    else None
                ),
                "verification": checkpoint["verification"] if phase == "verify" else None,
                "reflection": checkpoint["history"][-1:] if phase == "reflect" else [],
            },
        )
        self.store.event(checkpoint["task_id"], f"harness.{phase}", {"status": phase})

    @staticmethod
    def _compact(checkpoint: dict[str, Any]) -> None:
        """Keep a checkpoint under the state record cap by bounding stored evidence.

        A receipt commits together with its checkpoint, so an oversized checkpoint must
        shrink rather than fail: a completed effect keeps a known receipt.
        """
        if len(canonical_json(checkpoint).encode()) <= _CHECKPOINT_BYTES:
            return
        observations = [*checkpoint["results"].values(), *checkpoint["completed_effects"].values()]
        for entry in checkpoint["history"]:
            observations += list(entry["observations"].values())
        for budget in (16_384, 4_096, 1_024, 256):
            for observation in observations:
                if len(canonical_json(observation["evidence"]).encode()) > budget:
                    observation["evidence"] = bounded_json(observation["evidence"], budget) or {}
                    observation["truncated"] = True
            if len(canonical_json(checkpoint).encode()) <= _CHECKPOINT_BYTES:
                return

    def _guard(self, checkpoint: dict[str, Any], owner: str, lease: WorkerLease) -> None:
        task = self._task(checkpoint["task_id"])
        if self.store.cancelled(checkpoint["task_id"]):
            raise WorkbenchError("CANCELLED", "Execution was cancelled by the host")
        if task["state"] != "running" or task["owner"] != owner:
            raise WorkbenchError("CONFLICT", "Execution worker no longer owns the task")
        lease.check()
        if self.clock() >= checkpoint["deadline_at"]:
            raise WorkbenchError("DEADLINE_EXCEEDED", "Execution deadline is exhausted")

    def _accept_plan(self, checkpoint: dict[str, Any], plan: Plan) -> None:
        validate_plan(plan, min(self.limits.max_steps, 32))
        if self.store.policy.redactor.contains_secret(canonical_json(asdict(plan))):
            raise WorkbenchError("POLICY_DENIED", "Plan arguments cannot contain credentials")
        previous = {step["id"]: step for step in checkpoint["plan"]}
        serialized = [
            {**asdict(step), "dependencies": list(step.dependencies)} for step in plan.steps
        ]
        unchanged = [
            step
            for step in serialized
            if previous.get(step["id"]) == step
            and checkpoint["results"].get(step["id"], {}).get("success")
        ]
        # Keep a result only when its whole dependency closure is also kept (n <= 32).
        preserved: dict[str, Any] = {}
        while kept := [
            step
            for step in unchanged
            if step["id"] not in preserved and set(step["dependencies"]) <= preserved.keys()
        ]:
            preserved.update({step["id"]: checkpoint["results"][step["id"]] for step in kept})
        preserved_digests = {
            identifier: checkpoint["result_digests"][identifier] for identifier in preserved
        }
        # Compute against the old plan before its dependency routing labels are replaced.
        preserved_effects = [
            self._signature(step, checkpoint)
            for step in plan.steps
            if step.id in preserved and step.effect != "read"
        ]
        self._checkpoint(
            checkpoint,
            "execute",
            plan=serialized,
            results=preserved,
            result_digests=preserved_digests,
            # Reuse rolls forward one round: an effect from an older round may have been
            # superseded by a later one, so it is dispatched again, never reused stale.
            previous_effects=checkpoint["round_effects"],
            round_effects=preserved_effects,
            attempts={},
            current_step=None,
            dispatch_started=False,
            intent_id=None,
            verification=None,
        )

    def _reflect(self, checkpoint: dict[str, Any], reason: str) -> None:
        checkpoint["history"].append(
            {
                "round": checkpoint["plan_round"],
                "reason": reason,
                "observations": checkpoint["results"],
                "verification": checkpoint["verification"],
            }
        )
        self._checkpoint(checkpoint, "reflect")
        if checkpoint["plan_round"] >= self.limits.max_replans:
            raise WorkbenchError("REPLAN_EXHAUSTED", "Execution replan budget is exhausted")
        self._checkpoint(
            checkpoint, "plan", plan_round=checkpoint["plan_round"] + 1, current_step=None
        )

    @staticmethod
    def _signature(step: Step, checkpoint: dict[str, Any]) -> str:
        """Operation identity bound to its whole dependency closure (at most 32 steps)."""
        plan = {item["id"]: item for item in checkpoint["plan"]}
        result_digests, memo = checkpoint["result_digests"], {}

        def identity(action: str, arguments: Any, dependencies: Any) -> str:
            operation: dict[str, Any] = {"action": action, "arguments": arguments}
            if dependencies:
                # Upstream identities and results both bind reuse, so a change anywhere in
                # the closure is a different operation, even behind an identical receipt.
                # Dependencies bind by identity, never by step ID (a routing label), so a
                # renamed step cannot re-send or unblock anything; multiplicity is kept.
                operation["inputs"] = sorted(
                    (
                        {"operation": upstream(dep), "result": result_digests[dep]}
                        for dep in dependencies
                    ),
                    key=canonical_json,
                )
            return canonical_hash(operation)

        def upstream(step_id: str) -> str:
            if step_id not in memo:
                item = plan[step_id]
                memo[step_id] = identity(item["action"], item["arguments"], item["dependencies"])
            return memo[step_id]

        return identity(step.action, step.arguments, step.dependencies)

    def _dispatch(
        self, checkpoint: dict[str, Any], step: Step, owner: str, lease: WorkerLease
    ) -> None:
        self._guard(checkpoint, owner, lease)
        if checkpoint["steps"] >= self.limits.max_steps:
            raise WorkbenchError("STEP_EXHAUSTED", "Execution step budget is exhausted")
        signature = self._signature(step, checkpoint)
        if signature in checkpoint["round_effects"] or signature in checkpoint["previous_effects"]:
            checkpoint["results"][step.id] = checkpoint["completed_effects"][signature]
            checkpoint["result_digests"][step.id] = checkpoint["effect_result_digests"][signature]
            if signature not in checkpoint["round_effects"]:
                checkpoint["round_effects"].append(signature)
            self._checkpoint(checkpoint, "observe", current_step=step.id)
            return
        replay_safe = (
            step.effect == "read" and step.replay_safe and step.action in self.replay_safe_actions
        )
        if checkpoint["failures"].get(signature, 0) and not replay_safe:
            raise WorkbenchError(
                "REPLAY_DENIED", "Failed operation is not host-approved for replay"
            )
        checkpoint["attempts"][step.id] = checkpoint["attempts"].get(step.id, 0) + 1
        intent_id = self.store.intent(checkpoint["task_id"], "harness", {"payload_hash": signature})
        try:
            self._checkpoint(
                checkpoint,
                "execute",
                current_step=step.id,
                dispatch_started=True,
                intent_id=intent_id,
                steps=checkpoint["steps"] + 1,
            )
            self._guard(checkpoint, owner, lease)
        except WorkbenchError:
            self.store.receipt(intent_id, {"status": "not_dispatched"})
            checkpoint["dispatch_started"] = False
            checkpoint["intent_id"] = None
            raise
        context = ExecutionContext(
            checkpoint["task_id"],
            step.id,
            checkpoint["attempts"][step.id],
            {dep: Observation(**checkpoint["results"][dep]) for dep in step.dependencies},
        )
        try:
            observation = self.store.policy.redactor.clean(
                _observation(self.executor(step, context))
            )
        except WorkbenchError as error:
            if error.code in {"APPROVAL_REQUIRED", "POLICY_DENIED", "STALE_APPROVAL", "STALE"}:
                self.store.receipt(intent_id, {"status": "rejected"})
                self._checkpoint(checkpoint, "execute", dispatch_started=False, intent_id=None)
                raise
            self.store.unknown(intent_id)
            raise WorkbenchError(
                "OUTCOME_UNKNOWN", "Executor failed without a known operation receipt"
            ) from None
        except BaseException:
            self.store.unknown(intent_id)
            raise
        checkpoint["results"][step.id] = observation
        # Evidence may shrink in later checkpoints; identity binds the original receipt.
        checkpoint["result_digests"][step.id] = canonical_hash(observation)
        if observation["unknown"]:
            self.store.unknown(intent_id)
            self._checkpoint(checkpoint, "observe")
            raise WorkbenchError("OUTCOME_UNKNOWN", "Operation reported an unknown outcome")
        if observation["success"] and step.effect != "read":
            checkpoint["completed_effects"][signature] = observation
            checkpoint["effect_result_digests"][signature] = checkpoint["result_digests"][step.id]
            if signature not in checkpoint["round_effects"]:
                checkpoint["round_effects"].append(signature)
        self._checkpoint(
            checkpoint,
            "observe",
            dispatch_started=False,
            intent_id=None,
            receipt_intent=intent_id,
            receipt={"status": "succeeded" if observation["success"] else "failed"},
        )
        self._guard(checkpoint, owner, lease)

    def _loop(
        self, checkpoint: dict[str, Any], instruction: str, owner: str, lease: WorkerLease
    ) -> None:
        while True:
            self._guard(checkpoint, owner, lease)
            phase = checkpoint["phase"]
            if phase == "plan":
                plan = self.planner(
                    PlanRequest(
                        checkpoint["task_id"],
                        instruction,
                        tuple(checkpoint["history"]),
                        checkpoint["plan_round"],
                    )
                )
                self._guard(checkpoint, owner, lease)
                self._accept_plan(checkpoint, plan)
            elif phase in {"execute", "observe"}:
                if checkpoint["dispatch_started"]:
                    raise WorkbenchError(
                        "OUTCOME_UNKNOWN", "Dispatch checkpoint lacks an observation"
                    )
                steps = [
                    Step(**{**item, "dependencies": tuple(item["dependencies"])})
                    for item in checkpoint["plan"]
                ]
                current = checkpoint["current_step"]
                observation = checkpoint["results"].get(current)
                if observation is not None and not observation["success"]:
                    step = next(item for item in steps if item.id == current)
                    signature = self._signature(step, checkpoint)
                    failure_id = (
                        f"{checkpoint['plan_round']}:{step.id}:{checkpoint['attempts'][step.id]}"
                    )
                    failures = checkpoint["failures"].get(signature, 0)
                    if failure_id not in checkpoint["counted_failures"]:
                        failures += 1
                        checkpoint["counted_failures"].append(failure_id)
                    checkpoint["failures"][signature] = failures
                    self._checkpoint(checkpoint, "observe")
                    if failures >= self.limits.repeated_failure_limit:
                        raise WorkbenchError(
                            "REPEATED_FAILURE", "Repeated unsuccessful action stopped"
                        )
                    if (
                        observation["retryable"]
                        and step.effect == "read"
                        and step.replay_safe
                        and step.action in self.replay_safe_actions
                        and checkpoint["attempts"][step.id] < self.limits.max_attempts
                    ):
                        del checkpoint["results"][step.id]
                        del checkpoint["result_digests"][step.id]
                        self._dispatch(checkpoint, step, owner, lease)
                    else:
                        self._reflect(checkpoint, "step_failed")
                    continue
                completed = {
                    identifier
                    for identifier, value in checkpoint["results"].items()
                    if value["success"]
                }
                ready = next(
                    (
                        step
                        for step in steps
                        if step.id not in completed and set(step.dependencies) <= completed
                    ),
                    None,
                )
                if ready is not None:
                    self._dispatch(checkpoint, ready, owner, lease)
                else:
                    self._checkpoint(checkpoint, "verify", current_step=None)
            elif phase == "verify":
                verification = self.store.policy.redactor.clean(
                    _verification(
                        self.verifier(
                            VerificationRequest(
                                checkpoint["task_id"],
                                instruction,
                                {
                                    identifier: Observation(**value)
                                    for identifier, value in checkpoint["results"].items()
                                },
                                tuple(checkpoint["history"]),
                            )
                        )
                    )
                )
                self._checkpoint(checkpoint, "verify", verification=verification)
                self._guard(checkpoint, owner, lease)
                if verification["success"]:
                    return
                self._reflect(checkpoint, "verification_failed")
            elif phase == "reflect":
                if checkpoint["plan_round"] >= self.limits.max_replans:
                    raise WorkbenchError("REPLAN_EXHAUSTED", "Execution replan budget is exhausted")
                self._checkpoint(checkpoint, "plan", plan_round=checkpoint["plan_round"] + 1)
            elif (
                phase == "complete"
                and isinstance(checkpoint["verification"], dict)
                and checkpoint["verification"].get("success") is True
            ):
                return
            else:
                raise WorkbenchError("STATE_ERROR", "Invalid durable execution phase")

    def execute(self, instruction: str, *, task_id: str | None = None) -> dict[str, Any]:
        if task_id is None:
            task_id = self.store.create_task("harness", instruction, self.pins)
            started = self.clock()
            self.store.save(
                "execution",
                task_id,
                {
                    "version": 1,
                    "task_id": task_id,
                    "state": "pending",
                    "phase": "plan",
                    "plan": [],
                    "plan_round": 0,
                    "steps": 0,
                    "results": {},
                    "result_digests": {},
                    "history": [],
                    "attempts": {},
                    "failures": {},
                    "counted_failures": [],
                    "completed_effects": {},
                    "effect_result_digests": {},
                    "round_effects": [],
                    "previous_effects": [],
                    "started_at": started,
                    "deadline_at": started + self.limits.deadline_seconds,
                    "sequence": 0,
                    "current_step": None,
                    "intent_id": None,
                    "dispatch_started": False,
                    "verification": None,
                },
            )
        task = self._task(task_id)
        if task["state"] == "succeeded":
            # A completed execution reports its stored result under any contract; other host
            # pin drift still conflicts below.
            pins = task["pins"] if isinstance(task["pins"], dict) else {}
            if {**pins, "execution_contract": None} == {
                **self.pins,
                "execution_contract": None,
            } and task["instruction"] == self.store.policy.redactor.clean(instruction):
                return task["result"]  # type: ignore[no-any-return]
        stored = task["pins"].get("execution_contract") if isinstance(task["pins"], dict) else None
        if stored != EXECUTION_CONTRACT:
            raise WorkbenchError(
                "CONFLICT",
                f"Checkpoint uses execution contract {stored}; this version resumes only contract "
                f"{EXECUTION_CONTRACT}, so completed effects cannot replay. Inspect it with trace, "
                "then cancel it and start a new execution.",
            )
        if (
            task["instruction"] != self.store.policy.redactor.clean(instruction)
            or task["pins"] != self.pins
        ):
            raise WorkbenchError("CONFLICT", "Execution instruction or host contract pins changed")
        if task["state"] == "succeeded":
            return task["result"]  # type: ignore[no-any-return]
        checkpoint = self.store.load("execution", task_id)
        for name, observations in (
            ("result_digests", checkpoint["results"]),
            ("effect_result_digests", checkpoint["completed_effects"]),
        ):
            digests = checkpoint.get(name)
            if (
                not isinstance(digests, dict)
                or digests.keys() != observations.keys()
                or any(
                    not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)
                    for value in digests.values()
                )
            ):
                raise WorkbenchError(
                    "CONFLICT", "Execution result identity is unavailable; inspect its trace"
                )
        if task["state"] in {"failed", "interrupted", "awaiting_approval"}:
            self.store.resume(task_id, self.pins)
        owner = uuid.uuid4().hex
        if not self.store.claim(task_id, owner):
            raise WorkbenchError("CONFLICT", "Execution is already owned or cancelled")
        checkpoint = self.store.load("execution", task_id)
        checkpoint["owner"] = owner
        lease = WorkerLease(self.store, task_id, owner)
        lease.start()
        try:
            self._checkpoint(checkpoint, checkpoint["phase"], state="running")
            self._loop(checkpoint, task["instruction"], owner, lease)
            self._guard(checkpoint, owner, lease)
            self._checkpoint(checkpoint, "complete", state="succeeded")
            output = {**self.status(task_id), "state": "succeeded", "error": None}
            self.store.transition(task_id, "running", "succeeded", result=output)
            return output
        except WorkbenchError as error:
            state = self._task(task_id)["state"]
            if state == "running":
                target = (
                    "awaiting_approval"
                    if error.code in {"APPROVAL_REQUIRED", "STALE_APPROVAL"}
                    else "failed"
                )
                try:
                    self._checkpoint(checkpoint, checkpoint["phase"], state=target)
                except WorkbenchError as checkpoint_error:
                    self.store.event(
                        task_id, "harness.checkpoint_failed", {"error_code": checkpoint_error.code}
                    )
                self.store.transition(task_id, "running", target, error=error.to_dict())
            if error.code in {"APPROVAL_REQUIRED", "STALE_APPROVAL", "CANCELLED"}:
                return self.status(task_id)
            raise
        except BaseException:
            if self._task(task_id)["state"] == "running":
                try:
                    self._checkpoint(checkpoint, checkpoint["phase"], state="interrupted")
                except WorkbenchError as checkpoint_error:
                    self.store.event(
                        task_id, "harness.checkpoint_failed", {"error_code": checkpoint_error.code}
                    )
                self.store.transition(
                    task_id,
                    "running",
                    "interrupted",
                    error={"code": "INTERRUPTED", "message": "Execution stopped before completion"},
                )
            raise
        finally:
            lease.close()
