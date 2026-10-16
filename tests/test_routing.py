from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest

from agentic_workbench.agents import Budget, Intents
from agentic_workbench.config import Config
from agentic_workbench.errors import WorkbenchError
from agentic_workbench.models import Usage
from agentic_workbench.policy import WorkspacePolicy
from agentic_workbench.providers import ProviderRejected, ProviderResult
from agentic_workbench.routing import ModelRegistry, ModelSpec, RoutedProvider, RoutingLimits
from agentic_workbench.state import StateStore

ANALYSIS = {
    "summary": "Fixture review",
    "findings": [],
    "recommendations": [],
    "candidate_edits": [],
    "limitations": ["Local fixture"],
}


class Executor:
    schemas: list[dict[str, Any]] = []

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError("No tool call expected")


class Adapter:
    def __init__(self, error: str | None = None, usage: Usage | None = None) -> None:
        self.error = error
        self.usage = usage or Usage(requests=1, input_tokens=10, output_tokens=5)
        self.calls = 0

    def analyze(
        self,
        request: str,
        context: dict[str, Any],
        *,
        executor: Any,
        budget: Any,
        intents: Any,
    ) -> ProviderResult:
        self.calls += 1
        budget.reserve(8)
        intent = intents.intent("fixture.request", {"model": "fixture"})
        if self.error == "rejected":
            intents.receipt(intent, {"status": "rejected", "http_status": 400})
            raise ProviderRejected("Fixture rejected")
        if self.error == "contradictory":
            intents.receipt(intent, {"status": "received", **asdict(self.usage)})
            raise ProviderRejected("Receipt says received, not rejected")
        if self.error:
            if self.error == "OUTCOME_UNKNOWN":
                intents.unknown(intent)
            else:
                intents.receipt(intent, {"status": "invalid_response"})
            raise WorkbenchError(self.error, "Fixture failure")
        intents.receipt(intent, {"status": "received", **asdict(self.usage)})
        return ProviderResult(ANALYSIS, self.usage)


def spec(name: str, **overrides: Any) -> ModelSpec:
    return ModelSpec(
        name=name,
        capabilities=("analysis", "tools"),
        max_input_tokens=100,
        max_output_tokens=50,
        max_requests=1,
        input_price_per_million_usd=2.0,
        output_price_per_million_usd=4.0,
        **overrides,
    )


def runtime(root: Path) -> tuple[StateStore, str]:
    store = StateStore(WorkspacePolicy(root, Config()))
    task_id = store.create_task("reviewer", "Review", {})
    return store, task_id


def invoke(router: RoutedProvider, store: StateStore, task: str) -> ProviderResult:
    return router.analyze(
        "Review", {}, executor=Executor(), budget=Budget(store, task), intents=Intents(store, task)
    )


def test_capability_selection_cost_latency_and_durable_usage(tmp_path: Path) -> None:
    registry = ModelRegistry()
    unsupported, selected = Adapter(), Adapter()
    registry.register(ModelSpec("text", ("analysis",), 100, 50), unsupported)
    registry.register(spec("code"), selected)
    router = RoutedProvider(registry, ("text", "code"), required_capabilities=("tools",))
    with runtime(tmp_path)[0] as store:
        task = store.create_task("reviewer", "Review", {})
        result = invoke(router, store, task)
        assert unsupported.calls == 0 and selected.calls == 1
        assert result.usage.estimated_cost_usd == pytest.approx(0.00004)
        assert store.resource_usage(task)["tokens"] == 15
        assert store.resource_usage(task)["cost_microusd"] == 40
        assert any(event["name"] == "model.completed" for event in store.export()["events"])
    with StateStore(WorkspacePolicy(tmp_path, Config())) as reopened:
        assert reopened.resource_usage(task)["tokens"] == 15


def test_known_rejection_fallback_records_attempts(tmp_path: Path) -> None:
    registry = ModelRegistry()
    first, second = Adapter("rejected"), Adapter()
    registry.register(spec("first"), first)
    registry.register(spec("second"), second)
    store, task = runtime(tmp_path)
    with store:
        result = invoke(RoutedProvider(registry, ("first", "second")), store, task)
        assert first.calls == second.calls == 1
        assert result.usage.requests == 2
        assert store.resource_usage(task)["tokens"] == 15
        assert all(intent["state"] == "received" for intent in store.export()["intents"])


