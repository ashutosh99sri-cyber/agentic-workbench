from __future__ import annotations

import importlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from typing import Any

import pytest

from agentic_workbench.config import Config, Limits, ProviderConfig
from agentic_workbench.errors import WorkbenchError
from agentic_workbench.models import AgentResult, Evidence, Finding, Grant, text_hash
from agentic_workbench.orchestrator import Node
from agentic_workbench.policy import WorkspacePolicy
from agentic_workbench.providers import Provider, ProviderRegistry, ProviderResult
from agentic_workbench.providers_openai import OpenAIProvider
from agentic_workbench.sdk import Workbench
from agentic_workbench.skills import ROLES, SkillRegistry

ANALYSIS = {
    "summary": "Source-derived analysis",
    "findings": [],
    "recommendations": [],
    "candidate_edits": [],
    "limitations": ["No runtime execution"],
}
KEY = "test-only-credential-never-persist"


class Budget:
    def __init__(self) -> None:
        self.count = 0
        self.lock = threading.Lock()

    def reserve(self, maximum: int) -> None:
        with self.lock:
            if self.count >= maximum:
                raise WorkbenchError("LIMIT_EXCEEDED", "Shared request budget exhausted")
            self.count += 1


class Intents:
    def __init__(self) -> None:
        self.events: list[tuple[str, Any]] = []

    def intent(self, kind: str, metadata: dict[str, Any]) -> str:
        intent_id = str(len(self.events))
        self.events.append(("intent", {"id": intent_id, "kind": kind, **metadata}))
        return intent_id

    def receipt(self, intent_id: str, metadata: dict[str, Any]) -> None:
        self.events.append(("receipt", {"id": intent_id, **metadata}))

    def unknown(self, intent_id: str) -> None:
        self.events.append(("unknown", intent_id))


class Executor:
    def __init__(self) -> None:
        self.schemas = [
            {
                "type": "function",
                "name": "read_source",
                "description": "Read approved source",
                "strict": True,
                "parameters": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["path"],
                    "properties": {"path": {"type": "string", "minLength": 1, "maxLength": 4096}},
                },
            }
        ]
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.result: Any = {"text": "approved source", "source_hash": "a" * 64}

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((name, arguments))
        return self.result  # type: ignore[no-any-return]


def test_optional_sdk_absence_leaves_core_importable(tmp_path: Any, monkeypatch: Any) -> None:
    original = importlib.import_module

    def missing(name: str, *args: Any, **kwargs: Any) -> Any:
        if name in {"openai", "httpx2"}:
            raise ImportError("not installed")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", missing)
    config = Config(provider=ProviderConfig(name="openai", model="fixture-model"))
    provider = OpenAIProvider(WorkspacePolicy(tmp_path, config, grants=Grant(network=True)))
    budget, intents = Budget(), Intents()
    with pytest.raises(WorkbenchError, match="Install the openai extra"):
        provider.analyze("Review", {}, executor=Executor(), budget=budget, intents=intents)
    assert budget.count == 0 and not intents.events


def message(text: str | None = None) -> dict[str, Any]:
    return {
        "id": "msg_fixture",
        "type": "message",
        "role": "assistant",
        "status": "completed",
        "phase": "final_answer",
        "content": [
            {"type": "output_text", "text": text or json.dumps(ANALYSIS), "annotations": []}
        ],
    }


def call(
    call_id: str = "actual_call_1", name: str = "read_source", arguments: str = '{"path":"app.py"}'
) -> dict[str, Any]:
    return {
        "id": "fc_fixture",
        "type": "function_call",
        "call_id": call_id,
        "name": name,
        "arguments": arguments,
        "status": "completed",
    }


