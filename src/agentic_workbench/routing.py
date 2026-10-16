"""Trusted model registrations, capability routing and durable resource admission."""

from __future__ import annotations

import math
import re
import threading
import time
from copy import deepcopy
from dataclasses import asdict, dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import Any

from .errors import WorkbenchError
from .models import Usage, canonical_hash, canonical_json, schema
from .policy import WorkspacePolicy
from .providers import (
    BudgetLedger,
    IntentSink,
    Provider,
    ProviderRejected,
    ProviderResult,
    ToolExecutor,
)
from .state import StateStore


def _names(names: tuple[str, ...]) -> bool:
    return (
        isinstance(names, tuple)
        and 1 <= len(names) <= 64
        and all(
            isinstance(name, str) and re.fullmatch(r"[a-z][a-z0-9_.-]{0,63}", name)
            for name in names
        )
        and len(set(names)) == len(names)
    )


@dataclass(frozen=True)
class ModelSpec:
    """Host-declared adapter limits and supplied prices; no provider discovery or imports."""

    name: str
    capabilities: tuple[str, ...] = ("analysis",)
    max_input_tokens: int = 16_000
    max_output_tokens: int = 2_000
    max_requests: int = 1
    input_price_per_million_usd: float | None = None
    output_price_per_million_usd: float | None = None
    model: str | None = None

    def __post_init__(self) -> None:
        if not _names((self.name,)) or not _names(self.capabilities):
            raise WorkbenchError("CONFIG_ERROR", "Invalid model name or capabilities")
        if any(
            type(value) is not int or not 1 <= value <= maximum
            for value, maximum in (
                (self.max_input_tokens, 1_048_576),
                (self.max_output_tokens, 65_536),
                (self.max_requests, 128),
            )
        ):
            raise WorkbenchError("CONFIG_ERROR", "Invalid model resource bounds")
        prices = self.input_price_per_million_usd, self.output_price_per_million_usd
        if (prices[0] is None) != (prices[1] is None) or any(
            type(price) not in (int, float)
            or not math.isfinite(price)
            or not 0 <= price <= 1_000_000
            for price in prices
            if price is not None
        ):
            raise WorkbenchError("CONFIG_ERROR", "Invalid configured model prices")
        if self.model is not None and (
            not isinstance(self.model, str)
            or not 1 <= len(self.model) <= 200
            or self.model.startswith("sk-")
            or re.fullmatch(r"[A-Za-z0-9_.:/-]+", self.model) is None
        ):
            raise WorkbenchError("CONFIG_ERROR", "Invalid model identifier")

    def cost_microusd(self, input_tokens: int, output_tokens: int) -> int | None:
        if self.input_price_per_million_usd is None or self.output_price_per_million_usd is None:
            return None
        # USD per million tokens equals micro-USD per token; round reservations upward.
        return int(
            (
                Decimal(input_tokens) * Decimal(str(self.input_price_per_million_usd))
                + Decimal(output_tokens) * Decimal(str(self.output_price_per_million_usd))
            ).to_integral_value(rounding=ROUND_CEILING)
        )


@dataclass(frozen=True)
class RoutingLimits:
    maximum_tokens: int = 1_000_000
    maximum_cost_usd: float | None = 10.0

    def __post_init__(self) -> None:
        if type(self.maximum_tokens) is not int or not 1 <= self.maximum_tokens <= 2**63 - 1:
            raise WorkbenchError("CONFIG_ERROR", "Invalid root token limit")
        if self.maximum_cost_usd is not None and (
            type(self.maximum_cost_usd) not in (int, float)
            or not math.isfinite(self.maximum_cost_usd)
            or not 0 <= self.maximum_cost_usd <= 1_000_000_000
        ):
            raise WorkbenchError("CONFIG_ERROR", "Invalid root cost limit")

    @property
    def maximum_cost_microusd(self) -> int | None:
        if self.maximum_cost_usd is None:
            return None
        return int(
            (Decimal(str(self.maximum_cost_usd)) * 1_000_000).to_integral_value(
                rounding=ROUND_FLOOR
            )
        )


