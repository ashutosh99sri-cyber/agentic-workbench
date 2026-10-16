"""Contract fixtures for the host callback recipe; zero external provider calls."""

from __future__ import annotations

import json
import os
import runpy
import shutil
import sys
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from agentic_workbench import CommandConfig, Config, Grant, Workbench
from agentic_workbench.config import Limits, ProviderConfig
from agentic_workbench.errors import WorkbenchError
from agentic_workbench.models import canonical_json, text_hash
from agentic_workbench.policy import WorkspacePolicy
from agentic_workbench.providers import Provider, ProviderRegistry, ProviderRejected

REPOSITORY = Path(__file__).resolve().parents[1]
RECIPE = REPOSITORY / "examples/integrations/provider_adapter.py"
ANALYSIS = {
    "summary": "Deterministic contract fixture; no model inference",
    "findings": [],
    "recommendations": [],
    "candidate_edits": [],
    "limitations": ["Offline fixture; no evidence of model quality or live interoperability"],
}
HOST = "provider.example"


class Budget:
    def __init__(self, *, deny: bool = False) -> None:
        self.count, self.deny = 0, deny

    def reserve(self, maximum: int) -> None:
        if self.deny or self.count >= maximum:
            raise WorkbenchError("LIMIT_EXCEEDED", "Fixture request budget exhausted")
        self.count += 1


class Intents:
    def __init__(self) -> None:
        self.events: list[tuple[str, Any]] = []

    def intent(self, kind: str, metadata: dict[str, Any]) -> str:
        self.events.append(("intent", {"kind": kind, **metadata}))
        return "fixture-intent"

    def receipt(self, intent_id: str, metadata: dict[str, Any]) -> None:
        self.events.append(("receipt", metadata))

    def unknown(self, intent_id: str) -> None:
        self.events.append(("unknown", intent_id))


class Executor:
    allowed = ("host_read_only",)
    schemas = [{"name": "host_read_only"}]

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        pytest.fail("The direct-analysis recipe must not expand or execute host tools")


def response(analysis: dict[str, Any] | None = None) -> str:
    return canonical_json(
        {"analysis": analysis or ANALYSIS, "usage": {"input_tokens": 0, "output_tokens": 0}}
    )


def build(tmp_path: Path, transport: Any, *, grants: Grant | None = None, **kwargs: Any) -> Any:
    provider_class = runpy.run_path(str(RECIPE))["CallbackProvider"]
    config = Config(provider=ProviderConfig(name="callback", model="offline-fixture"), **kwargs)
    policy = WorkspacePolicy(
        tmp_path, config, grants=grants or Grant(network=True, provider_hosts=(HOST,))
    )
    return provider_class(policy, transport, domain=HOST)


def test_registered_callback_reserves_and_records_before_dispatch(tmp_path: Path) -> None:
    budget, intents, payloads = Budget(), Intents(), []

    def transport(payload: bytes, deadline: float, response_limit: int) -> str:
        assert budget.count == 1 and intents.events[0][0] == "intent"
        assert time.monotonic() < deadline <= time.monotonic() + 60
        assert response_limit == 16_000
        payloads.append(json.loads(payload))
        return response()

    provider = build(tmp_path, transport)
    registry = ProviderRegistry()
    assert isinstance(provider, Provider)
    registry.register("callback", provider)
    result = registry.get("callback").analyze(
        "Review app.py", {}, executor=Executor(), budget=budget, intents=intents
    )
    assert result.analysis == ANALYSIS and result.usage.requests == 1
    assert result.usage.input_tokens == result.usage.output_tokens == 0
    assert payloads[0]["tools"] == []
    assert [event[0] for event in intents.events] == ["intent", "receipt"]
    assert intents.events[-1][1]["status"] == "received"


@pytest.mark.parametrize("grants", [Grant(), Grant(network=True)])
def test_missing_network_or_domain_grant_prevents_dispatch(tmp_path: Path, grants: Grant) -> None:
    calls, budget, intents = [], Budget(), Intents()
    provider = build(tmp_path, lambda *args: calls.append(args), grants=grants)
    with pytest.raises(WorkbenchError) as failure:
        provider.analyze("Review", {}, executor=Executor(), budget=budget, intents=intents)
    assert failure.value.code == "POLICY_DENIED"
    assert not calls and not intents.events and budget.count == 0


def test_budget_denial_prevents_intent_and_dispatch(tmp_path: Path) -> None:
    calls, intents = [], Intents()
    provider = build(tmp_path, lambda *args: calls.append(args))
    with pytest.raises(WorkbenchError, match="budget exhausted"):
        provider.analyze(
            "Review", {}, executor=Executor(), budget=Budget(deny=True), intents=intents
        )
    assert not calls and not intents.events