def response(output: list[dict[str, Any]] | None = None, **overrides: Any) -> dict[str, Any]:
    return {
        "id": "resp_fixture",
        "object": "response",
        "created_at": 1_000,
        "model": "fixture-model",
        "status": "completed",
        "output": output if output is not None else [message()],
        "parallel_tool_calls": False,
        "tool_choice": "auto",
        "tools": [],
        "usage": {
            "input_tokens": 10,
            "output_tokens": 20,
            "total_tokens": 30,
            "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        },
        **overrides,
    }


@pytest.fixture
def runtime(tmp_path: Any, monkeypatch: Any) -> Any:
    pytest.importorskip("openai")
    httpx = pytest.importorskip("httpx2")
    monkeypatch.setenv("OPENAI_API_KEY", KEY)
    requests: list[Any] = []
    queue: list[Any] = [response()]

    def handle(request: Any) -> Any:
        requests.append(request)
        value = queue.pop(0)
        if isinstance(value, Exception):
            raise value
        if isinstance(value, tuple):
            status, body, headers = value
            return httpx.Response(status, json=body, headers=headers)
        if isinstance(value, str):
            return httpx.Response(200, text=value)
        return httpx.Response(200, json=value)

    def build(**kwargs: Any) -> Any:
        config = Config(
            provider=kwargs.pop(
                "provider",
                ProviderConfig(
                    name="openai", model="fixture-model", embedding_model="fixture-embedding"
                ),
            ),
            limits=kwargs.pop("limits", Limits()),
        )
        policy = WorkspacePolicy(tmp_path, config, grants=kwargs.pop("grants", Grant(network=True)))
        adapter = OpenAIProvider(policy, transport=httpx.MockTransport(handle), **kwargs)
        return adapter

    return build, queue, requests, Budget(), Intents(), Executor(), httpx


def analyze(runtime: Any, provider: Any = None) -> ProviderResult:
    build, _, _, budget, intents, executor, _ = runtime
    return (provider or build()).analyze(
        "Review source", {}, executor=executor, budget=budget, intents=intents
    )


def test_context_size_matches_actual_initial_wire_payload_without_dispatch(runtime: Any) -> None:
    build, _, requests, budget, intents, executor, _ = runtime
    provider = build()
    context = {"source": '\\n"\\' * 100}
    measured = provider.context_size("Review source", context, executor=executor)
    assert not requests and budget.count == 0 and not intents.events
    provider.analyze("Review source", context, executor=executor, budget=budget, intents=intents)
    assert measured == len(requests[0].content)


def test_explicit_host_tool_scope_supports_registered_read_names(runtime: Any) -> None:
    build, _, requests, budget, intents, executor, _ = runtime
    executor.allowed = ("host_read",)
    executor.schemas[0]["name"] = "host_read"
    build().analyze("Review source", {}, executor=executor, budget=budget, intents=intents)
    assert json.loads(requests[0].content)["tools"][0]["name"] == "host_read"


def test_provider_tool_dynamic_refs_cannot_fetch_remote_schemas(runtime: Any) -> None:
    build, _, requests, budget, intents, executor, _ = runtime
    executor.schemas[0]["parameters"]["$dynamicRef"] = "https://unapproved.invalid/schema"
    with pytest.raises(WorkbenchError, match="local references"):
        build().analyze("Review", {}, executor=executor, budget=budget, intents=intents)
    assert not requests and budget.count == 0 and not intents.events


def source_analysis(role: str) -> dict[str, Any]:
    return {
        **ANALYSIS,
        "summary": f"{role}: source-derived review",
        "findings": [
            {
                "title": "Observed value",
                "details": "The source sets value to 1.",
                "kind": "fact",
                "severity": "info",
                "evidence": [
                    {
                        "path": "app.py",
                        "start_line": 1,
                        "end_line": 1,
                        "source_hash": text_hash("value=1\n"),
                    }
                ],
            }
        ],
        "candidate_edits": [
            {
                "path": "app.py",
                "base_hash": text_hash("value=1\n"),
                "content": "value=2\n",
                "delete": False,
            }
        ],
        "limitations": ["Mock transport; runtime behavior remains unverified"],
    }


@pytest.mark.parametrize("role", ROLES)
def test_each_role_uses_installed_sdk_and_persists_result_and_receipt(
    runtime: Any, tmp_path: Any, role: str
) -> None:
    build, queue, requests, *_ = runtime
    target = tmp_path / "app.py"
    target.write_text("value=1\n")
    queue[:] = [response([message(json.dumps(source_analysis(role)))])]
    grants = Grant(network=True, write=True)
    provider = build(grants=grants)
    with Workbench(tmp_path, provider.policy.config, grants=grants, provider=provider) as wb:
        result = wb.run_agent(role, "Review value")
        assert result["agent"] == role and result["mode"] == "llm"
        assert result["findings"][0]["evidence"]
        assert result["proposal_ids"] and target.read_text() == "value=1\n"
        assert wb.review(result["proposal_ids"][0])["diff"]
        assert result["usage"]["requests"] == 1
        task_id = result["task_id"]
        persisted = wb.store.export()
        receipt = persisted["intents"][0]
        assert receipt["task_id"] == task_id and receipt["state"] == "received"
        assert receipt["usage"]["response_id"] == "resp_fixture"
        assert receipt["usage"]["input_tokens"] == 10
        assert KEY not in repr(persisted)
    with Workbench(tmp_path, provider.policy.config) as reopened:
        assert reopened.task_status(task_id)["result"] == result
        assert reopened.task_status(task_id)["state"] == "succeeded"
    payload = json.loads(requests[0].content)
    context = json.loads(payload["input"][0]["content"])["context"]
    assert context["role"] == role and context["skills"]
    selected = SkillRegistry(provider.policy).select(role, [], ["python"])
    assert {tool["name"] for tool in payload["tools"]} == {
        name for skill in selected for name in skill.required_tools
    }
    assert len(requests[0].content) <= provider.policy.config.limits.context_bytes
    assert target.read_text() == "value=1\n"


def test_envrc_never_enters_index_provider_context_or_persisted_state(
    runtime: Any, tmp_path: Any
) -> None:
    build, _, requests, *_ = runtime
    secret = "whsec_fixture_123456789"
    (tmp_path / ".envrc").write_text(f"export STRIPE_WEBHOOK_SECRET={secret}\n")
    (tmp_path / "app.py").write_text("value=1\n")
    provider = build()
    with Workbench(
        tmp_path, provider.policy.config, grants=Grant(network=True), provider=provider
    ) as wb:
        scanned = wb.scan()
        assert {source["path"] for source in scanned["files"]} == {"app.py"}
        assert not requests
        with pytest.raises(WorkbenchError, match="POLICY_DENIED"):
            wb.policy.read_source(".envrc")
        wb.run_agent("intelligence", "Review STRIPE_WEBHOOK_SECRET")
        assert secret not in json.dumps(wb.store.export())
    assert len(requests) == 1 and secret.encode() not in requests[0].content


def test_explicit_eight_role_graph_uses_sdk_and_carries_cited_dependencies(
    runtime: Any, tmp_path: Any
) -> None:
    build, queue, requests, *_ = runtime
    target = tmp_path / "app.py"
    target.write_text("value=1\n")
    queue[:] = [response([message(json.dumps(source_analysis(role)))]) for role in ROLES]
    grants = Grant(network=True, write=True)
    provider = build(grants=grants)
    nodes = [Node(role, role, (ROLES[i - 1],) if i else ()) for i, role in enumerate(ROLES[:-1])]
    nodes.append(Node("orchestrator", "orchestrator", ROLES[:-1]))
    with Workbench(tmp_path, provider.policy.config, grants=grants, provider=provider) as wb:
        result = wb.orchestrate("Review value", nodes)
        assert [item["agent"] for item in result["results"]] == list(ROLES)
        assert all(item["mode"] == "llm" for item in result["results"])
        persisted = wb.store.export()
        assert len(persisted["tasks"]) == 9
        assert all(task["state"] == "succeeded" for task in persisted["tasks"])
        assert len(persisted["intents"]) == len(requests) == 8
        assert all(intent["state"] == "received" for intent in persisted["intents"])
        for i, request in enumerate(requests):
            assert len(request.content) <= provider.policy.config.limits.context_bytes
            context = json.loads(json.loads(request.content)["input"][0]["content"])["context"]
            assert context["role"] == ROLES[i]
            if i == len(ROLES) - 1:
                assert [item["task_id"] for item in context["dependencies"]] == [
                    item["task_id"] for item in result["results"][:-1]
                ]
                assert [item["agent"] for item in context["dependencies"]] == list(ROLES[:-1])
                assert any(item.get("findings") for item in context["dependencies"])
            elif i:
                dependency = context["dependencies"][0]
                assert dependency["task_id"] == result["results"][i - 1]["task_id"]
                assert dependency["findings"][0]["evidence"]
                assert dependency["limitations"]
                assert context["dependencies_truncated"] is False
        assert wb.task_status(result["task_id"])["result"] == result
        assert wb.resume(result["task_id"]) == result
        assert len(requests) == 8
        assert len(result["proposal_ids"]) == 8 and target.read_text() == "value=1\n"


def test_oversized_dependency_is_explicitly_truncated_within_full_sdk_request(
    runtime: Any, tmp_path: Any
) -> None:
    build, _, requests, *_ = runtime
    (tmp_path / "app.py").write_text("value=1\n")
    citation = Evidence("app.py", 1, 1, text_hash("value=1\n"))
    upstream = AgentResult(
        "upstream-task",
        "intelligence",
        "llm",
        "源" * 8_000,
        evidence=[citation] * 200,
        findings=[
            Finding(f"Fact {i}", "詳細" * 2_000, "fact", evidence=[citation] * 20)
            for i in range(100)
        ],
        limitations=["不明" * 2_000] * 100,
    ).to_dict()
    provider = build()
    with Workbench(
        tmp_path, provider.policy.config, grants=Grant(network=True), provider=provider
    ) as wb:
        wb._runtime().run("engineering", "Review value", dependencies=[upstream])
    assert len(requests) == 1
    assert len(requests[0].content) <= provider.policy.config.limits.context_bytes
    context = json.loads(json.loads(requests[0].content)["input"][0]["content"])["context"]
    assert context["dependencies_truncated"] is True
    dependency = context["dependencies"][0]
    assert dependency["task_id"] == "upstream-task" and dependency["truncated"] is True
    assert dependency["findings"][0]["evidence"] == [citation.to_dict()] * 2
    assert dependency["limitations"]


def test_dependency_identity_limit_prevents_sdk_dispatch(runtime: Any, tmp_path: Any) -> None:
    build, queue, requests, *_ = runtime
    provider = build(limits=Limits(context_bytes=800))
    dependencies = [
        AgentResult(f"{role}-" + "x" * 100, role, "llm", "Summary").to_dict() for role in ROLES[:-1]
    ]
    with Workbench(
        tmp_path, provider.policy.config, grants=Grant(network=True), provider=provider
    ) as wb:
        with pytest.raises(WorkbenchError, match="Dependency identities"):
            wb._runtime().run("orchestrator", "Review value", dependencies=dependencies)
        assert wb.store.export()["intents"] == []
    assert requests == [] and len(queue) == 1


def test_registered_providers_are_explicit_and_offline_missing_is_actionable(runtime: Any) -> None:
    build, *_ = runtime
    registry = ProviderRegistry()
    with pytest.raises(WorkbenchError, match="configured provider"):
        registry.get("none")
    with pytest.raises(WorkbenchError, match="not registered"):
        registry.get("repository-supplied-module")
    provider = build()
    assert isinstance(provider, Provider)
    registry.register("openai", provider)
    assert registry.get("openai") is provider
    with pytest.raises(WorkbenchError):
        registry.register("openai", provider)


def test_real_sdk_request_uses_fixed_endpoint_closed_schema_and_usage(
    runtime: Any, monkeypatch: Any
) -> None:
    build, _, requests, budget, intents, _, _ = runtime
    monkeypatch.setenv("OPENAI_BASE_URL", "http://unapproved.invalid")
    monkeypatch.setenv("HTTPS_PROXY", "http://unapproved.invalid")
    monkeypatch.setenv("OPENAI_CUSTOM_HEADERS", "Authorization: Bearer wrong\nX-Untrusted: secret")
    result = analyze(runtime, build())
    request = requests[0]
    assert str(request.url) == "https://api.openai.com/v1/responses"
    assert request.headers["Authorization"] == f"Bearer {KEY}"
    assert "x-untrusted" not in request.headers
    payload = json.loads(request.content)
    assert payload["store"] is False
    assert payload["max_output_tokens"] == 2_000
    assert payload["include"] == ["reasoning.encrypted_content"]
    assert payload["text"]["format"]["strict"] is True
    assert payload["text"]["format"]["schema"]["additionalProperties"] is False
    assert payload["tools"][0]["strict"] is True
    assert len(request.content) <= 16_000
    assert result.analysis == ANALYSIS
    assert result.usage.requests == budget.count == 1
    assert (result.usage.input_tokens, result.usage.output_tokens) == (10, 20)
    assert result.usage.estimated_cost_usd is None
    assert intents.events[-1][1]["response_id"] == "resp_fixture"
    assert intents.events[-1][1]["provider_model"] == "fixture-model"
    assert KEY not in repr(intents.events) and KEY.encode() not in request.content


def test_tool_loop_carries_reasoning_messages_and_actual_call_ids(runtime: Any) -> None:
    _, queue, requests, _, _, executor, _ = runtime
    reasoning = {
        "id": "rs_fixture",
        "type": "reasoning",
        "summary": [],
        "encrypted_content": "fixtureopaque",
    }
    queue[:] = [response([reasoning, call()]), response([call("actual_call_2")]), response()]
    result = analyze(runtime)
    inputs = json.loads(requests[1].content)["input"]
    assert inputs[1:3] == [reasoning, call()]
    assert inputs[3]["call_id"] == "actual_call_1"
    assert inputs[3]["type"] == "function_call_output"
    assert json.loads(inputs[3]["output"]) == executor.result
    inputs = json.loads(requests[2].content)["input"]
    assert inputs[-1]["call_id"] == "actual_call_2"
    assert len(executor.calls) == 2
    assert result.usage.requests == 3 and result.usage.input_tokens == 30


@pytest.mark.parametrize(
    "output,code",
    [
        (
            [
                {
                    "id": "msg",
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "refusal", "refusal": KEY}],
                }
            ],
            "PROVIDER_REFUSAL",
        ),
        (
            [
                {
                    "type": "web_search_call",
                    "id": "ws",
                    "status": "completed",
                    "action": {"type": "search", "query": "unapproved"},
                }
            ],
            "PROVIDER_INVALID_RESPONSE",
        ),
        ([message("not-json")], "VALIDATION_ERROR"),
        ([message(json.dumps({**ANALYSIS, "unexpected": True}))], "VALIDATION_ERROR"),
        ([call(name="apply_change")], "POLICY_DENIED"),
        ([call(arguments='{"path":"app.py","command":"rm"}')], "VALIDATION_ERROR"),
        ([call(arguments='{"path":"app.py","path":"other.py"}')], "VALIDATION_ERROR"),
        ([message(), message()], "PROVIDER_INVALID_RESPONSE"),
    ],
)
def test_untrusted_outputs_are_explicit_and_never_execute_unapproved_tools(
    runtime: Any, output: Any, code: str
) -> None:
    _, queue, requests, _, intents, executor, _ = runtime
    queue[:] = [response(output)]
    with pytest.raises(WorkbenchError) as failure:
        analyze(runtime)
    assert failure.value.code == code
    assert KEY not in str(failure.value) and KEY not in repr(intents.events)
    assert len(requests) == 1 and not executor.calls