class ModelRegistry:
    """Explicit trusted Python adapters are alternatives to the built-in OpenAI adapter."""

    def __init__(self) -> None:
        self._models: dict[str, tuple[ModelSpec, Provider]] = {}

    def register(self, spec: ModelSpec, provider: Provider) -> None:
        if (
            not isinstance(spec, ModelSpec)
            or spec.name in self._models
            or len(self._models) >= 64
            or not isinstance(provider, Provider)
        ):
            raise WorkbenchError("CONFIG_ERROR", "Invalid or duplicate model registration")
        self._models[spec.name] = spec, provider

    def get(self, name: str) -> tuple[ModelSpec, Provider]:
        if name not in self._models:
            raise WorkbenchError("INTEGRATION_UNAVAILABLE", "Model is not registered by the host")
        return self._models[name]

    def describe(self) -> list[dict[str, Any]]:
        return [asdict(spec) for spec, _ in self._models.values()]

    @property
    def fingerprint(self) -> str:
        return canonical_hash(
            [
                {
                    "spec": asdict(spec),
                    "adapter": f"{type(provider).__module__}.{type(provider).__qualname__}",
                    "pin": getattr(provider, "fingerprint", None),
                }
                for spec, provider in self._models.values()
            ]
        )


class _RequestAllowance:
    def __init__(self, budget: BudgetLedger, maximum: int, store: StateStore, task_id: str) -> None:
        self.budget, self.maximum, self.count = budget, maximum, 0
        self.store, self.task_id = store, task_id
        self._lock = threading.Lock()

    def reserve(self, maximum: int) -> None:
        with self._lock:
            if self.store.cancelled(self.task_id):
                raise WorkbenchError("CANCELLED", "Model task was cancelled")
            if self.count >= self.maximum:
                raise WorkbenchError("LIMIT_EXCEEDED", "Registered model request limit exhausted")
            self.budget.reserve(maximum)
            self.count += 1


class _Receipts:
    def __init__(self, sink: IntentSink) -> None:
        self.sink = sink
        self.pending: set[str] = set()
        self.unknown_ids: set[str] = set()
        self.receipts: list[dict[str, Any]] = []
        self.latest_intent: str | None = None
        self.latest_receipt: str | None = None

    def intent(self, kind: str, metadata: dict[str, Any]) -> str:
        identifier = self.sink.intent(kind, metadata)
        self.pending.add(identifier)
        self.latest_intent = identifier
        return identifier

    def receipt(self, intent_id: str, metadata: dict[str, Any]) -> None:
        self.sink.receipt(intent_id, metadata)
        self.pending.discard(intent_id)
        self.unknown_ids.discard(intent_id)
        # A copy: the adapter may reuse or mutate its dict after recording it.
        self.receipts.append(deepcopy(metadata))
        self.latest_receipt = intent_id

    def unknown(self, intent_id: str) -> None:
        self.sink.unknown(intent_id)
        self.unknown_ids.add(intent_id)

    def tokens(self) -> tuple[int | None, int | None]:
        incoming = outgoing = 0
        for receipt in self.receipts:
            if receipt.get("status") in {"rejected", "rate_limited"}:
                continue
            values = receipt.get("input_tokens"), receipt.get("output_tokens")
            if any(type(value) is not int or value < 0 for value in values):
                return None, None
            assert isinstance(values[0], int) and isinstance(values[1], int)
            incoming += values[0]
            outgoing += values[1]
        return incoming, outgoing


