"""Contract tests for the documented MCP editor recipes, on a real stdio server."""

import hashlib
import importlib.util
import json
import os
import re
import select
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from agentic_workbench.mcp import PROTOCOL_VERSIONS

REPOSITORY = Path(__file__).resolve().parents[1]
EXAMPLES = REPOSITORY / "examples/integrations/mcp"
DOCS = REPOSITORY / "docs/integrations/mcp-editors.md"
VERIFIER = REPOSITORY / "scripts/verify_mcp_integration.py"
AGENTIC = "/absolute/path/to/venv/bin/agentic"
ROOT = "/absolute/path/to/application"
# Example file -> the top-level key under which that host reads its servers.
HOSTS = {
    "claude-code.mcp.json": "mcpServers",
    "vscode.mcp.json": "servers",
    "cursor.mcp.json": "mcpServers",
}
FORBIDDEN = {"apply", "rollback", "test", "execute", "approve", "repair", "write", "edit"}
MESSAGES: list[dict[str, Any]] = [
    {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "recipe-contract", "version": "1"},
        },
    },
    {"jsonrpc": "2.0", "method": "notifications/initialized"},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {"name": "search", "arguments": {"query": "double"}},
    },
    {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {"name": "apply", "arguments": {}},
    },
]


def synthetic(tmp_path: Path) -> Path:
    root = tmp_path / "application"
    root.mkdir()
    (root / "app.py").write_text("def double(x):\n    return x * 2\n")
    (root / "test_app.py").write_text("from app import double\n\nassert double(2) == 4\n")
    return root


def source(root: Path) -> dict[str, str]:
    # The server keeps its own private state under .agentic; source must never change.
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file() and ".agentic" not in path.parts
    }


def converse(command: list[str], messages: list[dict[str, Any]]) -> dict[Any, dict[str, Any]]:
    done = subprocess.run(
        command,
        input="".join(json.dumps(message) + "\n" for message in messages),
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, "PYTHONPATH": str(REPOSITORY / "src")},
        check=False,
    )
    assert done.returncode == 0, done.stderr
    return {reply.get("id"): reply for reply in map(json.loads, done.stdout.splitlines())}


def documented_tools() -> set[str]:
    return set(re.findall(r"^\| `([a-z_]+)` \|", DOCS.read_text(), re.MULTILINE))


@pytest.mark.parametrize("name", sorted(HOSTS))
def test_each_example_launches_only_the_offline_read_only_server(name: str) -> None:
    config = json.loads((EXAMPLES / name).read_text())
    assert list(config) == [HOSTS[name]]
    [(server, entry)] = config[HOSTS[name]].items()
    assert server == "agentic" and entry["command"] == AGENTIC
    # --provider none keeps a project's provider configuration from enabling inference.
    assert entry["args"] == ["mcp", "--root", ROOT, "--provider", "none"]
    assert set(entry) <= {"type", "command", "args"} and entry.get("type", "stdio") == "stdio"


@pytest.mark.parametrize("name", sorted(HOSTS))
def test_each_example_serves_documented_read_only_tools_over_stdio(
    tmp_path: Path, name: str
) -> None:
    root = synthetic(tmp_path)
    before = source(root)
    [entry] = json.loads((EXAMPLES / name).read_text())[HOSTS[name]].values()
    args = [str(root) if arg == ROOT else arg for arg in entry["args"]]
    replies = converse([sys.executable, "-m", "agentic_workbench.cli", *args], MESSAGES)
    initialized = replies[1]["result"]
    assert initialized["protocolVersion"] in PROTOCOL_VERSIONS
    assert initialized["capabilities"] == {"tools": {}}
    assert "never write source" in initialized["instructions"]
    tools = replies[2]["result"]["tools"]
    names = {tool["name"] for tool in tools}
    assert names == documented_tools() and not names & FORBIDDEN
    assert all(tool["inputSchema"]["additionalProperties"] is False for tool in tools)
    found = replies[3]["result"]
    assert found["isError"] is False
    digest = hashlib.sha256((root / "app.py").read_bytes()).hexdigest()
    assert any(
        chunk["evidence"] == {**chunk["evidence"], "path": "app.py", "source_hash": digest}
        for chunk in found["structuredContent"]["chunks"]
    )
    assert replies[4]["error"]["code"] == -32602
    assert source(root) == before