@pytest.mark.parametrize(
    "value",
    [response(status="incomplete"), response(output=[]), "[1]", '{"output": NaN}', "not-json"],
)
def test_incomplete_and_malformed_receipts_do_not_replay(runtime: Any, value: Any) -> None:
    _, queue, requests, _, intents, _, _ = runtime
    queue[:] = [value]
    with pytest.raises(WorkbenchError):
        analyze(runtime)
    assert len(requests) == 1
    assert any(kind == "receipt" for kind, _ in intents.events)


def test_explicit_429_retries_are_bounded_and_reserve_every_attempt(runtime: Any) -> None:
    _, queue, requests, budget, intents, _, _ = runtime
    rate_limit = (
        429,
        {"error": {"message": KEY, "type": "rate_limit_error"}},
        {"Retry-After": "0"},
    )
    queue[:] = [rate_limit, rate_limit, response()]
    result = analyze(runtime)
    assert result.usage.requests == budget.count == len(requests) == 3
    assert [metadata["status"] for kind, metadata in intents.events if kind == "receipt"] == [
        "rate_limited",
        "rate_limited",
        "received",
    ]
    queue[:] = [rate_limit] * 4
    before = len(requests)
    with pytest.raises(WorkbenchError, match="retry budget"):
        analyze(runtime)
    assert len(requests) - before == 3 and len(queue) == 1