def test_bounded_payload_measurement_and_secret_redaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "synthetic-opaque-fixture-credential"
    monkeypatch.setenv("RECIPE_API_KEY", secret)
    payloads, budget, intents = [], Budget(), Intents()
    provider = build(tmp_path, lambda payload, *_: payloads.append(payload) or response())
    context = {"source": f"value = '{secret}'\n", "authorization": "Bearer fake-value"}
    request = f"Review {secret}"
    measured = provider.context_size(request, context, executor=Executor())
    provider.analyze(request, context, executor=Executor(), budget=budget, intents=intents)
    assert measured == len(payloads[0]) <= provider.policy.config.limits.context_bytes
    assert secret.encode() not in payloads[0] and b"fake-value" not in payloads[0]
    assert b"[REDACTED]" in payloads[0] and secret not in repr(intents.events)
    calls: list[Any] = []
    tiny = build(tmp_path, lambda *args: calls.append(args), limits=Limits(context_bytes=1))
    assert tiny.context_size("Review", {}, executor=Executor()) > 1
    with pytest.raises(WorkbenchError) as failure:
        tiny.analyze("Review", {}, executor=Executor(), budget=Budget(), intents=Intents())
    assert failure.value.code == "LIMIT_EXCEEDED" and not calls


@pytest.mark.parametrize(
    "invalid",
    [
        "not-json",
        response({**ANALYSIS, "candidate_edits": "not-a-list"}),
        canonical_json({"analysis": ANALYSIS, "usage": {"input_tokens": -1, "output_tokens": 0}}),
        canonical_json({"analysis": ANALYSIS, "usage": {"input_tokens": True, "output_tokens": 0}}),
        canonical_json({"analysis": ANALYSIS, "usage": {"input_tokens": 1.0, "output_tokens": 0}}),
        canonical_json(
            {"analysis": ANALYSIS, "usage": {"input_tokens": 2**63, "output_tokens": 0}}
        ),
        response() + " " * 16_000,
    ],
)
def test_invalid_complete_response_has_typed_error_and_receipt(
    tmp_path: Path, invalid: str
) -> None:
    intents, budget = Intents(), Budget()
    provider = build(tmp_path, lambda *_: invalid)
    with pytest.raises(WorkbenchError) as failure:
        provider.analyze("Review", {}, executor=Executor(), budget=budget, intents=intents)
    assert failure.value.code == "PROVIDER_INVALID_RESPONSE"
    assert budget.count == 1 and intents.events[-1] == ("receipt", {"status": "invalid_response"})


def test_known_rejection_is_receipted_without_an_automatic_retry(tmp_path: Path) -> None:
    calls, intents = [], Intents()

    def rejected(*args: Any) -> str:
        calls.append(args)
        raise ProviderRejected("Known fixture rejection")

    provider = build(tmp_path, rejected)
    with pytest.raises(ProviderRejected):
        provider.analyze("Review", {}, executor=Executor(), budget=Budget(), intents=intents)
    assert len(calls) == 1 and intents.events[-1] == ("receipt", {"status": "rejected"})


def test_unknown_transport_outcome_latches_against_replay(tmp_path: Path) -> None:
    calls, intents, budget = [], Intents(), Budget()

    def disconnected(*args: Any) -> str:
        calls.append(args)
        raise TimeoutError("Untrusted transport diagnostic must not be persisted")

    provider = build(tmp_path, disconnected)
    for _ in range(2):
        with pytest.raises(WorkbenchError) as failure:
            provider.analyze("Review", {}, executor=Executor(), budget=budget, intents=intents)
        assert failure.value.code == "OUTCOME_UNKNOWN"
    assert len(calls) == budget.count == 1 and intents.events[-1][0] == "unknown"
    assert "diagnostic" not in repr(intents.events)