def test_the_host_check_relay_is_transparent_and_records_no_payloads(tmp_path: Path) -> None:
    root = synthetic(tmp_path)
    log = tmp_path / "relay.jsonl"
    server = [sys.executable, "-m", "agentic_workbench.cli", "mcp", "--root", str(root)]
    server += ["--provider", "none"]
    direct = converse(server, MESSAGES)
    wrapped = [sys.executable, str(VERIFIER), "--relay", str(log), "--", *server]
    relayed = converse(wrapped, MESSAGES)
    assert relayed == direct
    records = [json.loads(line) for line in log.read_text().splitlines()]
    sent = [record["method"] for record in records if record["direction"] == "host"]
    assert sent == [message["method"] for message in MESSAGES]
    assert all(set(record) <= {"direction", "kind", "method", "id", "bytes"} for record in records)
    assert "double" not in log.read_text()


def test_the_host_check_fails_closed_without_the_host(tmp_path: Path) -> None:
    done = subprocess.run(
        [sys.executable, str(VERIFIER), "--claude", str(tmp_path / "missing"), "--output"]
        + [str(tmp_path / "receipt")],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert done.returncode != 0 and "claude" in done.stderr.lower()


@pytest.mark.skipif(os.name != "posix", reason="SIGINT subprocess protocol check requires POSIX")
def test_mcp_sigint_exits_without_a_cli_envelope(tmp_path: Path) -> None:
    root = synthetic(tmp_path)
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "agentic_workbench.cli",
            "mcp",
            "--root",
            str(root),
            "--provider",
            "none",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, "PYTHONPATH": str(REPOSITORY / "src")},
    )
    try:
        assert process.stdin is not None and process.stdout is not None
        process.stdin.write(json.dumps(MESSAGES[0]) + "\n")
        process.stdin.flush()
        assert select.select([process.stdout], [], [], 10)[0]
        assert json.loads(process.stdout.readline())["id"] == 1
        process.send_signal(signal.SIGINT)
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 130
        assert stdout == "" and "Traceback" not in stderr
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()


def test_host_check_preserves_existing_output(tmp_path: Path) -> None:
    output = tmp_path / "receipt"
    output.mkdir()
    marker = output / "keep.txt"
    marker.write_text("existing evidence")
    # Host prerequisite checks may fail before the fresh-output check on non-macOS.
    done = subprocess.run(
        [sys.executable, str(VERIFIER), "--claude", sys.executable, "--output", str(output)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert done.returncode != 0 and marker.read_text() == "existing evidence"


@pytest.mark.skipif(os.name != "posix", reason="Process-group cleanup requires POSIX")
def test_host_timeout_stops_descendants(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location("mcp_host_verifier", VERIFIER)
    assert spec is not None and spec.loader is not None
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    marker = tmp_path / "heartbeat"
    child = "import time; from pathlib import Path; p=Path(" + repr(str(marker)) + "); "
    child += 'exec("while True:\\n p.write_text(str(time.monotonic())); time.sleep(0.03)")'
    parent = (
        "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',"
        + repr(child)
        + "]);time.sleep(30)"
    )
    with pytest.raises(subprocess.TimeoutExpired):
        verifier.host_step(
            [sys.executable, "-c", parent], timeout=1, env=dict(os.environ), cwd=tmp_path
        )
    assert marker.exists()
    value = marker.read_text()
    time.sleep(0.1)
    assert marker.read_text() == value
