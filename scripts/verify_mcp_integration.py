"""Check `agentic mcp` against the installed Claude Code host, without any model call.

Host check (macOS only):
    verify_mcp_integration.py --claude PATH --output DIR [--timeout SECONDS]
registers the read-only server in a throwaway Claude Code configuration and asks the host to
health-check it (`claude mcp list` and `claude mcp get`). The host gets a throwaway HOME and
CLAUDE_CONFIG_DIR with no credentials, outbound IP traffic denied by sandbox-exec for it and
everything it starts, and a hard timeout. It never runs a session, so no model is called.

Relay (registered as the host's server command by the check):
    verify_mcp_integration.py --relay LOG -- COMMAND...
passes stdio through unchanged and logs only each message's direction, kind, method, id and
size, never its payload. The log shows whether the host only initialized, listed tools, or
invoked one.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import subprocess
import sys
import threading
from pathlib import Path
from typing import IO, Any

PROFILE = "(version 1)(allow default)(deny network-outbound (remote ip))"
SANDBOX = Path("/usr/bin/sandbox-exec")
SOURCE = Path(__file__).resolve().parents[1] / "src"


def relay(log: Path, command: list[str]) -> int:
    # The host's registered server command, run without a shell.
    server = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE)  # noqa: S603
    lock = threading.Lock()

    def note(direction: str, line: bytes) -> None:
        entry: dict[str, Any] = {"direction": direction, "bytes": len(line)}
        try:
            message = json.loads(line)
        except ValueError:
            message = None
        if isinstance(message, dict):
            method, identifier = message.get("method"), message.get("id")
            entry["kind"] = (
                "error"
                if "error" in message
                else "result"
                if "result" in message
                else "request"
                if identifier is not None
                else "notification"
            )
            entry["method"] = method if isinstance(method, str) else None
            entry["id"] = identifier if isinstance(identifier, (int, str)) else None
        with lock, log.open("a", encoding="utf-8") as output:
            output.write(json.dumps(entry) + "\n")

    def pump(source: IO[bytes], sink: IO[bytes], direction: str) -> None:
        try:
            for line in iter(source.readline, b""):
                note(direction, line)
                sink.write(line)
                sink.flush()
        except (BrokenPipeError, ValueError):
            pass
        finally:
            try:
                sink.close()
            except OSError:
                pass

    assert server.stdin is not None and server.stdout is not None
    host = threading.Thread(target=pump, args=(sys.stdin.buffer, server.stdin, "host"), daemon=True)
    host.start()
    pump(server.stdout, sys.stdout.buffer, "server")
    return server.wait()


def fingerprint(paths: list[Path]) -> dict[str, str | None]:
    return {
        str(path): hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        for path in paths
    }


def host_step(
    argv: list[str], *, timeout: int, env: dict[str, str], cwd: Path
) -> subprocess.CompletedProcess[str]:
    process = subprocess.Popen(  # noqa: S603 - trusted host in fixed OS sandbox
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        cwd=cwd,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except BaseException:
        # Stop the health check and its MCP descendants on timeout/cancellation.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate()
        raise
    return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)


def check(claude: Path, output: Path, timeout: int) -> int:
    if not claude.is_file():
        sys.exit(f"Claude Code host not found: {claude}")
    if not SANDBOX.is_file():
        sys.exit("The no-network guarantee needs macOS sandbox-exec; refusing to run unsandboxed")
    if output.exists():
        sys.exit("Output directory must be new; existing evidence is preserved")
    output.mkdir(parents=True)
    workspace, home, log = output / "workspace", output / "home", output / "relay.jsonl"
    workspace.mkdir()
    (home / ".claude").mkdir(parents=True)
    (workspace / "app.py").write_text("def double(x):\n    return x * 2\n")
    (workspace / "test_app.py").write_text("from app import double\n\nassert double(2) == 4\n")
    sources = sorted(workspace.glob("*.py"))
    # The real user files a host session would otherwise write; only these are fingerprinted.
    checked = [Path.home() / ".claude.json", Path.home() / ".claude" / "settings.json"]
    before, source_before = fingerprint(checked), fingerprint(sources)
    environment = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(home),
        "CLAUDE_CONFIG_DIR": str(home / ".claude"),
        "TERM": "dumb",
        "DISABLE_AUTOUPDATER": "1",
        "DISABLE_TELEMETRY": "1",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
    }
    server = [sys.executable, str(Path(__file__).resolve()), "--relay", str(log), "--"]
    server += [sys.executable, "-m", "agentic_workbench.cli", "mcp", "--root", str(workspace)]
    server += ["--provider", "none"]
    register = ["mcp", "add", "--scope", "user", "agentic", "-e", f"PYTHONPATH={SOURCE}", "--"]
    steps: list[dict[str, Any]] = []
    for step in (["--version"], [*register, *server], ["mcp", "list"], ["mcp", "get", "agentic"]):
        argv = [str(SANDBOX), "-p", PROFILE, str(claude), *step]
        try:
            # The operator-named host binary inside the fixed sandbox profile, without a shell.
            done = host_step(argv, timeout=timeout, env=environment, cwd=workspace)
            steps.append(
                {
                    "argv": argv,
                    "exit": done.returncode,
                    "stdout": done.stdout[-4000:],
                    "stderr": done.stderr[-4000:],
                }
            )
        except subprocess.TimeoutExpired:
            steps.append({"argv": argv, "exit": None, "stdout": "", "stderr": "timed out"})
            break
    records = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    sent = [r["method"] for r in records if r["direction"] == "host" and r.get("method")]
    verdict = (
        "invoked a tool"
        if "tools/call" in sent
        else "listed tools"
        if "tools/list" in sent
        else "initialized only"
        if "initialize" in sent
        else "not contacted"
    )
    listed = steps[2]["stdout"] if len(steps) > 2 else ""
    connected = any("agentic" in line and "Connected" in line for line in listed.splitlines())
    after, source_after = fingerprint(checked), fingerprint(sources)
    passed = (
        all(step["exit"] == 0 for step in steps)
        and len(steps) == 4
        and connected
        and verdict != "not contacted"
        and after == before
        and source_after == source_before
    )
    receipt = {
        "passed": passed,
        "verdict": verdict,
        "connected": connected,
        "host_methods": sent,
        "relay": records,
        "steps": steps,
        "controls": {
            "credentials": "none: throwaway HOME and CLAUDE_CONFIG_DIR, no API key or login",
            "network": f"sandbox-exec {PROFILE} for the host and every process it starts",
            "timeout_seconds": timeout,
            "configuration": "server registered at user scope inside the throwaway config only",
        },
        "checked_files": {path: {"before": before[path], "after": after[path]} for path in before},
        "source_unchanged": source_after == source_before,
        "limitations": [
            "Only the installed Claude Code CLI was exercised; other hosts are unverified.",
            "The host health-checked the server; no model session or model-driven tool use ran.",
            "Only the files under checked_files were fingerprinted; this is not a filesystem "
            "audit. Throwaway HOME, CLAUDE_CONFIG_DIR and the sandbox profile are the controls.",
        ],
    }
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"passed": passed, "verdict": verdict, "connected": connected}))
    return 0 if passed else 1


def main() -> int:
    if "--relay" in sys.argv:
        position = sys.argv.index("--")
        return relay(Path(sys.argv[sys.argv.index("--relay") + 1]), sys.argv[position + 1 :])
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--claude", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=60)
    options = parser.parse_args()
    return check(options.claude.resolve(), options.output.resolve(), options.timeout)


if __name__ == "__main__":
    sys.exit(main())