@pytest.mark.parametrize(
    "code", ["OUTCOME_UNKNOWN", "POLICY_DENIED", "PROVIDER_INVALID_RESPONSE", "LIMIT_EXCEEDED"]
)
def test_errors_never_authorize_fallback(tmp_path: Path, code: str) -> None:
    registry = ModelRegistry()
    first, second = Adapter(code), Adapter()
    registry.register(spec("first"), first)
    registry.register(spec("second"), second)
    store, task = runtime(tmp_path)
    with store:
        with pytest.raises(WorkbenchError, match=code):
            invoke(RoutedProvider(registry, ("first", "second")), store, task)
        assert second.calls == 0
        if code == "OUTCOME_UNKNOWN":
            assert store.resource_usage(task)["tokens"] == 150
            with pytest.raises(WorkbenchError, match="OUTCOME_UNKNOWN"):
                invoke(RoutedProvider(registry, ("second",)), store, task)
            assert second.calls == 0


def test_rejection_contradicting_its_receipt_never_falls_back(tmp_path: Path) -> None:
    registry = ModelRegistry()
    first, second = Adapter("contradictory"), Adapter()
    registry.register(spec("first"), first)
    registry.register(spec("second"), second)
    store, task = runtime(tmp_path)
    with store:
        with pytest.raises(WorkbenchError, match="PROVIDER_INVALID_RESPONSE"):
            invoke(RoutedProvider(registry, ("first", "second")), store, task)
        assert first.calls == 1 and second.calls == 0
        assert store.resource_usage(task)["tokens"] == 15


def test_rejection_of_an_earlier_request_cannot_override_the_latest_received_request(
    tmp_path: Path,
) -> None:
    class OutOfOrder(Adapter):
        def analyze(self, request: str, context: dict[str, Any], **options: Any) -> ProviderResult:
            self.calls += 1
            options["budget"].reserve(8)
            earlier = options["intents"].intent("fixture.request", {"model": "fixture"})
            options["budget"].reserve(8)
            latest = options["intents"].intent("fixture.request", {"model": "fixture"})
            options["intents"].receipt(latest, {"status": "received", **asdict(self.usage)})
            options["intents"].receipt(earlier, {"status": "rejected", "http_status": 400})
            raise ProviderRejected("Earlier request rejected after the latest succeeded")

    registry = ModelRegistry()
    first, second = OutOfOrder(), Adapter()
    registry.register(
        ModelSpec("first", max_input_tokens=100, max_output_tokens=50, max_requests=2), first
    )
    registry.register(spec("second"), second)
    store, task = runtime(tmp_path)
    with store:
        router = RoutedProvider(
            registry, ("first", "second"), limits=RoutingLimits(maximum_cost_usd=None)
        )
        with pytest.raises(WorkbenchError, match="PROVIDER_INVALID_RESPONSE"):
            invoke(router, store, task)
        assert first.calls == 1 and second.calls == 0
        assert store.resource_usage(task)["tokens"] == 15


def test_atomic_resource_budget_across_connections_and_restart(tmp_path: Path) -> None:
    store, task = runtime(tmp_path)
    other = StateStore(store.policy)

    def reserve(candidate: StateStore) -> str:
        try:
            return candidate.reserve_resources(task, 75, 40, 100, 100)
        except WorkbenchError as error:
            return error.code

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(reserve, (store, other)))
        assert outcomes.count("LIMIT_EXCEEDED") == 1
        assert store.resource_usage(task)["tokens"] == 75
    finally:
        store.close()
        other.close()
    with StateStore(WorkspacePolicy(tmp_path, Config())) as reopened:
        assert reopened.resource_usage(task)["tokens"] == 75
        with pytest.raises(WorkbenchError, match="LIMIT_EXCEEDED"):
            reopened.reserve_resources(task, 75, 40, 100, 100)


def test_budget_admission_precedes_model_dispatch(tmp_path: Path) -> None:
    registry = ModelRegistry()
    adapter = Adapter()
    registry.register(spec("code"), adapter)
    router = RoutedProvider(registry, ("code",), limits=RoutingLimits(maximum_tokens=149))
    store, task = runtime(tmp_path)
    with store:
        with pytest.raises(WorkbenchError, match="LIMIT_EXCEEDED"):
            invoke(router, store, task)
        assert adapter.calls == 0 and not store.export()["intents"]