@pytest.mark.parametrize("cancel_root", [False, True], ids=["child", "root"])
@pytest.mark.parametrize("tool_round", [False, True], ids=["429-retry", "tool-round"])
def test_cancelled_task_tree_blocks_actual_next_provider_dispatch(
    runtime: Any, tmp_path: Any, monkeypatch: Any, cancel_root: bool, tool_round: bool
) -> None:
    *_, httpx = runtime
    (tmp_path / "app.py").write_text("value=1\n")
    config = Config(provider=ProviderConfig(name="openai", model="fixture-model"))
    grants = Grant(network=True)
    requests: list[Any] = []
    reads_after_cancellation: list[str] = []

    def read_source(path: str) -> Any:
        reads_after_cancellation.append(path)
        return original_read_source(path)

    def handle(request: Any) -> Any:
        requests.append(request)
        if len(requests) == 1:
            wb.cancel(root if cancel_root else child)
            monkeypatch.setattr(wb.policy, "read_source", read_source)
            if tool_round:
                arguments = json.dumps(
                    {"path": "app.py", "start_line": 1, "end_line": 1, "source_hash": None}
                )
                return httpx.Response(200, json=response([call(arguments=arguments)]))
            return httpx.Response(
                429,
                json={"error": {"message": "Fixture rate limit", "type": "rate_limit_error"}},
                headers={"Retry-After": "0"},
            )
        return httpx.Response(200, json=response())

    provider = OpenAIProvider(
        WorkspacePolicy(tmp_path, config, grants=grants),
        credential_resolver=lambda: KEY,
        transport=httpx.MockTransport(handle),
    )
    with Workbench(tmp_path, config, grants=grants, provider=provider) as wb:
        original_read_source = wb.policy.read_source
        agent_runtime = wb._runtime()
        root = wb.store.create_task("orchestrator", "Root", agent_runtime.pins("orchestrator"))
        assert wb.store.claim(root, "root-owner")
        child = wb.store.create_task(
            "intelligence", "Review value", agent_runtime.pins("intelligence"), parent_id=root
        )
        with pytest.raises(WorkbenchError, match="CANCELLED"):
            agent_runtime.run("intelligence", "Review value", task_id=child)
        assert wb.store.get_task(child)["state"] == "cancelled"
        assert wb.store.get_task(root)["state"] == ("cancelled" if cancel_root else "running")
        intents = wb.store.export()["intents"]
        assert len(intents) == 1 and intents[0]["state"] == "received"
    assert len(requests) == 1 and not reads_after_cancellation