def test_sdk_network_grant_cannot_be_borrowed_from_adapter(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("value = 1\n")
    calls: list[Any] = []
    provider = build(tmp_path, lambda *args: calls.append(args) or response())
    with Workbench(tmp_path, provider.policy.config, provider=provider) as wb:
        with pytest.raises(WorkbenchError) as failure:
            wb.run_agent("engineering", "Review app.py")
        assert failure.value.code == "POLICY_DENIED"
        assert wb.store.export()["intents"] == []
    assert not calls


@pytest.mark.parametrize("count", [1.0, 2**63])
def test_invalid_usage_closes_durable_intent(tmp_path: Path, count: int | float) -> None:
    (tmp_path / "app.py").write_text("value = 1\n")
    invalid = canonical_json(
        {"analysis": ANALYSIS, "usage": {"input_tokens": count, "output_tokens": 0}}
    )
    provider = build(tmp_path, lambda *_: invalid)
    with Workbench(
        tmp_path, provider.policy.config, grants=provider.policy.grants, provider=provider
    ) as wb:
        with pytest.raises(WorkbenchError) as failure:
            wb.run_agent("engineering", "Review app.py")
        assert failure.value.code == "PROVIDER_INVALID_RESPONSE"
        [intent] = wb.store.export()["intents"]
        assert intent["state"] == "received" and intent["usage"]["status"] == "invalid_response"


def test_durable_unknown_outcome_blocks_resume_with_a_new_adapter(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("value = 1\n")
    calls: list[Any] = []

    def disconnected(*args: Any) -> str:
        calls.append(args)
        raise TimeoutError("Offline uncertain outcome")

    provider = build(tmp_path, disconnected)
    grants, config = provider.policy.grants, provider.policy.config
    with Workbench(tmp_path, config, grants=grants, provider=provider) as wb:
        with pytest.raises(WorkbenchError, match="OUTCOME_UNKNOWN"):
            wb.run_agent("engineering", "Review app.py")
        exported = wb.store.export()
        [intent] = exported["intents"]
        assert intent["state"] == "unknown" and intent["usage"] is None
        assert exported["budgets"][0]["reserved"] == 1
        task_id = intent["task_id"]
    fresh = build(tmp_path, disconnected)
    with Workbench(tmp_path, config, grants=grants, provider=fresh) as wb:
        with pytest.raises(WorkbenchError, match="OUTCOME_UNKNOWN"):
            wb.resume(task_id)
    assert len(calls) == 1


def test_sdk_source_boundaries_and_candidate_require_fresh_approval(tmp_path: Path) -> None:
    source = "value = 1\n"
    (tmp_path / "app.py").write_text(source)
    (tmp_path / ".envrc").write_text("private-source-canary\n")
    candidate = deepcopy(ANALYSIS)
    candidate["candidate_edits"] = [
        {
            "path": "app.py",
            "base_hash": text_hash(source),
            "content": "value = 2\n",
            "delete": False,
        }
    ]
    calls: list[bytes] = []
    grants = Grant(network=True, write=True, provider_hosts=(HOST,))
    provider = build(
        tmp_path, lambda payload, *_: calls.append(payload) or response(candidate), grants=grants
    )
    registry = ProviderRegistry()
    registry.register("callback", provider)
    with Workbench(
        tmp_path, provider.policy.config, grants=grants, provider_registry=registry
    ) as wb:
        result = wb.run_agent("engineering", "Review app.py")
        [proposal_id] = result["proposal_ids"]
        assert (tmp_path / "app.py").read_text() == source
        for approval in (None, "0" * 64):
            with pytest.raises(WorkbenchError) as failure:
                wb.apply(proposal_id, dry_run=False, approval=approval)
            assert failure.value.code == "APPROVAL_REQUIRED"
        old_digest = wb.review(proposal_id)["digest"]
        changed = deepcopy(candidate["candidate_edits"])
        changed[0]["content"] = "value = 3\n"
        later = wb.propose(changed, rationale="A different fixture candidate")
        with pytest.raises(WorkbenchError) as failure:
            wb.apply(later["proposal_id"], dry_run=False, approval=old_digest)
        assert failure.value.code == "APPROVAL_REQUIRED"
        assert (tmp_path / "app.py").read_text() == source
        assert len(calls) == 1 and b"private-source-canary" not in calls[0]
        receipt = wb.store.export()["intents"][0]
        assert receipt["state"] == "received" and receipt["usage"]["status"] == "received"


@pytest.mark.skipif(os.name != "posix", reason="Approved mutations require POSIX")
def test_callback_drives_real_disposable_repair_with_supplied_candidate(tmp_path: Path) -> None:
    root = tmp_path / "python_app"
    shutil.copytree(REPOSITORY / "examples/python_app", root)
    source = (root / "app.py").read_text()
    fixed = source.replace(
        "return amount_cents - discount_percent",
        "return amount_cents * (100 - discount_percent) // 100",
    )
    candidate = deepcopy(ANALYSIS)
    candidate["candidate_edits"] = [
        {"path": "app.py", "base_hash": text_hash(source), "content": fixed, "delete": False}
    ]
    calls: list[bytes] = []
    grants = Grant(
        network=True, write=True, execute=True, trusted_host=True, provider_hosts=(HOST,)
    )
    config = Config(
        provider=ProviderConfig(name="callback", model="offline-fixture"),
        commands={"unit": CommandConfig((sys.executable, "-B", "-m", "unittest", "-q"))},
    )
    provider_class = runpy.run_path(str(RECIPE))["CallbackProvider"]
    provider = provider_class(
        WorkspacePolicy(root, config, grants=grants),
        lambda payload, *_: calls.append(payload) or response(candidate),
        domain=HOST,
    )
    registry = ProviderRegistry()
    registry.register("callback", provider)
    with Workbench(root, config, grants=grants, provider_registry=registry) as wb:
        options = {"command_id": "unit", "edit_paths": ["app.py"], "backend": "trusted-host"}
        first = wb.repair("Fix the percentage discount", **options)
        assert not calls
        options["task_id"] = first["task_id"]
        second = wb.repair(
            "Fix the percentage discount",
            baseline_approval=first["reviews"]["baseline"]["digest"],
            **options,
        )
        assert second["baseline"]["exit_code"] != 0 and len(calls) == 1
        assert (root / "app.py").read_text() == source
        third = wb.repair(
            "Fix the percentage discount", approval=second["reviews"]["change"]["digest"], **options
        )
        final = wb.repair(
            "Fix the percentage discount",
            test_approval=third["reviews"]["test"]["digest"],
            **options,
        )
        assert final["outcome"] == "repaired" and final["state"] == "succeeded"
        assert final["attempts"][0]["verification"]["exit_code"] == 0 and len(calls) == 1
        assert (root / "app.py").read_text() == fixed
        assert wb.store.export()["intents"][0]["state"] == "received"
