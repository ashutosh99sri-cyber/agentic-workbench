"""Offline installed-SDK tutorial; only its own temporary training project is mutable."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from agentic_workbench import CommandConfig, Config, Grant, Workbench

SOURCE = """def discounted_total(amount_cents: int, discount_percent: int) -> int:
    return amount_cents - discount_percent
"""
FIXED = SOURCE.replace(
    "amount_cents - discount_percent", "amount_cents * (100 - discount_percent) // 100"
)
TESTS = """import os
import unittest
from pathlib import Path
from app import discounted_total

class DiscountTests(unittest.TestCase):
    def test_percentage(self):
        self.assertEqual(discounted_total(1000, 10), 900)

    def test_sanitized_snapshot(self):
        self.assertNotIn("OPENAI_API_KEY", os.environ)
        self.assertFalse(Path(".agentic").exists())
"""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def run_tests(wb: Workbench) -> dict[str, Any]:
    review = wb.test_review("unit", backend="trusted-host")
    return wb.test("unit", approval=review["digest"], backend="trusted-host", dry_run=False)


def walkthrough(*, execute: bool = False) -> dict[str, Any]:
    require(not execute or os.name == "posix", "--execute requires POSIX")
    require(Path(sys.executable).is_absolute(), "Use an absolute installed Python interpreter")
    with tempfile.TemporaryDirectory(prefix="agentic-sdk-tutorial-") as temporary:
        root = Path(temporary).resolve()
        originals = {"app.py": SOURCE.encode(), "test_app.py": TESTS.encode()}
        for name, content in originals.items():
            (root / name).write_bytes(content)
        config = Config(
            commands={"unit": CommandConfig((sys.executable, "-I", "-B", "-m", "unittest", "-q"))}
        )
        grants = Grant(write=execute, execute=execute, trusted_host=execute)
        with Workbench(root, config, grants=grants) as wb:
            scan = wb.scan()
            explanation = wb.explain("app.py")
            original_hash = hashlib.sha256(originals["app.py"]).hexdigest()
            plan = wb.plan(
                "Fix the training percentage discount and retain its regression test",
                proposal={
                    "schema_version": 1,
                    "rationale": "Apply the percentage to the amount in this synthetic fixture",
                    "edits": [
                        {
                            "path": "app.py",
                            "base_hash": original_hash,
                            "content": FIXED,
                            "delete": False,
                        }
                    ],
                },
            )
            require(len(plan["proposals"]) == 1, "Expected only the predefined training proposal")
            review = wb.review(plan["proposals"][0]["proposal_id"])
            require(
                len(review["edits"]) == 1
                and review["edits"][0]["path"] == "app.py"
                and review["edits"][0]["base_hash"] == original_hash,
                "Training proposal escaped its predefined scope",
            )
            dry_run = wb.apply(review["proposal_id"])
            require(
                all((root / name).read_bytes() == data for name, data in originals.items()),
                "Read-only tutorial changed source",
            )
            report = {
                "temporary_root": str(root),
                "executed": execute,
                "scan_files": len(scan["files"]),
                "explanation_mode": explanation["mode"],
                "explanation": explanation["summary"],
                "provider_requests": explanation["usage"]["requests"],
                "plan_task_id": plan["task_id"],
                "review": review,
                "dry_run": dry_run,
                "tests": {},
            }
            if execute:
                before = run_tests(wb)
                require(
                    before["exit_code"] != 0 and "990 != 900" in before["stderr"],
                    "Training regression did not fail as expected",
                )
                applied = wb.apply(review["proposal_id"], approval=review["digest"], dry_run=False)
                try:
                    require(
                        (root / "app.py").read_bytes() == FIXED.encode(),
                        "Applied source differs from the exact training fix",
                    )
                    after = run_tests(wb)
                    require(
                        after["exit_code"] == 0 and "Ran 2 tests" in after["stderr"],
                        "Approved training fix did not pass both tests",
                    )
                finally:
                    rollback_review = wb.review_rollback(applied["change_id"])
                    rollback = wb.rollback(
                        applied["change_id"], approval=rollback_review["digest"], dry_run=False
                    )
                    require(
                        all((root / name).read_bytes() == data for name, data in originals.items()),
                        "Rollback changed source bytes",
                    )
                report.update(
                    applied=applied, rollback=rollback, tests={"before": before, "after": after}
                )
            report.update(
                original_sha256=original_hash,
                final_sha256=hashlib.sha256((root / "app.py").read_bytes()).hexdigest(),
                source_unchanged=True,
            )
        return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Approve the exact synthetic fix and trusted-host tests, then roll back",
    )
    args = parser.parse_args()
    # Reporting happens only after rollback and owned temporary-directory cleanup.
    print(json.dumps(walkthrough(execute=args.execute), indent=2))