@pytest.mark.parametrize("retry_after", ["61", "nan", "-1", "invalid-date"])
def test_retry_after_never_exceeds_root_time_budget(runtime: Any, retry_after: str) -> None:
    _, queue, requests, _, _, _, _ = runtime
    queue[:] = [(429, {"error": {"message": "rate limit"}}, {"Retry-After": retry_after})]
    with pytest.raises(WorkbenchError, match="bounded task delay"):
        analyze(runtime)
    assert len(requests) == 1


@pytest.mark.parametrize("status", [500, 503, 408, 409])
def test_possible_server_effects_are_unknown_without_sdk_retries(runtime: Any, status: int) -> None:
    build, queue, requests, _, intents, _, _ = runtime
    provider = build()
    queue[:] = [(status, {"error": {"message": KEY}}, {})]
    with pytest.raises(WorkbenchError, match="OUTCOME_UNKNOWN"):
        analyze(runtime, provider)
    with pytest.raises(WorkbenchError, match="blocks replay"):
        analyze(runtime, provider)
    assert len(requests) == 1 and any(kind == "unknown" for kind, _ in intents.events)
    assert KEY not in repr(intents.events)


def test_transport_timeout_is_unknown_and_credential_resolved_immediately(runtime: Any) -> None:
    build, queue, requests, _, intents, _, httpx = runtime
    resolves: list[bool] = []

    def credential() -> str:
        resolves.append(True)
        return KEY

    provider = build(credential_resolver=credential)
    assert not resolves
    queue[:] = [httpx.ReadTimeout(KEY)]
    with pytest.raises(WorkbenchError) as failure:
        analyze(runtime, provider)
    assert failure.value.code == "OUTCOME_UNKNOWN" and KEY not in str(failure.value)
    assert len(requests) == len(resolves) == 1
    assert intents.events[-1][0] == "unknown"


def test_request_tool_result_and_schema_byte_bounds_are_complete(runtime: Any) -> None:
    build, queue, requests, _, _, executor, _ = runtime
    with pytest.raises(WorkbenchError, match="byte limit"):
        analyze(runtime, build(limits=Limits(context_bytes=100)))
    assert not requests
    executor.schemas[0]["description"] = "x" * 16_000
    with pytest.raises(WorkbenchError, match="byte limit"):
        analyze(runtime)
    assert not requests
    executor.schemas[0]["description"] = "Read source"
    executor.result = {"text": "x" * 16_001}
    queue[:] = [response([call()])]
    with pytest.raises(WorkbenchError, match="byte limit"):
        analyze(runtime)
    assert len(requests) == 1


def test_instructions_and_result_schema_count_towards_bytes(runtime: Any, monkeypatch: Any) -> None:
    from agentic_workbench import providers_openai

    build, _, requests, *_ = runtime
    monkeypatch.setattr(providers_openai, "_INSTRUCTIONS", "x" * 16_000)
    with pytest.raises(WorkbenchError, match="byte limit"):
        analyze(runtime, build())
    assert not requests


def test_carried_tool_payload_is_bounded_as_a_complete_request(runtime: Any) -> None:
    build, queue, requests, budget, intents, executor, _ = runtime
    executor.result = {"text": "x" * 8_000}
    queue[:] = [response([call()])]
    with pytest.raises(WorkbenchError, match="byte limit"):
        build().analyze(
            "Review", {"source": "x" * 8_000}, executor=executor, budget=budget, intents=intents
        )
    assert len(requests) == 1 and budget.count == 1


@pytest.mark.parametrize("value", [None, [], {"bad": float("nan")}])
def test_tool_results_are_validated_independently(runtime: Any, value: Any) -> None:
    _, queue, requests, _, _, executor, _ = runtime
    queue[:] = [response([call()])]
    executor.result = value
    with pytest.raises(WorkbenchError, match="VALIDATION_ERROR"):
        analyze(runtime)
    assert len(requests) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"parameters": {"type": "object", "properties": {}, "required": []}},
        {
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"path": {"$ref": "https://unapproved.invalid/schema"}},
                "required": ["path"],
            }
        },
        {"name": "approve"},
        {"name": []},
        {"strict": False},
    ],
)
def test_tool_schemas_cannot_expose_authority_or_remote_validation(
    runtime: Any, changes: Any
) -> None:
    _, _, requests, _, _, executor, _ = runtime
    executor.schemas[0].update(changes)
    with pytest.raises(WorkbenchError):
        analyze(runtime)
    assert not requests


