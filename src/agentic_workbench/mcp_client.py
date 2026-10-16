"""Bounded stdio MCP client for explicitly reviewed trusted-host processes."""

from __future__ import annotations

import os
import select
import selectors
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from .config import CommandConfig
from .errors import WorkbenchError
from .models import canonical_hash, canonical_json, strict_json
from .policy import WorkspacePolicy


class StdioMCPClient:
    """Process separation, sanitized environment and hard termination; no OS sandbox.

    Register as an execute tool with reviewer=client.review. The host approves the
    exact executable/argv. Sandboxed executable tools instead use Runner bindings.
    """

    execution_effect = "execute"

    def __init__(self, policy: WorkspacePolicy, argv: tuple[str, ...]) -> None:
        CommandConfig(argv)
        self.policy, self.argv = policy, argv

    def review(self, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        if os.name != "posix":
            raise WorkbenchError("INTEGRATION_UNAVAILABLE", "Stdio MCP process control needs POSIX")
        if not (self.policy.grants.execute and self.policy.grants.trusted_host):
            raise WorkbenchError(
                "POLICY_DENIED", "Stdio MCP requires explicit trusted-host execution"
            )
        resolved = shutil.which(self.argv[0])
        if resolved is None:
            raise WorkbenchError("INTEGRATION_UNAVAILABLE", "MCP executable is unavailable")
        executable = Path(resolved).resolve(strict=True)
        # Keep executable review bounded; do not trust repository-relative executables.
        if executable.is_relative_to(self.policy.root) or not executable.is_file():
            raise WorkbenchError("POLICY_DENIED", "MCP executable must be host-installed")
        info = executable.stat()
        if info.st_size > 64 * 1024 * 1024:
            raise WorkbenchError("LIMIT_EXCEEDED", "MCP executable exceeds review size")
        import hashlib

        files = {}
        for argument in self.argv[1:]:
            if argument.startswith("-") or len(argument) > 4096:
                continue
            try:
                path = Path(argument)
                path = path if path.is_absolute() else self.policy.root / path
                if not os.path.isfile(path):
                    continue
                path = path.resolve(strict=True)
                if path.is_relative_to(self.policy.root):
                    raise WorkbenchError(
                        "POLICY_DENIED", "MCP cannot execute repository file arguments"
                    )
                if path.stat().st_size > 64 * 1024 * 1024:
                    raise WorkbenchError("LIMIT_EXCEEDED", "MCP argument file exceeds review size")
                files[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                raise WorkbenchError("POLICY_DENIED", "MCP argument file is unavailable") from None
        record = {
            "executable": str(executable),
            "executable_hash": hashlib.sha256(executable.read_bytes()).hexdigest(),
            "argv": list(self.argv),
            "argument_files": files,
            "policy": self.policy.fingerprint,
            "isolation": "trusted-host-process",
        }
        return {**record, "digest": canonical_hash(record)}

    def _session(
        self, method: str, parameters: dict[str, Any], timeout: float, limit: int = 64_000
    ) -> dict[str, Any]:
        review = self.review()
        deadline = time.monotonic() + timeout
        messages: list[dict[str, Any]] = [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "agentic-workbench", "version": "1"},
                },
            },
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": method, "params": parameters},
        ]
        with tempfile.TemporaryDirectory(prefix="agentic-mcp-") as directory:
            environment = {"HOME": directory, "TMPDIR": directory, "LANG": "C.UTF-8"}
            process = subprocess.Popen(  # noqa: S603 - exact host-reviewed argv, shell disabled
                [review["executable"], *self.argv[1:]],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=directory,
                env=environment,
                start_new_session=True,
            )
            assert process.stdin and process.stdout and process.stderr
            selector = selectors.DefaultSelector()
            total = 0
            buffer = bytearray()
            try:
                os.set_blocking(process.stdin.fileno(), False)
                for stream in (process.stdout, process.stderr):
                    os.set_blocking(stream.fileno(), False)
                    selector.register(stream, selectors.EVENT_READ)

                def send(message: dict[str, Any]) -> None:
                    assert process.stdin
                    payload = memoryview((canonical_json(message) + "\n").encode())
                    if len(payload) > 1_048_576:
                        # Nothing was sent: a known refusal, not an unknown effect.
                        raise WorkbenchError(
                            "TOOL_REJECTED", "MCP request frame exceeds byte limit"
                        )
                    while payload:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise WorkbenchError("OUTCOME_UNKNOWN", "MCP input deadline elapsed")
                        _, writable, _ = select.select(
                            [], [process.stdin.fileno()], [], min(0.1, remaining)
                        )
                        if writable:
                            try:
                                count = os.write(process.stdin.fileno(), payload)
                                payload = payload[count:]
                            except BlockingIOError:
                                continue

                send(messages[0])
                initialized = False
                while time.monotonic() < deadline:
                    for key, _ in selector.select(min(0.1, max(0, deadline - time.monotonic()))):
                        block = os.read(key.fd, 4096)
                        if not block:
                            selector.unregister(key.fileobj)
                            continue
                        total += len(block)
                        if total > limit:
                            raise WorkbenchError("OUTCOME_UNKNOWN", "MCP output exceeded its limit")
                        if key.fileobj is not process.stdout:
                            continue
                        buffer.extend(block)
                        while b"\n" in buffer:
                            line, _, remainder = buffer.partition(b"\n")
                            buffer[:] = remainder
                            item = strict_json(line.decode("utf-8"), max_bytes=limit)
                            if not isinstance(item, dict) or item.get("jsonrpc") != "2.0":
                                raise WorkbenchError("OUTCOME_UNKNOWN", "Invalid MCP frame")
                            if "id" not in item:
                                continue
                            expected = 2 if initialized else 1
                            if item.get("id") != expected or "error" in item:
                                raise WorkbenchError("OUTCOME_UNKNOWN", "Unexpected MCP response")
                            result = item.get("result")
                            if not isinstance(result, dict):
                                raise WorkbenchError("OUTCOME_UNKNOWN", "Invalid MCP result")
                            if not initialized:
                                if result.get("protocolVersion") != "2025-11-25":
                                    raise WorkbenchError(
                                        "INTEGRATION_UNAVAILABLE", "Unsupported MCP version"
                                    )
                                initialized = True
                                send(messages[1])
                                send(messages[2])
                            else:
                                return result
                    if process.poll() is not None and not selector.get_map():
                        break
                raise WorkbenchError("OUTCOME_UNKNOWN", "MCP stopped without a complete receipt")
            except (OSError, UnicodeError):
                raise WorkbenchError("OUTCOME_UNKNOWN", "MCP process transport stopped") from None
            finally:
                selector.close()
                # Kill descendants even if the MCP parent has exited.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=5)
                process.stdin.close()
                process.stdout.close()
                process.stderr.close()

    def list_tools(self, *, timeout: float = 30) -> list[dict[str, Any]]:
        result = self._session("tools/list", {}, timeout)
        tools = result.get("tools")
        if (
            not isinstance(tools, list)
            or len(tools) > 64
            or not all(isinstance(t, dict) for t in tools)
        ):
            raise WorkbenchError("VALIDATION_ERROR", "Invalid MCP discovery result")
        return tools

    def call_tool(
        self, name: str, arguments: dict[str, Any], *, timeout: float, limit: int = 64_000
    ) -> dict[str, Any]:
        """``limit`` bounds process output: model context for reads, receipts for effects."""
        result = self._session("tools/call", {"name": name, "arguments": arguments}, timeout, limit)
        if result.get("isError") is True:
            raise WorkbenchError(
                "OUTCOME_UNKNOWN", "MCP tool returned an error without an effect receipt"
            )
        structured = result.get("structuredContent")
        if not isinstance(structured, dict):
            raise WorkbenchError("VALIDATION_ERROR", "MCP tool requires structured JSON content")
        return structured
