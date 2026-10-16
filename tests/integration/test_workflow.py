import shutil
import sys
from pathlib import Path

import pytest

from agentic_workbench.config import CommandConfig, Config
from agentic_workbench.models import Grant, text_hash
from agentic_workbench.sdk import Workbench


@pytest.mark.parametrize("example", ["python_app", "typescript_app"])
def test_actual_regression_apply_test_and_rollback(tmp_path: Path, example: str) -> None:
    source = Path(__file__).resolve().parents[2] / "examples" / example
    root = tmp_path / example
    shutil.copytree(source, root, ignore=shutil.ignore_patterns(".agentic"))
    if example == "python_app":
        path = "app.py"
        old = "return amount_cents - discount_percent"
        new = "return amount_cents * (100 - discount_percent) // 100"
        argv = (sys.executable, "-m", "unittest", "-q")
    else:
        path = "src/app.ts"
        old = "return amountCents - discountPercent;"
        new = "return Math.floor(amountCents * (100 - discountPercent) / 100);"
        node = shutil.which("node")
        assert node is not None
        argv = (node, "--test", "test/app.test.mjs")
    config = Config(commands={"unit": CommandConfig(argv)})
    grants = Grant(write=True, execute=True, trusted_host=True)
    with Workbench(root, config, grants=grants) as wb:
        before = wb.test_review("unit", backend="trusted-host")
        failed = wb.test("unit", approval=before["digest"], backend="trusted-host", dry_run=False)
        assert failed["exit_code"] != 0
        original = (root / path).read_text()
        plan = wb.plan(
            "Fix percentage discount",
            proposal={
                "schema_version": 1,
                "rationale": "Apply percentage to amount",
                "edits": [
                    {
                        "path": path,
                        "base_hash": text_hash(original),
                        "content": original.replace(old, new),
                        "delete": False,
                    }
                ],
            },
        )
        proposal = plan["proposals"][0]
        wb.apply(proposal["proposal_id"])
        assert (root / path).read_text() == original
        changed = wb.apply(proposal["proposal_id"], approval=proposal["digest"], dry_run=False)
        after = wb.test_review("unit", backend="trusted-host")
        passed = wb.test("unit", approval=after["digest"], backend="trusted-host", dry_run=False)
        assert passed["exit_code"] == 0
        rollback = wb.review_rollback(changed["change_id"])
        wb.rollback(changed["change_id"], approval=rollback["digest"], dry_run=False)
        assert (root / path).read_text() == original