def test_unknown_usage_retains_conservative_estimate(tmp_path: Path) -> None:
    registry = ModelRegistry()
    registry.register(spec("code"), Adapter(usage=Usage(requests=1)))
    store, task = runtime(tmp_path)
    with store:
        result = invoke(RoutedProvider(registry, ("code",)), store, task)
        assert result.usage.estimated_cost_usd is None
        assert store.resource_usage(task)["tokens"] == 150
        assert store.resource_usage(task)["cost_microusd"] == 400


def test_unregistered_and_invalid_model_descriptors_fail_closed() -> None:
    registry = ModelRegistry()
    with pytest.raises(WorkbenchError, match="registered"):
        RoutedProvider(registry, ("missing",))
    with pytest.raises(WorkbenchError, match="CONFIG_ERROR"):
        registry.register(spec("code", model="sk-secret"), Adapter())
    registry.register(spec("code"), Adapter())
    with pytest.raises(WorkbenchError, match="duplicate"):
        registry.register(spec("code"), Adapter())


def test_missing_prices_require_explicit_unbounded_cost_limit(tmp_path: Path) -> None:
    registry = ModelRegistry()
    adapter = Adapter()
    registry.register(ModelSpec("unpriced", max_input_tokens=100, max_output_tokens=50), adapter)
    store, task = runtime(tmp_path)
    with store:
        with pytest.raises(WorkbenchError, match="configured model prices"):
            invoke(RoutedProvider(registry, ("unpriced",)), store, task)
        assert adapter.calls == 0
        result = invoke(
            RoutedProvider(registry, ("unpriced",), limits=RoutingLimits(maximum_cost_usd=None)),
            store,
            task,
        )
        assert result.usage.estimated_cost_usd is None
        assert store.resource_usage(task)["cost_known"] is False


def test_cost_admission_precedes_model_dispatch(tmp_path: Path) -> None:
    registry = ModelRegistry()
    adapter = Adapter()
    registry.register(spec("priced"), adapter)
    store, task = runtime(tmp_path)
    with store:
        router = RoutedProvider(
            registry, ("priced",), limits=RoutingLimits(maximum_cost_usd=0.0001)
        )
        with pytest.raises(WorkbenchError, match="LIMIT_EXCEEDED"):
            invoke(router, store, task)
        assert adapter.calls == 0


def test_usage_exceeding_model_contract_blocks_further_dispatch(tmp_path: Path) -> None:
    registry = ModelRegistry()
    adapter = Adapter(usage=Usage(requests=1, input_tokens=101, output_tokens=1))
    registry.register(spec("priced"), adapter)
    store, task = runtime(tmp_path)
    with store:
        router = RoutedProvider(registry, ("priced",))
        with pytest.raises(WorkbenchError, match="registered token bounds"):
            invoke(router, store, task)
        with pytest.raises(WorkbenchError, match="OUTCOME_UNKNOWN"):
            invoke(router, store, task)
        assert adapter.calls == 1


def test_idempotency_claims_are_atomic_and_preserve_unknown_restart(tmp_path: Path) -> None:
    store, _ = runtime(tmp_path)
    other = StateStore(store.policy)
    fingerprint = "a" * 64
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(
                pool.map(
                    lambda candidate: candidate.begin_operation(
                        "tool-operation", "key", fingerprint
                    ),
                    (store, other),
                )
            )
        assert outcomes.count(None) == 1
        assert next(value for value in outcomes if value is not None)["state"] == "pending"
        store.mark_operation_unknown("tool-operation", "key", fingerprint)
        with pytest.raises(WorkbenchError, match="CONFLICT"):
            store.begin_operation("tool-operation", "key", "b" * 64)
    finally:
        store.close()
        other.close()
    with StateStore(WorkspacePolicy(tmp_path, Config())) as reopened:
        assert reopened.begin_operation("tool-operation", "key", fingerprint)["state"] == "unknown"


def test_execution_checkpoint_and_receipt_commit_atomically_with_ownership(tmp_path: Path) -> None:
    store, task = runtime(tmp_path)
    with store:
        assert store.claim(task, "worker")
        intent = store.intent(task, "harness-step")
        value = {"task_id": task, "state": "running", "results": {"step": {"success": True}}}
        with pytest.raises(WorkbenchError, match="CONFLICT"):
            store.execution_checkpoint(task, "other-worker", value, intent, {"status": "received"})
        assert store.load("execution", task) is None
        store.execution_checkpoint(task, "worker", value, intent, {"status": "received"})
        assert store.load("execution", task) == value
        assert store.export()["intents"][0]["state"] == "received"
        store.transition(task, "running", "awaiting_approval")
        assert store.resume(task, {})["state"] == "pending"


