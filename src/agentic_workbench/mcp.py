"""Minimal MCP stdio server exposing read-only and review-only commands.

ponytail: implements only initialize, ping, tools/list and tools/call over newline-delimited
JSON-RPC with the standard library. Adopt the official MCP SDK if prompts, resources or
server-initiated notifications are needed.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TextIO

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from . import __version__
from .errors import WorkbenchError
from .index_cache import IncrementalIndexCache
from .models import canonical_json, strict_json
from .sdk import Workbench
from .secrets import SecretRedactor
from .skills import ROLES

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
INSTRUCTIONS = (
    "Agentic Workbench tools read and review one local workspace. They never write source, "
    "run tests or approve proposals; approval digests are host actions outside this server."
)
_TEXT = {"type": "string", "minLength": 1, "maxLength": 4096}
_TOOLS: dict[str, tuple[str, dict[str, Any], tuple[str, ...]]] = {
    "scan": (
        "Offline workspace inventory: files, languages, frameworks, Python symbols and calls.",
        {},
        (),
    ),
    "explain": (
        "Cited explanation of a file path, symbol name or query with static symbol tracing.",
        {"target": _TEXT},
        ("target",),
    ),
    "search": (
        "Lexical search over current source chunks, cited by path, line span and hash.",
        {"query": _TEXT, "limit": {"type": "integer", "minimum": 1, "maximum": 50}},
        ("query",),
    ),
    "plan": (
        "Coordinated discovery, analysis, engineering and testing plan. Returns proposal IDs "
        "and never writes source.",
        {"instruction": _TEXT},
        ("instruction",),
    ),
    "run": (
        "Invoke one agent role independently.",
        {"role": {"type": "string", "enum": list(ROLES)}, "instruction": _TEXT},
        ("role", "instruction"),
    ),
    "status": ("Persisted state and result of one task.", {"task_id": _TEXT}, ("task_id",)),
    "review": (
        "Diff and digest of one stored proposal. Approval happens outside this server.",
        {"proposal_id": _TEXT},
        ("proposal_id",),
    ),
    "impact": (
        "Cited static impact of changing indexed files: their definitions, callers, imports, "
        "references and test references. Paths guide analysis only; they grant nothing.",
        {
            "paths": {
                "type": "array",
                "items": _TEXT,
                "minItems": 1,
                "maxItems": 20,
                "uniqueItems": True,
            },
            "limit": {"type": "integer", "minimum": 1, "maximum": 50},
        },
        ("paths",),
    ),
}


def _schema(name: str) -> dict[str, Any]:
    _, properties, required = _TOOLS[name]
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


def _result(identifier: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": identifier, "result": result}


def _error(identifier: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": identifier, "error": {"code": code, "message": message}}


class Server:
    def __init__(
        self, factory: Callable[[], Workbench], *, redactor: SecretRedactor | None = None
    ) -> None:
        self.factory = factory
        self.redactor = redactor or SecretRedactor.from_environment()
        # One cache for the server's lifetime: each call still opens, rereads and closes.
        self.index_cache = IncrementalIndexCache()

    def tools(self) -> list[dict[str, Any]]:
        return [
            {"name": name, "description": description, "inputSchema": _schema(name)}
            for name, (description, _, _) in _TOOLS.items()
        ]

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        with self.factory() as wb:
            wb.index_cache = self.index_cache
            if name == "scan":
                data = wb.scan()
            elif name == "explain":
                data = wb.explain(arguments["target"])
            elif name == "search":
                data = wb.search(arguments["query"], limit=arguments.get("limit", 5))
            elif name == "plan":
                data = wb.plan(arguments["instruction"])
            elif name == "run":
                data = wb.run_agent(arguments["role"], arguments["instruction"])
            elif name == "status":
                data = wb.task_status(arguments["task_id"])
            elif name == "impact":
                data = wb.impact(arguments["paths"], limit=arguments.get("limit", 20))
            else:
                data = wb.review(arguments["proposal_id"])
        cleaned: dict[str, Any] = self.redactor.clean(data)
        return cleaned

    def handle(self, message: Any) -> dict[str, Any] | None:
        if (
            not isinstance(message, dict)
            or message.get("jsonrpc") != "2.0"
            or not isinstance(message.get("method"), str)
        ):
            identifier = message.get("id") if isinstance(message, dict) else None
            return _error(identifier, -32600, "Invalid request")
        if "id" not in message:
            return None
        identifier, method = message["id"], message["method"]
        params = message.get("params")
        params = params if isinstance(params, dict) else {}
        if method == "initialize":
            requested = params.get("protocolVersion")
            version = requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
            return _result(
                identifier,
                {
                    "protocolVersion": version,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "agentic-workbench", "version": __version__},
                    "instructions": INSTRUCTIONS,
                },
            )
        if method == "ping":
            return _result(identifier, {})
        if method == "tools/list":
            return _result(identifier, {"tools": self.tools()})
        if method != "tools/call":
            return _error(identifier, -32601, "Method not found")
        name, arguments = params.get("name"), params.get("arguments", {})
        if not isinstance(name, str) or name not in _TOOLS or not isinstance(arguments, dict):
            return _error(identifier, -32602, "Unknown tool or invalid arguments")
        try:
            Draft202012Validator(_schema(name)).validate(arguments)
        except ValidationError:
            return _error(identifier, -32602, "Invalid tool arguments")
        try:
            data = self.call(name, arguments)
        except WorkbenchError as error:
            failure = error.to_dict()
        except (OSError, UnicodeError, ValueError, TypeError, KeyError):
            failure = {
                "code": "OPERATION_FAILED",
                "message": "Operation failed at an input or filesystem boundary",
                "retryable": False,
            }
        else:
            return _result(
                identifier,
                {
                    "content": [{"type": "text", "text": canonical_json(data)}],
                    "structuredContent": data,
                    "isError": False,
                },
            )
        return _result(
            identifier,
            {
                "content": [{"type": "text", "text": str(failure["message"])}],
                "structuredContent": {"error": failure},
                "isError": True,
            },
        )

    def serve(self, reader: TextIO, writer: TextIO) -> int:
        maximum = 1_048_576
        while line := reader.readline(maximum + 1):
            if len(line) > maximum or len(line.encode("utf-8", "surrogateescape")) > maximum:
                writer.write(
                    canonical_json(_error(None, -32700, "Frame exceeds byte limit")) + "\n"
                )
                writer.flush()
                return 2
            if not line.strip():
                continue
            try:
                response = self.handle(strict_json(line))
            except WorkbenchError:
                response = _error(None, -32700, "Parse error")
            if response is not None:
                writer.write(canonical_json(response) + "\n")
                writer.flush()
        return 0
