import io
import json
import os
import sys
import time
from pathlib import Path

import pytest

from agentic_workbench import CommandConfig, Config, Grant, WorkbenchError
from agentic_workbench.mcp_client import StdioMCPClient
from agentic_workbench.policy import WorkspacePolicy
from agentic_workbench.state import StateStore
from agentic_workbench.tool_backends import JSONAPI
from agentic_workbench.tool_registry import ToolRegistry, ToolSpec

EMPTY = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}


def test_named_python_tool_uses_approved_snapshot_runner(tmp_path: Path) -> None:
    (tmp_path / "probe.py").write_text("print('actual isolated copy')\n")
    config = Config(commands={"probe": CommandConfig((sys.executable, "probe.py"))})
    policy = WorkspacePolicy(tmp_path, config, grants=Grant(execute=True, trusted_host=True))
    with StateStore(policy) as store:
        registry = ToolRegistry(policy, store)
        registry.register_command("python_probe", "probe", backend="trusted-host", python=True)
        reviewed = registry.review("python_probe", {})
        assert reviewed["external_review"]["backend"] == "trusted-host"
        result = registry.invoke(
            "python_probe", {}, approval=reviewed["digest"], idempotency_key="probe-1"
        )
        assert result.data is not None and result.data["exit_code"] == 0
        assert "actual isolated copy" in result.data["stdout"]
        assert (tmp_path / "probe.py").exists()
        assert "python_probe" not in registry.scoped(()).allowed


def test_fixed_https_api_grants_credentials_and_bounded_json(tmp_path: Path) -> None:
    secret = "synthetic-api-credential"
    seen = []

    class Response(io.BytesIO):
        def geturl(self):
            return "https://api.example.test/read"

    class Opener:
        def open(self, request, *, timeout):
            seen.append((request, timeout))
            return Response(json.dumps({"echo": secret, "value": 1}).encode())

    policy = WorkspacePolicy(
        tmp_path, grants=Grant(network=True, provider_hosts=("api.example.test",))
    )
    with StateStore(policy) as store:
        registry = ToolRegistry(policy, store)
        api = JSONAPI(
            policy, "https://api.example.test/read", credential=lambda: secret, opener=Opener()
        )
        api.register(
            registry,
            ToolSpec(
                "api_read",
                "Approved API read",
                EMPTY,
                {"type": "object"},
                backend="api",
                destination="api.example.test",
                model_visible=True,
            ),
        )
        result = registry.scoped(()).execute("api_read", {})
        assert result["echo"] == "[REDACTED]" and seen[0][1] <= 30
        assert seen[0][0].get_header("Authorization") == "Bearer " + secret
    with pytest.raises(WorkbenchError, match="CONFIG_ERROR"):
        JSONAPI(policy, "http://api.example.test/read")
    denied = WorkspacePolicy(tmp_path)
    with pytest.raises(WorkbenchError, match="POLICY_DENIED"):
        JSONAPI(denied, "https://api.example.test/read", opener=Opener()).request({}, timeout=1)
    with pytest.raises(WorkbenchError, match="POLICY_DENIED"):
        api.request({"echo": secret}, timeout=1)


MCP_FIXTURE = """
import json, sys
for line in sys.stdin:
    item = json.loads(line)
    if 'id' not in item:
        continue
    if item['method'] == 'initialize':
        result = {'protocolVersion':'2025-11-25', 'capabilities':{'tools':{}},
                  'serverInfo':{'name':'fixture','version':'1'}}
    elif item['method'] == 'tools/list':
        result = {'tools':[{'name':'counter', 'description':'Fixture counter',
                           'inputSchema':{'type':'object'}}]}
    else:
        result = {'structuredContent':{'value':item['params']['arguments'].get('value', 7)},
                  'content':[], 'isError':False}
    print(json.dumps({'jsonrpc':'2.0','id':item['id'],'result':result}), flush=True)
"""


