"""Review, repair, verify, and roll back a fresh provider-free fixture."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from agentic_workbench import CommandConfig, Config, Grant, Workbench, WorkbenchError

INSTRUCTION = "Fix the percentage discount and verify the unit tests"
BACKEND = "trusted-host"


def show(label: str, value: dict[str, Any]) -> None:
    print(f"\n{label}\n{json.dumps(value, indent=2, sort_keys=True)}", flush=True)
    if value.get("diff"):
        print(value["diff"], flush=True)


def approve(word: str, label: str, review: dict[str, Any]) -> bool:
    show(label, review)
    try:
        decision = input(f"Type {word} to approve this digest, or anything else to pause: ").strip()
    except (EOFError, KeyboardInterrupt):
        decision = ""
    if decision != word:
        print(f"\nPaused before {word}; the workspace and available task state are retained.")
        return False
    print(f"Approved {word} digest: {review['digest']}", flush=True)
    return True


def walkthrough(root: Path) -> int:
    fixture = Path(__file__).resolve().parents[1] / "python_app"
    for filename in ("app.py", "test_app.py"):
        shutil.copyfile(fixture / filename, root / filename)
    original = (root / "app.py").read_text()
    old = "return amount_cents - discount_percent"
    new = "return amount_cents * (100 - discount_percent) // 100"
    if original.count(old) != 1:
        raise ValueError("The checked-in percentage fixture no longer matches this walkthrough")
    config = Config(
        commands={
            "unit": CommandConfig(
                (str(Path(sys.executable).absolute()), "-B", "-m", "unittest", "-q")
            )
        }
    )
    grants = Grant(write=True, execute=True, trusted_host=True)
    with Workbench(root, config, grants=grants) as wb:
        wb.init()
    with (root / ".agentic/config.toml").open("a", encoding="utf-8") as output:
        output.write("\n[commands.unit]\nargv = " + json.dumps(list(config.commands["unit"].argv)))
        output.write("\n")

    print("Provider: none. Network grant: false.")
    print(
        "Trusted-host runs a known Python fixture on your host, with weaker isolation than Docker."
    )
    print("Each approval below is separate; the Workbench closes and reopens between stages.")
    with Workbench(root, grants=grants) as wb:
        baseline_review = wb.test_review("unit", backend=BACKEND)
    if not approve("BASELINE", "Baseline command review", baseline_review):
        return 1
    with Workbench(root, grants=grants) as wb:
        baseline = wb.test(
            "unit", approval=baseline_review["digest"], backend=BACKEND, dry_run=False
        )
    show("Baseline receipt (the deliberate regression must fail)", baseline)
    if baseline["exit_code"] == 0 or baseline["timed_out"] or baseline["output_limited"]:
        raise ValueError("Expected a completed failing baseline; the repair has not been proposed")

    with Workbench(root, grants=grants) as wb:
        proposal = wb.propose(
            [
                {
                    "path": "app.py",
                    "base_hash": hashlib.sha256(original.encode()).hexdigest(),
                    "content": original.replace(old, new),
                    "delete": False,
                }
            ],
            rationale="Apply the discount percentage to the amount in cents",
            instruction=INSTRUCTION,
        )
        pending = wb.execute(
            INSTRUCTION, proposal_id=proposal["proposal_id"], command_id="unit", backend=BACKEND
        )
    task_id = pending["task_id"]
    print(f"TASK: {task_id}")
    print(f"PROPOSAL: {proposal['proposal_id']}")
    print(f"Execution state before patch approval: {pending['state']}")
    if pending["state"] != "awaiting_approval" or (root / "app.py").read_text() != original:
        raise ValueError("The workflow did not pause before the source change")
    change_review = pending["reviews"]["change"]
    if not approve("APPLY", "Exact patch review", change_review):
        return 1
    with Workbench(root, grants=grants) as wb:
        applied = wb.execute(
            INSTRUCTION,
            proposal_id=proposal["proposal_id"],
            command_id="unit",
            backend=BACKEND,
            task_id=task_id,
            approval=change_review["digest"],
        )
    if applied["state"] != "awaiting_approval":
        raise ValueError("The workflow did not pause for the separate repaired check")
    change_id = applied["observations"]["apply"]["evidence"]["change"]["change_id"]
    print(f"CHANGE: {change_id}")
    print(f"Execution state before repaired check approval: {applied['state']}")
    test_review = applied["reviews"]["test"]
    if not approve("CHECK", "Repaired command review", test_review):
        return 1
    with Workbench(root, grants=grants) as wb:
        completed = wb.execute(
            INSTRUCTION,
            proposal_id=proposal["proposal_id"],
            command_id="unit",
            backend=BACKEND,
            task_id=task_id,
            approval=change_review["digest"],
            test_approval=test_review["digest"],
        )
        trace = wb.trace(task_id)
        rollback_review = wb.review_rollback(change_id)
    if completed["state"] != "succeeded":
        raise ValueError("The repaired workflow did not succeed")
    repaired = completed["verification"]["evidence"]["receipt"]
    show("Repaired receipt", repaired)
    show("Retained task trace (verification describes the repaired snapshot)", trace)
    if not approve("ROLLBACK", "Exact rollback review", rollback_review):
        return 1
    with Workbench(root, grants=grants) as wb:
        rolled_back = wb.rollback(change_id, approval=rollback_review["digest"], dry_run=False)
    show("Rollback receipt", rolled_back)
    if rolled_back["state"] != "rolled_back" or (root / "app.py").read_text() != original:
        raise ValueError("Rollback did not restore the original fixture")
    print("Original fixture restored. The successful repair trace remains available.")
    print(
        "RESULT: "
        + json.dumps(
            {
                "workspace": str(root),
                "task_id": task_id,
                "proposal_id": proposal["proposal_id"],
                "change_id": change_id,
                "baseline_exit_code": baseline["exit_code"],
                "repaired_exit_code": repaired["exit_code"],
                "rollback_state": rolled_back["state"],
            },
            sort_keys=True,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trusted-host", action="store_true", help="Allow this known host fixture")
    parser.add_argument("--workspace", type=Path, help="New directory to retain (must not exist)")
    args = parser.parse_args()
    if not args.trusted_host:
        parser.error("This fixture requires --trusted-host; no workspace has been created")
    target = args.workspace.expanduser() if args.workspace is not None else None
    if target is not None and (target.exists() or target.is_symlink()):
        parser.error("Refusing an existing path or symlink; choose a new disposable directory")
    if os.name != "posix":
        parser.error("This mutation walkthrough requires POSIX; use the portable read-only setup")
    try:
        if target is None:
            root = Path(tempfile.mkdtemp(prefix="agentic-offline-repair-")).resolve()
        else:
            target.mkdir(mode=0o700)
            root = target.resolve()
    except FileExistsError:
        parser.error("Refusing an existing path or symlink; choose a new disposable directory")
    except OSError as error:
        parser.error(str(error))
    print(f"WORKSPACE: {root}", flush=True)
    try:
        return walkthrough(root)
    except KeyboardInterrupt:
        print("\nInterrupted; the workspace and available task state are retained.")
        return 1
    except (WorkbenchError, OSError, ValueError) as error:
        print(f"Stopped: {error}. Workspace retained: {root}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
