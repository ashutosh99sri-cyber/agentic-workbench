"""Stable one-envelope CLI backed by the public Workbench SDK."""

from __future__ import annotations

import argparse
import getpass
import importlib.util
import io
import os
import sys
import warnings
from dataclasses import replace
from pathlib import Path
from typing import Any, NoReturn

from . import __version__
from .errors import WorkbenchError
from .models import Grant, canonical_hash, canonical_json
from .observability import EventLogger
from .sdk import Workbench, read_proposal_file
from .secrets import SecretRedactor


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise WorkbenchError("VALIDATION_ERROR", "Invalid CLI arguments; run agentic --help")


def _parser() -> Parser:
    parser = Parser(
        prog="agentic", description="Source-grounded agents with explicit host approvals"
    )
    parser.add_argument("--version", action="version", version=f"agentic {__version__}")
    commands = parser.add_subparsers(dest="command", required=True, parser_class=Parser)
    for name in (
        "init",
        "scan",
        "explain",
        "plan",
        "apply",
        "test",
        "run",
        "status",
        "resume",
        "search",
        "state",
        "execute",
        "repair",
        "cancel",
        "trace",
        "context",
        "tools",
        "skills",
        "impact",
    ):
        sub = commands.add_parser(name)
        sub.add_argument("--root", default=".")
        sub.add_argument(
            "--typescript-package", type=Path, help="Trusted TypeScript 7 package directory"
        )
        sub.add_argument(
            "--node-executable", type=Path, help="Trusted Node executable for structural analysis"
        )
        sub.add_argument(
            "--json", action="store_true", help="Emit the versioned JSON envelope (default)"
        )
        if name in {"explain", "plan", "run", "search", "resume", "execute", "repair"}:
            sub.add_argument("--provider")
            sub.add_argument("--model")
            sub.add_argument("--embedding-model")
            sub.add_argument("--allow-network", action="store_true")
            sub.add_argument(
                "--prompt-key",
                action="store_true",
                help="Read an OpenAI key without echo for this command only",
            )
        if name == "explain":
            sub.add_argument("target")
        elif name == "plan":
            sub.add_argument("instruction")
            sub.add_argument("--proposal-file", type=Path)
        elif name == "run":
            sub.add_argument("agent")
            sub.add_argument("instruction")
        elif name in {"status", "resume", "cancel", "trace"}:
            sub.add_argument("task_id")
        elif name == "context":
            sub.add_argument("query")
            sub.add_argument("--changed-path", action="append")
        elif name == "impact":
            sub.add_argument("changed_paths", nargs="+")
            sub.add_argument("--limit", type=int, default=20)
        elif name == "execute":
            sub.add_argument("instruction")
            sub.add_argument("--proposal-id")
            sub.add_argument("--command-id")
            sub.add_argument(
                "--task-id", help="Resume a saved built-in execution with matching options"
            )
            sub.add_argument("--approve", help="Exact change approval digest")
            sub.add_argument("--approve-test", help="Exact command/snapshot approval digest")
            sub.add_argument("--backend", choices=("docker", "trusted-host"), default="docker")
            sub.add_argument("--trusted-host", action="store_true")
        elif name == "repair":
            sub.add_argument("instruction")
            sub.add_argument("--command-id", required=True)
            sub.add_argument(
                "--edit-path", action="append", required=True, help="Existing source to edit"
            )
            sub.add_argument("--max-attempts", type=int, default=2)
            sub.add_argument("--task-id", help="Resume a saved repair with matching options")
            sub.add_argument("--approve-baseline", help="Exact baseline command approval digest")
            sub.add_argument("--approve", help="Exact change approval digest")
            sub.add_argument("--approve-test", help="Exact verification command approval digest")
            sub.add_argument("--trusted-host", action="store_true")
        elif name == "search":
            sub.add_argument("query")
            modes = sub.add_mutually_exclusive_group()
            modes.add_argument("--semantic", action="store_true")
            modes.add_argument("--combined", action="store_true")
            sub.add_argument("--dimensions", type=int, default=256)
            sub.add_argument("--limit", type=int, default=5)
        elif name in {"apply", "test", "state"}:
            sub.add_argument("--dry-run", action="store_true")
            sub.add_argument("--approve")
            if name == "apply":
                sub.add_argument("proposal_id", nargs="?")
                sub.add_argument("--rollback")
            elif name == "test":
                sub.add_argument("--command-id", required=True)
                sub.add_argument("--backend", choices=("docker", "trusted-host"), default="docker")
                sub.add_argument("--trusted-host", action="store_true")
            else:
                sub.add_argument("action", choices=("export", "prune"))
                sub.add_argument("--days", type=int)
    mcp = commands.add_parser("mcp", help="Serve read-only and review tools over MCP stdio")
    mcp.add_argument("--root", default=".")
    mcp.add_argument("--typescript-package", type=Path)
    mcp.add_argument("--node-executable", type=Path)
    mcp.add_argument("--provider")
    mcp.add_argument("--model")
    mcp.add_argument("--allow-network", action="store_true")
    return parser


