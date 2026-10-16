import io
import json
from pathlib import Path
from typing import Any

from agentic_workbench.mcp import Server
from agentic_workbench.sdk import Workbench


def _serve(root: Path, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    server = Server(lambda: Workbench(root))
    reader = io.StringIO("".join(json.dumps(m) + "\n" for m in messages) + "\n{not json\n")
    writer = io.StringIO()
    assert server.serve(reader, writer) == 0
    return [json.loads(line) for line in writer.getvalue().splitlines()]


def test_mcp_handshake_tool_listing_and_read_only_calls(tmp_path: Path) -> None:
    source = "def total(x):\n    return x\n"
    (tmp_path / "app.py").write_text(source)
    responses = _serve(
        tmp_path,
        [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2024-11-05", "capabilities": {}},
            },
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "explain", "arguments": {"target": "total"}},
            },
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "apply"}},
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {"name": "status", "arguments": {"task_id": "missing"}},
            },
            {"jsonrpc": "2.0", "id": 6, "method": "resources/list"},
            {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {"name": "search", "arguments": {"query": "total", "limit": 0}},
            },
        ],
    )
    by_id = {response.get("id"): response for response in responses}
    assert len(responses) == 8
    assert by_id[1]["result"]["protocolVersion"] == "2024-11-05"
    assert by_id[1]["result"]["capabilities"] == {"tools": {}}
    tools = by_id[2]["result"]["tools"]
    assert {t["name"] for t in tools} == {
        "scan",
        "explain",
        "search",
        "plan",
        "run",
        "status",
        "review",
        "impact",
    }
    assert all(t["inputSchema"]["additionalProperties"] is False for t in tools)
    explained = by_id[3]["result"]
    assert explained["isError"] is False
    assert explained["structuredContent"]["mode"] == "static"
    assert "Traced total" in explained["structuredContent"]["summary"]
    assert json.loads(explained["content"][0]["text"]) == explained["structuredContent"]
    assert by_id[4]["error"]["code"] == -32602
    assert by_id[5]["result"]["isError"] is True
    assert "error" in by_id[5]["result"]["structuredContent"]
    assert by_id[6]["error"]["code"] == -32601
    assert by_id[7]["error"]["code"] == -32602
    assert by_id[None]["error"]["code"] == -32700
    assert (tmp_path / "app.py").read_text() == source


def test_mcp_server_bounds_frames_and_stops_before_following_messages(tmp_path: Path) -> None:
    server = Server(lambda: Workbench(tmp_path))
    reader = io.StringIO("x" * 1_048_577 + '\n{"jsonrpc":"2.0","id":1,"method":"ping"}\n')
    writer = io.StringIO()
    assert server.serve(reader, writer) == 2
    response = json.loads(writer.getvalue())
    assert response["id"] is None and response["error"]["code"] == -32700
    assert "Frame" in response["error"]["message"]


def test_malformed_tool_names_return_invalid_params_and_serving_continues(tmp_path: Path) -> None:
    names = ["[]", "{}", "1", "null"]
    frames = [
        f'{{"jsonrpc":"2.0","id":{i},"method":"tools/call","params":{{"name":{name}}}}}'
        for i, name in enumerate(names)
    ]
    reader = io.StringIO("\n".join([*frames, '{"jsonrpc":"2.0","id":9,"method":"ping"}']) + "\n")
    writer = io.StringIO()
    Server(lambda: Workbench(tmp_path)).serve(reader, writer)
    responses = [json.loads(line) for line in writer.getvalue().splitlines()]
    assert [r["error"]["code"] for r in responses[:4]] == [-32602] * 4
    assert responses[4] == {"jsonrpc": "2.0", "id": 9, "result": {}}


def test_an_undecodable_frame_returns_a_parse_error_and_serving_continues(tmp_path: Path) -> None:
    raw = b'\xff\xfe not utf-8\n{"jsonrpc":"2.0","id":2,"method":"ping"}\n'
    reader = io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8", errors="surrogateescape")
    writer = io.StringIO()
    Server(lambda: Workbench(tmp_path)).serve(reader, writer)
    responses = [json.loads(line) for line in writer.getvalue().splitlines()]
    assert responses[0]["error"]["code"] == -32700
    assert responses[1] == {"jsonrpc": "2.0", "id": 2, "result": {}}


def test_cli_mcp_reads_stdin_bytes_without_crashing(tmp_path: Path) -> None:
    import subprocess
    import sys

    completed = subprocess.run(  # noqa: S603 - fixed interpreter and module
        [sys.executable, "-m", "agentic_workbench.cli", "mcp", "--root", str(tmp_path)],
        input=b'\xff\n{"jsonrpc":"2.0","id":2,"method":"ping"}\n',
        capture_output=True,
        timeout=60,
        check=False,
    )
    lines = [json.loads(line) for line in completed.stdout.decode().splitlines()]
    assert lines[-1] == {"jsonrpc": "2.0", "id": 2, "result": {}}
    assert all(line.get("jsonrpc") == "2.0" for line in lines)


def test_mcp_shares_one_index_cache_across_short_lived_workbenches(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("def double(x):\n    return x * 2\n")
    opened: list[Workbench] = []

    def factory() -> Workbench:
        opened.append(Workbench(tmp_path))
        return opened[-1]

    server = Server(factory)
    first = server.call("scan", {})["cache_stats"]
    second = server.call("scan", {})["cache_stats"]
    assert first["rebuilt"] == first["files_read"] >= 1 and first["reused"] == 0
    assert second["reused"] == second["files_read"] and second["rebuilt"] == 0
    assert len(opened) == 2 and all(wb.index_cache is server.index_cache for wb in opened)
    # Every call still reads the source afresh: an edit is rebuilt, not served stale.
    (tmp_path / "app.py").write_text("def triple(x):\n    return x * 3\n")
    third = server.call("scan", {})
    assert third["cache_stats"]["rebuilt"] == 1
    assert [s["name"] for s in third["symbols"]] == ["triple"]


def test_mcp_lists_and_runs_the_impact_tool(tmp_path: Path) -> None:
    (tmp_path / "lib.py").write_text("def total():\n    return 1\n")
    (tmp_path / "app.py").write_text("from lib import total\n\nprint(total())\n")
    server = Server(lambda: Workbench(tmp_path))
    assert "impact" in {tool["name"] for tool in server.tools()}

    def call(arguments: dict[str, Any]) -> dict[str, Any]:
        request = {"name": "impact", "arguments": arguments}
        response = server.handle(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": request}
        )
        assert response is not None
        return response

    result = call({"paths": ["lib.py"], "limit": 5})["result"]
    assert result["isError"] is False
    assert [c["evidence"]["path"] for c in result["structuredContent"]["callers"]] == ["app.py"]
    missing = call({"paths": ["missing.py"]})["result"]
    assert (
        missing["isError"] and missing["structuredContent"]["error"]["code"] == "VALIDATION_ERROR"
    )
    assert call({"paths": []})["error"]["code"] == -32602
    assert call({"paths": ["lib.py"], "limit": 51})["error"]["code"] == -32602