class RoutedProvider:
    """Provider-compatible host routing; fallback is allowed only after known rejection."""

    def __init__(
        self,
        registry: ModelRegistry,
        preference: tuple[str, ...],
        *,
        required_capabilities: tuple[str, ...] = ("analysis",),
        limits: RoutingLimits | None = None,
    ) -> None:
        if not _names(preference) or not _names(required_capabilities):
            raise WorkbenchError("CONFIG_ERROR", "Invalid model routing configuration")
        self.registry, self.preference = registry, preference
        self.required_capabilities = required_capabilities
        self.limits = limits or RoutingLimits()
        for name in preference:
            registry.get(name)

    @property
    def fingerprint(self) -> str:
        return canonical_hash(
            {
                "registry": self.registry.fingerprint,
                "preference": self.preference,
                "required_capabilities": self.required_capabilities,
                "limits": asdict(self.limits),
            }
        )

    def _candidates(self) -> list[tuple[ModelSpec, Provider]]:
        candidates = [self.registry.get(name) for name in self.preference]
        selected = [
            candidate
            for candidate in candidates
            if set(self.required_capabilities) <= set(candidate[0].capabilities)
        ]
        if not selected:
            raise WorkbenchError(
                "INTEGRATION_UNAVAILABLE", "No registered model meets required capabilities"
            )
        return selected

    def context_size(self, request: str, context: dict[str, Any], *, executor: ToolExecutor) -> int:
        """Choose context that fits each configured eligible fallback's initial envelope."""
        sizes = []
        for _, provider in self._candidates():
            measure = getattr(provider, "context_size", None)
            if callable(measure):
                size = measure(request, context, executor=executor)
                if type(size) is not int or size < 0:
                    raise WorkbenchError("CONFIG_ERROR", "Adapter context measurement is invalid")
            else:
                # shortcut: unknown envelopes use JSON estimates; add context_size for exact sizing.
                output_schema = schema("ModelAnalysis")
                output_schema["$defs"] = {
                    name: output_schema["$defs"][name]
                    for name in ("Evidence", "Finding", "CandidateEdit")
                }
                size = len(
                    canonical_json(
                        {
                            "request": request,
                            "context": context,
                            "tools": executor.schemas,
                            "output_schema": output_schema,
                        }
                    ).encode()
                )
            sizes.append(size)
        return max(sizes)

    def analyze(
        self,
        request: str,
        context: dict[str, Any],
        *,
        executor: ToolExecutor,
        budget: BudgetLedger,
        intents: IntentSink,
    ) -> ProviderResult:
        if not isinstance(request, str) or not request.strip() or not isinstance(context, dict):
            raise WorkbenchError(
                "VALIDATION_ERROR", "Routing requires a request and object context"
            )
        store, root_id, task_id = (
            getattr(budget, "store", None),
            getattr(budget, "root_id", None),
            getattr(intents, "task_id", None),
        )
        if (
            not isinstance(store, StateStore)
            or not isinstance(root_id, str)
            or not isinstance(task_id, str)
        ):
            raise WorkbenchError(
                "CONFIG_ERROR", "Routing requires durable host budget and intent sinks"
            )
        task = store.get_task(task_id)
        if store.cancelled(task_id):
            raise WorkbenchError("CANCELLED", "Model task was cancelled")
        if task["root_id"] != root_id:
            raise WorkbenchError("CONFLICT", "Model budget and task roots differ")
        candidates = self._candidates()
        total_requests = 0
        total_in: int | None = 0
        total_out: int | None = 0
        total_cost: int | None = 0
        last_rejection: ProviderRejected | None = None
        for spec, provider in candidates:
            if store.cancelled(task_id):
                raise WorkbenchError("CANCELLED", "Model task was cancelled")
            attached = getattr(provider, "policy", None)
            if isinstance(attached, WorkspacePolicy):
                if (
                    attached.workspace_id != store.policy.workspace_id
                    or attached.config.fingerprint != store.policy.config.fingerprint
                ):
                    raise WorkbenchError(
                        "POLICY_DENIED", "Routed adapter workspace or configuration differs"
                    )
                if (
                    attached.config.limits.context_bytes > spec.max_input_tokens
                    or attached.config.limits.max_output_tokens > spec.max_output_tokens
                ):
                    raise WorkbenchError(
                        "CONFIG_ERROR", "Model descriptor understates adapter token bounds"
                    )
            payload = {"request": request, "context": context}
            if len(canonical_json(payload).encode()) > spec.max_input_tokens:
                raise WorkbenchError(
                    "LIMIT_EXCEEDED", "Request exceeds the registered input token bound"
                )
            reserve_in = spec.max_input_tokens * spec.max_requests
            reserve_out = spec.max_output_tokens * spec.max_requests
            reserved_cost = spec.cost_microusd(reserve_in, reserve_out)
            if reserved_cost is None and self.limits.maximum_cost_usd is not None:
                raise WorkbenchError(
                    "CONFIG_ERROR", "Dollar admission requires configured model prices"
                )
            reservation = store.reserve_resources(
                root_id,
                reserve_in + reserve_out,
                reserved_cost or 0,
                self.limits.maximum_tokens,
                self.limits.maximum_cost_microusd
                if self.limits.maximum_cost_microusd is not None
                else 2**63 - 1,
                pricing_known=reserved_cost is not None,
            )
            allowance = _RequestAllowance(budget, spec.max_requests, store, task_id)
            receipts = _Receipts(intents)
            try:
                route_intent = intents.intent(
                    "model.route",
                    {"model": spec.model or spec.name, "payload_hash": canonical_hash(payload)},
                )
            except BaseException:
                # Nothing was dispatched: refund the admission instead of leaving it charged.
                store.settle_resources(reservation, 0, 0)
                raise
            started = time.monotonic()
            rejection: ProviderRejected | None = None
            failure: WorkbenchError | None = None
            result: ProviderResult | None = None
            try:
                result = provider.analyze(
                    request, context, executor=executor, budget=allowance, intents=receipts
                )
                if not isinstance(result, ProviderResult):
                    raise WorkbenchError(
                        "PROVIDER_INVALID_RESPONSE", "Adapter returned an invalid result"
                    )
                if result.usage.requests != allowance.count or allowance.count == 0:
                    raise WorkbenchError(
                        "PROVIDER_INVALID_RESPONSE", "Adapter request usage is inconsistent"
                    )
                if receipts.pending or receipts.unknown_ids or result.usage.unknown_receipts:
                    raise WorkbenchError(
                        "OUTCOME_UNKNOWN", "Adapter returned with unresolved external intents"
                    )
                incoming, outgoing = result.usage.input_tokens, result.usage.output_tokens
                observed_in, observed_out = receipts.tokens()
                if (
                    observed_in is not None
                    and observed_out is not None
                    and receipts.receipts
                    and (incoming != observed_in or outgoing != observed_out)
                ):
                    raise WorkbenchError(
                        "PROVIDER_INVALID_RESPONSE", "Adapter token usage contradicts receipts"
                    )
            except ProviderRejected as error:
                incoming, outgoing = receipts.tokens()
                # The rejection must describe the latest request, not an earlier completion.
                if (
                    not receipts.receipts
                    or receipts.latest_receipt != receipts.latest_intent
                    or receipts.receipts[-1].get("status") not in {"rejected", "rate_limited"}
                ):
                    failure = WorkbenchError(
                        "PROVIDER_INVALID_RESPONSE",
                        "Adapter rejection is not confirmed by a receipt",
                    )
                else:
                    rejection = error
            except WorkbenchError as error:
                failure = error
                incoming, outgoing = receipts.tokens()
            except BaseException:
                store.unknown_resources(reservation)
                intents.unknown(route_intent)
                raise
            elapsed_ms = max(0, int((time.monotonic() - started) * 1_000))
            if (
                receipts.pending
                or receipts.unknown_ids
                or failure is not None
                and failure.code == "OUTCOME_UNKNOWN"
            ):
                store.unknown_resources(reservation)
                intents.unknown(route_intent)
                raise WorkbenchError("OUTCOME_UNKNOWN", "Uncertain model outcome blocks fallback")
            cost = (
                None
                if incoming is None or outgoing is None
                else spec.cost_microusd(incoming, outgoing)
            )
            if (
                incoming is not None
                and outgoing is not None
                and (incoming > reserve_in or outgoing > reserve_out)
            ):
                store.unknown_resources(reservation)
                intents.receipt(route_intent, {"status": "resource_bound_exceeded"})
                raise WorkbenchError("LIMIT_EXCEEDED", "Adapter exceeded registered token bounds")
            try:
                store.settle_resources(
                    reservation,
                    reserve_in + reserve_out
                    if incoming is None or outgoing is None
                    else incoming + outgoing,
                    (reserved_cost or 0) if cost is None else cost,
                )
            except WorkbenchError:
                store.unknown_resources(reservation)
                intents.receipt(route_intent, {"status": "resource_bound_exceeded"})
                raise
            intents.receipt(
                route_intent,
                {
                    "status": "rejected" if rejection else "failed" if failure else "completed",
                    "requests": allowance.count,
                    "input_tokens": incoming,
                    "output_tokens": outgoing,
                    "estimated_cost_usd": None if cost is None else cost / 1_000_000,
                },
            )
            store.event(
                task_id,
                "model.rejected" if rejection else "model.failed" if failure else "model.completed",
                {
                    "agent": spec.name,
                    "root_id": root_id,
                    "elapsed_ms": elapsed_ms,
                    "input_tokens": incoming,
                    "output_tokens": outgoing,
                    "cost_microusd": cost,
                    "error_code": rejection.code
                    if rejection
                    else failure.code
                    if failure
                    else None,
                },
            )
            total_requests += allowance.count
            total_in = None if total_in is None or incoming is None else total_in + incoming
            total_out = None if total_out is None or outgoing is None else total_out + outgoing
            total_cost = None if total_cost is None or cost is None else total_cost + cost
            if failure is not None:
                raise failure
            if rejection is not None:
                last_rejection = rejection
                continue
            assert result is not None
            return ProviderResult(
                result.analysis,
                Usage(
                    requests=total_requests,
                    input_tokens=total_in,
                    output_tokens=total_out,
                    unknown_receipts=result.usage.unknown_receipts,
                    estimated_cost_usd=None if total_cost is None else total_cost / 1_000_000,
                ),
            )
        assert last_rejection is not None
        raise last_rejection