def _workbench(args: argparse.Namespace, grants: Grant) -> Workbench:
    typescript_package = getattr(args, "typescript_package", None)
    node_executable = getattr(args, "node_executable", None)
    if bool(typescript_package) != bool(node_executable):
        raise WorkbenchError(
            "VALIDATION_ERROR", "Select both --typescript-package and --node-executable"
        )
    analyzer = None
    if typescript_package:
        from .typescript import TypeScriptAnalyzer

        assert node_executable is not None  # the paired argparse paths were checked above
        analyzer = TypeScriptAnalyzer(node_executable, typescript_package)
    wb = Workbench(args.root, grants=grants, typescript_analyzer=analyzer)
    try:
        if (
            getattr(args, "provider", None)
            or getattr(args, "model", None)
            or getattr(args, "embedding_model", None)
        ):
            provider = wb.policy.config.provider
            wb.policy.config = replace(
                wb.policy.config,
                provider=replace(
                    provider,
                    name=args.provider or provider.name,
                    model=args.model or provider.model,
                    embedding_model=getattr(args, "embedding_model", None)
                    or provider.embedding_model,
                ),
            )
    except BaseException:
        # The caller's with-block has not started, so close the opened store here.
        wb.close()
        raise
    return wb


def _prompt_credential(args: argparse.Namespace) -> tuple[str, str]:
    if not sys.stdin.isatty():
        raise WorkbenchError("POLICY_DENIED", "Key entry requires an interactive terminal")
    if not args.allow_network:
        raise WorkbenchError("POLICY_DENIED", "Key entry requires explicit --allow-network")
    if args.command == "search" and not (args.semantic or args.combined):
        raise WorkbenchError("VALIDATION_ERROR", "Key entry requires semantic search")
    with _workbench(args, Grant(network=True)) as wb:
        provider = wb.policy.config.provider
        if provider.name != "openai":
            raise WorkbenchError("CONFIG_ERROR", "Key entry requires the OpenAI provider")
        model = provider.embedding_model if args.command == "search" else provider.model
        if model is None:
            raise WorkbenchError("CONFIG_ERROR", "Configure a model before entering a key")
        wb.policy.check_network("api.openai.com")
    if any(importlib.util.find_spec(module) is None for module in ("openai", "httpx2")):
        raise WorkbenchError("INTEGRATION_UNAVAILABLE", "Install the openai optional extra first")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            key = getpass.getpass("OpenAI API key (hidden, this command only): ")
    except (getpass.GetPassWarning, EOFError):
        raise WorkbenchError(
            "POLICY_DENIED", "Hidden key entry is unavailable or cancelled"
        ) from None
    if not key.strip() or len(key) > 8192 or any(char in key for char in ("\x00", "\r", "\n")):
        raise WorkbenchError("CONFIG_ERROR", "Enter a nonempty API key on one line")
    return provider.credential_env, key


def _dispatch(args: argparse.Namespace) -> dict[str, Any]:
    approval = getattr(args, "approve", None)
    dry_run = getattr(args, "dry_run", False) or approval is None
    trusted = getattr(args, "trusted_host", False)
    backend = "trusted-host" if trusted else getattr(args, "backend", "docker")
    if (
        args.command in {"test", "execute"}
        and backend == "trusted-host"
        and not trusted
        and (not dry_run or getattr(args, "approve_test", None))
    ):
        raise WorkbenchError(
            "POLICY_DENIED", "Host execution requires the separate --trusted-host opt-in"
        )
    # Repair writes and runs only through its exact approvals; grants are capabilities.
    grants = Grant(
        network=getattr(args, "allow_network", False),
        write=(args.command == "apply" and not dry_run)
        or (args.command == "execute" and args.proposal_id is not None)
        or args.command == "repair",
        execute=(args.command == "test" and not dry_run)
        or (args.command == "execute" and args.command_id is not None)
        or args.command == "repair",
        trusted_host=trusted and (not dry_run or args.command in {"execute", "repair"}),
    )
    with _workbench(args, grants) as wb:
        if args.command == "init":
            return wb.init()
        if args.command == "scan":
            return wb.scan()
        if args.command == "explain":
            return wb.explain(args.target)
        if args.command == "plan":
            return wb.plan(
                args.instruction,
                proposal=read_proposal_file(args.proposal_file) if args.proposal_file else None,
            )
        if args.command == "run":
            return wb.run_agent(args.agent, args.instruction)
        if args.command == "execute":
            return wb.execute(
                args.instruction,
                proposal_id=args.proposal_id,
                command_id=args.command_id,
                approval=approval,
                test_approval=args.approve_test,
                backend=backend,
                task_id=args.task_id,
            )
        if args.command == "repair":
            return wb.repair(
                args.instruction,
                command_id=args.command_id,
                edit_paths=args.edit_path,
                baseline_approval=args.approve_baseline,
                approval=approval,
                test_approval=args.approve_test,
                backend=backend,
                task_id=args.task_id,
                max_attempts=args.max_attempts,
            )
        if args.command == "cancel":
            return wb.cancel(args.task_id)
        if args.command == "trace":
            return wb.trace(args.task_id)
        if args.command == "context":
            return wb.context(args.query, changed_paths=args.changed_path)
        if args.command == "impact":
            return wb.impact(args.changed_paths, limit=args.limit)
        if args.command == "tools":
            registry = wb.tools()
            for command_id in wb.policy.config.commands:
                alias = (
                    "command_"
                    + command_id.replace("-", "_")[:36]
                    + "_"
                    + canonical_hash(command_id)[:12]
                )
                registry.register_command(alias, command_id)
            return {"tools": registry.discover(), "fingerprint": registry.fingerprint}
        if args.command == "skills":
            return {"skills": [s.pin() for s in wb._registry().skills]}
        if args.command == "status":
            return wb.task_status(args.task_id)
        if args.command == "resume":
            return wb.resume(args.task_id)
        if args.command == "search":
            return wb.search(
                args.query,
                semantic=args.semantic,
                mode="combined" if args.combined else None,
                dimensions=args.dimensions,
                limit=args.limit,
            )
        if args.command == "apply":
            if bool(args.proposal_id) == bool(args.rollback):
                raise WorkbenchError(
                    "VALIDATION_ERROR", "Choose one proposal ID or --rollback CHANGE_ID"
                )
            if args.rollback:
                return wb.rollback(args.rollback, approval=approval, dry_run=dry_run)
            return wb.apply(args.proposal_id, approval=approval, dry_run=dry_run)
        if args.command == "test":
            output = wb.test(args.command_id, approval=approval, backend=backend, dry_run=dry_run)
            if not dry_run and (
                output["exit_code"] != 0 or output["timed_out"] or output["output_limited"]
            ):
                raise WorkbenchError(
                    "TEST_FAILED", "Approved test command failed; inspect its execution record"
                )
            return output
        if args.action == "export":
            return wb.store.export()
        days = args.days or wb.policy.config.state.retention_days
        if not dry_run and approval is None:
            raise WorkbenchError("APPROVAL_REQUIRED", "Cleanup requires reviewed approval")
        if dry_run:
            return wb.store.review_prune(days)
        assert approval is not None
        return wb.store.prune(approval, days)