def test_real_stdio_mcp_handshake_discovery_call_and_timeout(tmp_path: Path) -> None:
    policy = WorkspacePolicy(tmp_path, grants=Grant(execute=True, trusted_host=True))
    client = StdioMCPClient(policy, (sys.executable, "-c", f"exec({MCP_FIXTURE!r})"))
    assert client.list_tools(timeout=3)[0]["name"] == "counter"
    with StateStore(policy) as store:
        registry = ToolRegistry(policy, store)
        registry.register_mcp(
            ToolSpec(
                "mcp_counter",
                "Reviewed MCP process",
                EMPTY,
                {"type": "object"},
                backend="mcp",
                effect="execute",
            ),
            client,
            "counter",
            reviewer=client.review,
        )
        digest = registry.review("mcp_counter", {})["digest"]
        assert registry.invoke(
            "mcp_counter", {}, approval=digest, idempotency_key="mcp-1"
        ).data == {"value": 7}
    hung = StdioMCPClient(policy, (sys.executable, "-c", "import time; time.sleep(30)"))
    with pytest.raises(WorkbenchError, match="OUTCOME_UNKNOWN"):
        hung.call_tool("counter", {}, timeout=0.1)


def test_mcp_nonreading_stdin_cannot_escape_total_deadline(tmp_path: Path) -> None:
    policy = WorkspacePolicy(tmp_path, grants=Grant(execute=True, trusted_host=True))
    source = (
        "import json,sys,time; request=json.loads(sys.stdin.readline()); "
        "print(json.dumps({'jsonrpc':'2.0','id':1,"
        "'result':{'protocolVersion':'2025-11-25'}}),flush=True); "
        "time.sleep(30)"
    )
    client = StdioMCPClient(policy, (sys.executable, "-c", source))
    started = time.monotonic()
    with pytest.raises(WorkbenchError, match="OUTCOME_UNKNOWN"):
        client.call_tool("counter", {"payload": "x" * 500_000}, timeout=0.2)
    assert time.monotonic() - started < 3