def test_checkpoint_receipt_rolls_back_when_checkpoint_is_invalid(tmp_path: Path) -> None:
    store, task = runtime(tmp_path)
    with store:
        assert store.claim(task, "worker")
        intent = store.intent(task, "harness-step")
        with pytest.raises(WorkbenchError, match="LIMIT_EXCEEDED"):
            store.execution_checkpoint(
                task,
                "worker",
                {"task_id": task, "oversized": "x" * 1_048_576},
                intent,
                {"status": "received"},
            )
        assert store.load("execution", task) is None
        assert store.export()["intents"][0]["state"] == "pending"


def test_prune_retains_resources_and_checkpoint_for_retained_task_tree(tmp_path: Path) -> None:
    store, task = runtime(tmp_path)
    with store:
        reservation = store.reserve_resources(task, 100, 100, 1000, 1000)
        store.settle_resources(reservation, 10, 10)
        store.reserve_tool_call(task)
        store.save("execution", task, {"task_id": task, "state": "failed"})
        with closing(sqlite3.connect(store.path)) as connection, connection:
            connection.execute("UPDATE records SET updated_at = '2000-01-01T00:00:00+00:00'")
        assert store.review_prune(30)["records"] == []


def test_prune_uses_authoritative_cancelled_task_state(tmp_path: Path) -> None:
    store, task = runtime(tmp_path)
    with store:
        assert store.claim(task, "worker")
        store.save("execution", task, {"task_id": task, "state": "awaiting_approval"})
        store.transition(task, "running", "awaiting_approval")
        store.cancel_tree(task)
        with closing(sqlite3.connect(store.path)) as connection, connection:
            connection.execute("UPDATE records SET updated_at = '2000-01-01T00:00:00+00:00'")
            connection.execute("UPDATE tasks SET updated_at = '2000-01-01T00:00:00+00:00'")
        reviewed = store.review_prune(30)
        assert reviewed["tasks"] == [task]
        assert any(row["kind"] == "execution" for row in reviewed["records"])
        store.begin_operation("tool-operation", "unknown", "a" * 64)
        store.mark_operation_unknown("tool-operation", "unknown", "a" * 64)
        with closing(sqlite3.connect(store.path)) as connection, connection:
            connection.execute("UPDATE records SET updated_at = '2000-01-01T00:00:00+00:00'")
        assert not any(row["kind"] == "tool-operation" for row in store.review_prune(30)["records"])


def test_cancellation_scope_trace_and_dispatch_budgets(tmp_path: Path) -> None:
    store, root = runtime(tmp_path)
    with store:
        child = store.create_task("reviewer", "Child", {}, parent_id=root)
        other = store.create_task("reviewer", "Other", {})
        assert set(store.cancel_tree(root)) == {root, child}
        assert store.get_task(other)["state"] == "pending"
        assert {event["task_id"] for event in store.task_events(root)} == {root, child}
        assert len(store.task_events(root, limit=1)) == 1
        with pytest.raises(WorkbenchError, match="CANCELLED"):
            store.reserve(root, 8)
        with pytest.raises(WorkbenchError, match="CANCELLED"):
            store.reserve_resources(root, 1, 1, 100, 100)
        with pytest.raises(WorkbenchError, match="CANCELLED"):
            store.reserve_tool_call(root)


def test_root_cannot_complete_with_unknown_descendant_effect(tmp_path: Path) -> None:
    store, root = runtime(tmp_path)
    with store:
        assert store.claim(root, "worker")
        child = store.create_task("reviewer", "Child", {}, parent_id=root)
        intent = store.intent(child, "fixture.request")
        store.unknown(intent)
        with pytest.raises(WorkbenchError, match="OUTCOME_UNKNOWN"):
            store.transition(root, "running", "succeeded")