def test_http_transport_disables_environment_redirects_and_hidden_retries(
    runtime: Any, monkeypatch: Any
) -> None:
    _, _, _, _, _, _, httpx = runtime
    options: list[dict[str, Any]] = []
    original_client = httpx.Client

    class Client(original_client):  # type: ignore[misc, valid-type]
        def __init__(self, **kwargs: Any) -> None:
            options.append(kwargs)
            super().__init__(**kwargs)

    monkeypatch.setattr(httpx, "Client", Client)
    analyze(runtime)
    assert options[0]["verify"] is True
    assert options[0]["trust_env"] is False
    assert options[0]["follow_redirects"] is False
    assert 0 < options[0]["timeout"] <= 60


def test_response_stream_stops_at_byte_limit_and_closes(runtime: Any) -> None:
    build, _, requests, budget, intents, executor, httpx = runtime
    seen: list[int] = []
    closed: list[bool] = []

    class Stream(httpx.SyncByteStream):  # type: ignore[misc, valid-type]
        def __iter__(self) -> Any:
            for index in range(100):
                seen.append(index)
                yield b"x" * 1_000

        def close(self) -> None:
            closed.append(True)

    def handler(request: Any) -> Any:
        requests.append(request)
        return httpx.Response(200, stream=Stream())

    provider = build()
    provider._transport = httpx.MockTransport(handler)
    with pytest.raises(WorkbenchError, match="byte limit|byte or time bounds"):
        provider.analyze("Review", {}, executor=executor, budget=budget, intents=intents)
    assert len(seen) == 17 and closed and len(requests) == 1
    assert intents.events[-1][0] == "receipt"


def test_root_deadline_covers_tools_retries_embeddings_and_later_calls(
    runtime: Any, monkeypatch: Any
) -> None:
    from agentic_workbench import providers_openai

    build, queue, requests, _, _, executor, _ = runtime
    provider = build(limits=Limits(request_timeout=1))
    now = [100.0]
    monkeypatch.setattr(providers_openai.time, "monotonic", lambda: now[0])
    original = executor.execute

    def slow_tool(name: str, values: dict[str, Any]) -> dict[str, Any]:
        now[0] += 2
        return original(name, values)

    executor.execute = slow_tool  # type: ignore[method-assign]
    queue[:] = [response([call()])]
    with pytest.raises(WorkbenchError, match="time budget"):
        analyze(runtime, provider)
    with pytest.raises(WorkbenchError, match="time budget"):
        embed(runtime, provider)
    assert len(requests) == 1


def test_redirects_and_authentication_errors_do_not_retry(runtime: Any) -> None:
    _, queue, requests, _, intents, _, _ = runtime
    queue[:] = [(307, {}, {"Location": "https://unapproved.invalid"})]
    with pytest.raises(WorkbenchError, match="PROVIDER_REJECTED"):
        analyze(runtime)
    queue[:] = [(401, {"error": {"message": KEY}}, {})]
    with pytest.raises(WorkbenchError, match="PROVIDER_REJECTED"):
        analyze(runtime)
    assert len(requests) == 2
    assert KEY not in repr(intents.events)


def test_credentials_are_rejected_in_context_and_scrubbed_from_results(runtime: Any) -> None:
    build, _, requests, budget, intents, executor, _ = runtime
    with pytest.raises(WorkbenchError, match="credential material"):
        build().analyze("Review", {"leak": KEY}, executor=executor, budget=budget, intents=intents)
    assert not requests and not intents.events
    _, queue, *_ = runtime
    queue[:] = [response([message(json.dumps({**ANALYSIS, "summary": KEY}))])]
    result = analyze(runtime)
    assert result.analysis["summary"] == "[REDACTED]"
    assert KEY not in repr(result) and KEY not in repr(intents.events)


def test_provider_debug_logging_cannot_capture_echoed_credential_headers(
    runtime: Any, caplog: Any
) -> None:
    import logging

    _, queue, _, _, intents, _, _ = runtime
    queue[:] = [(200, response(), {"x-request-id": KEY})]
    with caplog.at_level(logging.DEBUG, logger="openai._base_client"):
        analyze(runtime)
    assert KEY not in caplog.text and KEY not in repr(intents.events)
    assert intents.events[-1][1]["request_id"] == "[REDACTED]"


def test_tool_rounds_request_budget_and_reused_ids_stop_before_execution(runtime: Any) -> None:
    build, queue, requests, budget, _, executor, _ = runtime
    queue[:] = [response([call()]), response([call("actual_call_2")])]
    with pytest.raises(WorkbenchError, match="round budget"):
        analyze(runtime, build(limits=Limits(tool_rounds=1)))
    assert len(executor.calls) == 1 and len(requests) == 2
    queue[:] = [response()]
    with pytest.raises(WorkbenchError, match="Shared request budget"):
        analyze(runtime, build(limits=Limits(provider_requests=budget.count)))
    assert len(requests) == 2
    queue[:] = [response([call()]), response([call()])]
    with pytest.raises(WorkbenchError, match="reused a function call ID"):
        analyze(runtime)
    assert len(executor.calls) == 2


def test_budget_is_shared_across_concurrent_children(runtime: Any) -> None:
    build, queue, requests, _, _, _, _ = runtime
    queue[:] = [response()]
    provider = build(limits=Limits(provider_requests=1))

    def run() -> Any:
        try:
            return analyze(runtime, provider)
        except WorkbenchError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: run(), range(2)))
    assert sum(isinstance(result, ProviderResult) for result in results) == 1
    assert "LIMIT_EXCEEDED" in results and len(requests) == 1