def main(argv: list[str] | None = None) -> int:
    redactor = SecretRedactor.from_environment()
    logger = EventLogger(redactor.redact)
    credential_name: str | None = None
    previous_credential: str | None = None
    try:
        args = _parser().parse_args(argv)
        if getattr(args, "prompt_key", False):
            credential_name, key = _prompt_credential(args)
            previous_credential = os.environ.get(credential_name)
            os.environ[credential_name] = key
            redactor = SecretRedactor.from_environment([credential_name])
            logger = EventLogger(redactor.redact)
        logger.emit("command.started", agent="cli", status=args.command)
        if args.command == "mcp":
            from .mcp import Server

            grants = Grant(network=args.allow_network)
            # Undecodable bytes reach strict_json as surrogates and get a JSON-RPC parse
            # error, instead of stopping the server.
            reader = io.TextIOWrapper(
                sys.stdin.buffer, encoding="utf-8", errors="surrogateescape", newline="\n"
            )
            try:
                return Server(lambda: _workbench(args, grants), redactor=redactor).serve(
                    reader, sys.stdout
                )
            except KeyboardInterrupt:
                # MCP stdout must remain JSON-RPC, including host-initiated shutdown.
                return 130
        data = _dispatch(args)
        try:
            logger.emit(
                "command.completed", agent="cli", task_id=data.get("task_id"), status="succeeded"
            )
        except WorkbenchError:
            data["observability_status"] = "stderr_unavailable"
        print(canonical_json({"schema_version": 1, "ok": True, "data": redactor.clean(data)}))
        # A finished repair that failed keeps its facts in the envelope and fails the shell.
        return 1 if args.command == "repair" and data.get("outcome") == "failed" else 0
    except WorkbenchError as error:
        try:
            logger.emit("command.failed", agent="cli", error_code=error.code, status="failed")
        except WorkbenchError:
            pass
        print(
            canonical_json(
                {"schema_version": 1, "ok": False, "error": redactor.clean(error.to_dict())}
            )
        )
        return error.exit_code
    except (OSError, UnicodeError, ValueError, TypeError, KeyError):
        print(
            canonical_json(
                {
                    "schema_version": 1,
                    "ok": False,
                    "error": {
                        "code": "OPERATION_FAILED",
                        "message": "Operation failed at an input or filesystem boundary",
                        "retryable": False,
                    },
                }
            )
        )
        return 1
    except KeyboardInterrupt:
        print(
            canonical_json(
                {
                    "schema_version": 1,
                    "ok": False,
                    "error": {
                        "code": "INTERRUPTED",
                        "message": "Operation interrupted; inspect saved state before resuming",
                        "retryable": False,
                    },
                }
            )
        )
        return 1

    finally:
        if credential_name is not None:
            if previous_credential is None:
                os.environ.pop(credential_name, None)
            else:
                os.environ[credential_name] = previous_credential


if __name__ == "__main__":
    sys.exit(main())