def test_mcp_process_requires_execution_effect_and_pins_file_arguments(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    script = tmp_path / "server.py"
    script.write_text("print('first')\n")
    policy = WorkspacePolicy(root, grants=Grant(execute=True, trusted_host=True))
    client = StdioMCPClient(policy, (sys.executable, str(script)))
    before = client.review()["digest"]
    script.write_text("print('second')\n")
    assert client.review()["digest"] != before
    (root / "server.py").write_text("print('untrusted')\n")
    with pytest.raises(WorkbenchError, match="POLICY_DENIED"):
        StdioMCPClient(policy, (sys.executable, str(root / "server.py"))).review()
    with StateStore(policy) as store:
        registry = ToolRegistry(policy, store)
        with pytest.raises(WorkbenchError, match="CONFIG_ERROR"):
            registry.register_mcp(
                ToolSpec(
                    "mcp",
                    "Unsafe model process",
                    EMPTY,
                    {"type": "object"},
                    backend="mcp",
                    model_visible=True,
                ),
                client,
                "counter",
            )


def _slow_http_worker(connection, url, headers, body, timeout, limit):
    # Same signature as tool_backends._http_request; a mismatch would crash before the marker.
    Path(json.loads(body)["started"]).write_text(str(os.getpid()))
    time.sleep(30)


def test_api_worker_enforces_hard_total_deadline(tmp_path: Path, monkeypatch) -> None:
    from agentic_workbench import tool_backends

    policy = WorkspacePolicy(
        tmp_path, grants=Grant(network=True, provider_hosts=("api.example.test",))
    )
    monkeypatch.setattr(tool_backends, "_http_request", _slow_http_worker)
    marker = tmp_path / "worker-started"
    started = time.monotonic()
    with pytest.raises(WorkbenchError) as raised:
        JSONAPI(policy, "https://api.example.test/read").request(
            {"started": str(marker)}, timeout=2.0
        )
    assert raised.value.code == "OUTCOME_UNKNOWN"
    assert raised.value.message == "API total deadline elapsed"
    assert time.monotonic() - started < 4.5
    # The deadline killed the worker: it no longer runs.
    with pytest.raises(ProcessLookupError):
        os.kill(int(marker.read_text()), 0)


def _expanding_http_worker(connection, url, headers, body, timeout, limit):
    from agentic_workbench import tool_backends

    # Runs in the spawned worker: only the HTTP response is replaced; the real worker
    # redacts it and sends its envelope through the real pipe.
    tool_backends._http_result = lambda *args, **kwargs: {"items": [{"token": "x"}] * 60_000}
    tool_backends._http_request(connection, url, headers, body, timeout, limit)


def test_api_effect_receipt_survives_redaction_growth_across_the_worker_pipe(
    tmp_path: Path, monkeypatch
) -> None:
    from agentic_workbench import tool_backends

    policy = WorkspacePolicy(
        tmp_path, grants=Grant(write=True, network=True, provider_hosts=("api.example.test",))
    )
    monkeypatch.setattr(tool_backends, "_http_request", _expanding_http_worker)
    with StateStore(policy) as store:
        registry = ToolRegistry(policy, store)
        spec = ToolSpec(
            "api_write",
            "Write API",
            EMPTY,
            {"type": "object"},
            backend="api",
            effect="write",
            destination="api.example.test",
        )
        JSONAPI(policy, "https://api.example.test/write").register(registry, spec)
        digest = registry.review("api_write", {})["digest"]
        first = registry.invoke("api_write", {}, approval=digest, idempotency_key="w")
        assert first.status == "succeeded" and first.data is not None
        assert len(first.data["items"]) == 60_000
        assert first.data["items"][0] == {"token": "[REDACTED]"}
        replay = registry.invoke("api_write", {}, approval=digest, idempotency_key="w")
        assert replay.cached and replay.truncated and replay.data is not None
        assert 0 < len(replay.data["items"]) < 60_000


def _typed_http_worker(connection, url, headers, body, timeout, limit):
    from agentic_workbench import tool_backends

    # Runs in the spawned worker: typed values under secret-sounding names, as APIs return.
    tool_backends._http_result = lambda *args, **kwargs: {
        "user_id": "u1",
        "max_token": 4096,
        "rotate_secret": {"days": 30},
    }
    tool_backends._http_request(connection, url, headers, body, timeout, limit)


def test_api_effect_typed_fields_under_secret_names_keep_a_known_receipt(
    tmp_path: Path, monkeypatch
) -> None:
    from agentic_workbench import tool_backends

    policy = WorkspacePolicy(
        tmp_path, grants=Grant(write=True, network=True, provider_hosts=("api.example.test",))
    )
    monkeypatch.setattr(tool_backends, "_http_request", _typed_http_worker)
    output = {
        "type": "object",
        "properties": {"max_token": {"type": "integer"}, "rotate_secret": {"type": "object"}},
        "required": ["max_token", "rotate_secret"],
    }
    with StateStore(policy) as store:
        registry = ToolRegistry(policy, store)
        spec = ToolSpec(
            "api_write",
            "Write API",
            EMPTY,
            output,
            backend="api",
            effect="write",
            destination="api.example.test",
        )
        JSONAPI(policy, "https://api.example.test/write").register(registry, spec)
        digest = registry.review("api_write", {})["digest"]
        first = registry.invoke("api_write", {}, approval=digest, idempotency_key="w")
        # The transport keeps types for validation; the registry redacts afterwards.
        assert first.status == "succeeded" and first.data == {
            "user_id": "u1",
            "max_token": "[REDACTED]",
            "rotate_secret": "[REDACTED]",
        }
        assert registry.invoke("api_write", {}, approval=digest, idempotency_key="w").cached


def test_api_effect_approval_binds_full_endpoint(tmp_path: Path) -> None:
    policy = WorkspacePolicy(
        tmp_path, grants=Grant(write=True, network=True, provider_hosts=("api.example.test",))
    )
    with StateStore(policy) as store:
        spec = ToolSpec(
            "api_write",
            "Write API",
            EMPTY,
            {"type": "object"},
            backend="api",
            effect="write",
            destination="api.example.test",
        )
        first, second = ToolRegistry(policy, store), ToolRegistry(policy, store)
        JSONAPI(policy, "https://api.example.test/a").register(first, spec)
        JSONAPI(policy, "https://api.example.test/b").register(second, spec)
        digest = first.review("api_write", {})["digest"]
        with pytest.raises(WorkbenchError, match="STALE_APPROVAL"):
            second.invoke("api_write", {}, approval=digest, idempotency_key="write")


def test_mcp_approval_binds_remote_tool_name(tmp_path: Path) -> None:
    policy = WorkspacePolicy(tmp_path, grants=Grant(execute=True, trusted_host=True))
    client = StdioMCPClient(policy, (sys.executable, "-c", f"exec({MCP_FIXTURE!r})"))
    with StateStore(policy) as store:
        first, second = ToolRegistry(policy, store), ToolRegistry(policy, store)
        spec = ToolSpec(
            "mcp_action",
            "Reviewed process action",
            EMPTY,
            {"type": "object"},
            backend="mcp",
            effect="execute",
        )
        first.register_mcp(spec, client, "read", reviewer=client.review)
        second.register_mcp(spec, client, "write", reviewer=client.review)
        digest = first.review("mcp_action", {})["digest"]
        with pytest.raises(WorkbenchError, match="STALE_APPROVAL"):
            second.invoke("mcp_action", {}, approval=digest, idempotency_key="action")


def test_api_effect_receipts_are_not_capped_at_the_model_context_limit(tmp_path: Path) -> None:
    body = {"items": ["v" * 100] * 130}

    class Response(io.BytesIO):
        def geturl(self):
            return "https://api.example.test/write"

    class Opener:
        calls = 0

        def open(self, request, *, timeout):
            Opener.calls += 1
            return Response(json.dumps(body).encode())

    policy = WorkspacePolicy(
        tmp_path, grants=Grant(write=True, network=True, provider_hosts=("api.example.test",))
    )
    with StateStore(policy) as store:
        registry = ToolRegistry(policy, store)
        spec = ToolSpec(
            "api_write",
            "Write API",
            EMPTY,
            {"type": "object"},
            backend="api",
            effect="write",
            destination="api.example.test",
        )
        JSONAPI(policy, "https://api.example.test/write", opener=Opener()).register(registry, spec)
        digest = registry.review("api_write", {})["digest"]
        assert registry.invoke("api_write", {}, approval=digest, idempotency_key="w").data == body
        assert registry.invoke("api_write", {}, approval=digest, idempotency_key="w").cached
        assert Opener.calls == 1


def test_mcp_effect_results_are_not_capped_at_the_model_context_limit(tmp_path: Path) -> None:
    policy = WorkspacePolicy(tmp_path, grants=Grant(execute=True, trusted_host=True))
    client = StdioMCPClient(policy, (sys.executable, "-c", f"exec({MCP_FIXTURE!r})"))
    schema = {
        "type": "object",
        "properties": {"value": {"type": "string"}},
        "required": ["value"],
        "additionalProperties": False,
    }
    with StateStore(policy) as store:
        registry = ToolRegistry(policy, store)
        spec = ToolSpec(
            "mcp_action",
            "Reviewed process action",
            schema,
            {"type": "object"},
            backend="mcp",
            effect="execute",
        )
        registry.register_mcp(spec, client, "counter", reviewer=client.review)
        arguments = {"value": "v" * 100_000}
        digest = registry.review("mcp_action", arguments)["digest"]
        first = registry.invoke("mcp_action", arguments, approval=digest, idempotency_key="one")
        assert first.status == "succeeded" and first.data == {"value": "v" * 100_000}
        assert registry.invoke(
            "mcp_action", arguments, approval=digest, idempotency_key="one"
        ).cached