def test_missing_configuration_grant_key_and_sdk_are_actionable(
    runtime: Any, monkeypatch: Any
) -> None:
    build, _, requests, *_ = runtime
    with pytest.raises(WorkbenchError, match="host grant"):
        analyze(runtime, build(grants=Grant()))
    with pytest.raises(WorkbenchError, match="provider.model"):
        analyze(runtime, build(provider=ProviderConfig(name="openai")))
    monkeypatch.delenv("OPENAI_API_KEY")
    with pytest.raises(WorkbenchError, match="API key environment"):
        analyze(runtime)
    monkeypatch.setenv("OPENAI_API_KEY", KEY)
    original = importlib.import_module

    def missing(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "openai":
            raise ImportError("not installed")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", missing)
    with pytest.raises(WorkbenchError, match="Install the openai extra"):
        analyze(runtime)
    assert not requests


def embedding() -> dict[str, Any]:
    return {
        "object": "list",
        "model": "fixture-embedding",
        "data": [{"object": "embedding", "index": 0, "embedding": [0.5, 1.0]}],
        "usage": {"prompt_tokens": 3, "total_tokens": 3},
    }


def embed(runtime: Any, provider: Any = None, **kwargs: Any) -> Any:
    build, _, _, budget, intents, _, _ = runtime
    values = {
        "chunk_hashes": [text_hash("source")],
        "dimensions": 2,
        "source_grant": True,
        **kwargs,
    }
    return (provider or build()).embed(["source"], budget=budget, intents=intents, **values)


def test_actual_sdk_embedding_contract_and_provenance(runtime: Any) -> None:
    _, queue, requests, _, _, _, _ = runtime
    queue[:] = [embedding()]
    result = embed(runtime)
    assert str(requests[0].url) == "https://api.openai.com/v1/embeddings"
    assert json.loads(requests[0].content)["encoding_format"] == "float"
    assert result.provider == "openai" and result.model == "fixture-embedding"
    assert result.chunk_hashes == (text_hash("source"),)
    assert result.vectors == ((0.5, 1.0),) and result.usage.input_tokens == 3


@pytest.mark.parametrize(
    "changes",
    [
        {"index": 1},
        {"index": True},
        {"embedding": [1]},
        {"embedding": [True, 1]},
        {"embedding": ["bad", 1]},
        {"embedding": [10**1_000, 1]},
    ],
)
def test_invalid_embedding_vectors_are_rejected(runtime: Any, changes: dict[str, Any]) -> None:
    _, queue, requests, _, _, _, _ = runtime
    value = embedding()
    value["data"][0].update(changes)
    queue[:] = [value]
    with pytest.raises(WorkbenchError, match="PROVIDER_INVALID_RESPONSE"):
        embed(runtime)
    assert len(requests) == 1


def test_embedding_nonfinite_counts_hashes_grants_and_shared_budget(runtime: Any) -> None:
    build, queue, requests, budget, _, _, _ = runtime
    with pytest.raises(WorkbenchError, match="source transmission"):
        embed(runtime, source_grant=False)
    with pytest.raises(WorkbenchError, match="source hashes"):
        embed(runtime, chunk_hashes=["a" * 64])
    assert not requests
    queue[:] = [json.dumps(embedding()).replace("0.5", "NaN")]
    with pytest.raises(WorkbenchError):
        embed(runtime)
    value = deepcopy(embedding())
    value["data"] = []
    queue[:] = [value]
    with pytest.raises(WorkbenchError, match="embedding count"):
        embed(runtime)
    provider = build(limits=Limits(provider_requests=budget.count))
    with pytest.raises(WorkbenchError, match="Shared request budget"):
        embed(runtime, provider)
    assert len(requests) == 2


@pytest.mark.parametrize("failure_mode", ["deadline", "timeout"])
def test_partial_receipt_is_durable_unknown_and_blocks_sdk_restart(
    runtime: Any, monkeypatch: Any, failure_mode: str
) -> None:
    from agentic_workbench import providers_openai

    build, _, requests, _, _, _, httpx = runtime
    provider = build(limits=Limits(request_timeout=1))
    root = provider.policy.root
    (root / "source.py").write_text("value = 1\n")
    now = [100.0]
    monkeypatch.setattr(providers_openai.time, "monotonic", lambda: now[0])

    class Stream(httpx.SyncByteStream):  # type: ignore[misc, valid-type]
        def __iter__(self) -> Any:
            yield b"{"
            if failure_mode == "timeout":
                raise httpx.ReadTimeout(KEY)
            now[0] += 2
            yield b'"partial":true'

    def handler(request: Any) -> Any:
        requests.append(request)
        return httpx.Response(200, stream=Stream())

    provider._transport = httpx.MockTransport(handler)
    config = provider.policy.config
    with Workbench(root, config=config, grants=Grant(network=True), provider=provider) as wb:
        with pytest.raises(WorkbenchError, match="OUTCOME_UNKNOWN"):
            wb.explain("value")
        exported = wb.store.export()
        assert exported["budgets"][0]["reserved"] == 1
        assert exported["intents"][0]["state"] == "unknown"
        assert exported["intents"][0]["usage"] is None
        task_id = exported["intents"][0]["task_id"]
        assert wb.task_status(task_id)["state"] == "failed"
        with pytest.raises(WorkbenchError, match="blocks replay"):
            analyze(runtime, provider)
        assert KEY not in repr(exported)
    # A fresh adapter cannot evade the persisted unresolved intent on resume.
    with Workbench(root, config=config, grants=Grant(network=True)) as reopened:
        with pytest.raises(WorkbenchError, match="OUTCOME_UNKNOWN"):
            reopened.resume(task_id)
    assert len(requests) == 1


@pytest.mark.parametrize("body", ["malformed-json", "x" * 16_001])
def test_sdk_keeps_known_invalid_and_oversized_receipts(runtime: Any, body: str) -> None:
    build, queue, requests, *_ = runtime
    provider = build()
    root = provider.policy.root
    (root / "source.py").write_text("value = 1\n")
    queue[:] = [body]
    with Workbench(
        root, config=provider.policy.config, grants=Grant(network=True), provider=provider
    ) as wb:
        with pytest.raises(WorkbenchError) as failure:
            wb.explain("value")
        assert failure.value.code in {"VALIDATION_ERROR", "LIMIT_EXCEEDED"}
        exported = wb.store.export()
        receipt = exported["intents"][0]
        assert receipt["state"] == "received"
        assert receipt["usage"]["status"] in {"invalid_response", "response_limit"}
        assert provider._unknown is False
    assert len(requests) == 1


def test_default_sdk_workflow_bounds_source_and_preserves_shared_provenance(runtime: Any) -> None:
    build, queue, requests, *_ = runtime
    provider = build()
    root = provider.policy.root
    line = "# value " + "word " * 20
    for name in ("a.py", "b.py"):
        (root / name).write_text("\n".join([line] * 60) + "\n")
    queue[:] = [(200, response(), {"x-request-id": "req_transport_fixture"})] * 6
    with Workbench(
        root, config=provider.policy.config, grants=Grant(network=True), provider=provider
    ) as wb:
        result = wb.plan("value")
        assert len(result["results"]) == 6
        exported = wb.store.export()
        assert len(exported["budgets"]) == 1
        assert exported["budgets"][0]["reserved"] == 6
        assert exported["budgets"][0]["root_id"] == result["task_id"]
        assert len(exported["intents"]) == 6
        for intent in exported["intents"]:
            assert intent["kind"] == "openai.responses"
            assert intent["metadata"]["model"] == "fixture-model"
            assert len(intent["metadata"]["payload_hash"]) == 64
            assert intent["usage"]["status"] == "received"
            assert intent["usage"]["response_id"] == "resp_fixture"
            assert intent["usage"]["request_id"] == "req_transport_fixture"
            assert intent["usage"]["provider_model"] == "fixture-model"
            assert (intent["usage"]["input_tokens"], intent["usage"]["output_tokens"]) == (10, 20)
        assert KEY not in repr(exported)
    with Workbench(root, config=provider.policy.config, grants=Grant(network=True)) as reopened:
        assert reopened.task_status(result["task_id"])["state"] == "succeeded"
        assert reopened.store.export()["intents"] == exported["intents"]
    assert len(requests) == 6
    for request in requests:
        assert len(request.content) <= 16_000
        context = json.loads(json.loads(request.content)["input"][0]["content"])["context"]
        assert context["retrieval"]
        for chunk in context["retrieval"]:
            citation = chunk["evidence"]
            lines = (root / citation["path"]).read_text().splitlines()
            assert chunk["text"] == "\n".join(
                lines[citation["start_line"] - 1 : citation["end_line"]]
            )


def test_sdk_shared_root_budget_rejects_child_overflow(runtime: Any) -> None:
    build, queue, requests, *_ = runtime
    provider = build(limits=Limits(provider_requests=1))
    root = provider.policy.root
    (root / "source.py").write_text("value = 1\n")
    queue[:] = [response()]
    with Workbench(
        root, config=provider.policy.config, grants=Grant(network=True), provider=provider
    ) as wb:
        with pytest.raises(WorkbenchError, match="request budget"):
            wb.plan("value")
        exported = wb.store.export()
        assert len(exported["budgets"]) == 1
        assert exported["budgets"][0]["reserved"] == 1
        assert len(exported["intents"]) == 1
    assert len(requests) == 1


@pytest.mark.parametrize("case", ["denied_grant", "other_workspace", "other_configuration"])
def test_sdk_effective_policy_cannot_be_replaced_by_adapter_policy(runtime: Any, case: str) -> None:
    build, _, requests, *_ = runtime
    provider = build()
    root = provider.policy.root
    config = provider.policy.config
    network = case != "denied_grant"
    if case == "other_workspace":
        root = root / "another-workspace"
        root.mkdir()
    if case == "other_configuration":
        config = Config(provider=ProviderConfig(name="openai", model="another-model"))
    (root / "source.py").write_text("value = 1\n")
    with Workbench(root, config=config, grants=Grant(network=network), provider=provider) as wb:
        with pytest.raises(WorkbenchError, match="POLICY_DENIED"):
            wb.explain("value")
        assert not wb.store.export()["intents"]
    assert not requests


@pytest.mark.parametrize("options", [{"limit": 0}, {"dimensions": 0}, {"query": "x" * 4097}])
def test_sdk_semantic_input_validation_precedes_paid_dispatch(runtime: Any, options: Any) -> None:
    build, _, requests, *_ = runtime
    provider = build()
    root = provider.policy.root
    (root / "source.py").write_text("value = 1\n")
    values = {"query": "value", "dimensions": 2, "limit": 5, **options}
    with Workbench(
        root, config=provider.policy.config, grants=Grant(network=True), provider=provider
    ) as wb:
        with pytest.raises(WorkbenchError, match="Invalid bounded search request"):
            wb.search(semantic=True, **values)
        assert not wb.store.export()["intents"]
    assert not requests