def test_cancelled_child_cannot_dispatch_another_model_round(tmp_path: Path) -> None:
    store, root = runtime(tmp_path)
    with store:
        child = store.create_task("reviewer", "Child", {}, parent_id=root)

        class CancellingAdapter(Adapter):
            def analyze(
                self, request: str, context: dict[str, Any], **kwargs: Any
            ) -> ProviderResult:
                result = super().analyze(request, context, **kwargs)
                store.cancel_tree(child)
                kwargs["budget"].reserve(8)
                return result

        registry = ModelRegistry()
        registry.register(
            ModelSpec(
                "code",
                max_input_tokens=100,
                max_output_tokens=50,
                max_requests=2,
                input_price_per_million_usd=0,
                output_price_per_million_usd=0,
            ),
            CancellingAdapter(),
        )
        with pytest.raises(WorkbenchError, match="CANCELLED"):
            RoutedProvider(registry, ("code",)).analyze(
                "Review",
                {},
                executor=Executor(),
                budget=Budget(store, root),
                intents=Intents(store, child),
            )
        assert store.get_task(root)["state"] == "pending"
        assert store.export()["budgets"][0]["reserved"] == 1


def test_cancel_before_the_route_intent_releases_its_reservation(tmp_path: Path) -> None:
    registry = ModelRegistry()
    adapter = Adapter()
    registry.register(spec("first"), adapter)
    store, task = runtime(tmp_path)
    with store:

        class CancellingIntents(Intents):
            def intent(self, kind: str, metadata: dict[str, Any]) -> str:
                store.cancel_tree(task)
                return super().intent(kind, metadata)

        with pytest.raises(WorkbenchError, match="CANCELLED"):
            RoutedProvider(registry, ("first",)).analyze(
                "Review",
                {},
                executor=Executor(),
                budget=Budget(store, task),
                intents=CancellingIntents(store, task),
            )
        assert adapter.calls == 0
        usage = store.resource_usage(task)
        assert usage is not None and usage["tokens"] == 0
        assert {r["value"]["state"] for r in store.list_records("resource-reservation")} == {
            "settled"
        }


def test_rejection_without_a_receipt_never_falls_back(tmp_path: Path) -> None:
    class Silent(Adapter):
        def analyze(self, request: str, context: dict[str, Any], **_: Any) -> ProviderResult:
            self.calls += 1
            raise ProviderRejected("Rejected without recording evidence")

    registry = ModelRegistry()
    first, second = Silent(), Adapter()
    registry.register(spec("first"), first)
    registry.register(spec("second"), second)
    store, task = runtime(tmp_path)
    with store:
        with pytest.raises(WorkbenchError, match="PROVIDER_INVALID_RESPONSE"):
            invoke(RoutedProvider(registry, ("first", "second")), store, task)
        assert first.calls == 1 and second.calls == 0


def test_a_failed_dispatch_event_closes_the_route_intent(tmp_path: Path, monkeypatch) -> None:
    registry = ModelRegistry()
    adapter = Adapter()
    registry.register(spec("first"), adapter)
    store, task = runtime(tmp_path)
    with store:
        original = store.event

        def failing_event(task_id: str, name: str, metadata: dict[str, Any]) -> int:
            if name == "provider.dispatch":
                raise WorkbenchError("STATE_ERROR", "Injected state failure")
            return original(task_id, name, metadata)

        monkeypatch.setattr(store, "event", failing_event)
        with pytest.raises(WorkbenchError, match="STATE_ERROR"):
            invoke(RoutedProvider(registry, ("first",)), store, task)
        assert adapter.calls == 0
        assert {intent["state"] for intent in store.export()["intents"]} == {"received"}
        usage = store.resource_usage(task)
        assert usage is not None and usage["tokens"] == 0


def test_routing_keeps_its_own_copy_of_each_receipt(tmp_path: Path) -> None:
    class Mutating(Adapter):
        def analyze(self, request: str, context: dict[str, Any], **options: Any) -> ProviderResult:
            self.calls += 1
            options["budget"].reserve(8)
            intent = options["intents"].intent("fixture.request", {"model": "fixture"})
            receipt = {"status": "received", **asdict(self.usage)}
            options["intents"].receipt(intent, receipt)
            receipt["status"] = "rejected"
            raise ProviderRejected("Receipt dict flipped after recording")

    registry = ModelRegistry()
    first, second = Mutating(), Adapter()
    registry.register(spec("first"), first)
    registry.register(spec("second"), second)
    store, task = runtime(tmp_path)
    with store:
        with pytest.raises(WorkbenchError, match="PROVIDER_INVALID_RESPONSE"):
            invoke(RoutedProvider(registry, ("first", "second")), store, task)
        assert second.calls == 0
