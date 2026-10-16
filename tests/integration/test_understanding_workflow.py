"""Real Node fixture, source-cited selection and approved executable verification."""

import shutil
from pathlib import Path

import pytest

from agentic_workbench import CommandConfig, Config, Grant, Workbench
from agentic_workbench.models import text_hash
from agentic_workbench.typescript import TypeScriptAnalyzer

ROOT = Path(__file__).resolve().parents[2]


def test_typescript_impact_to_reviewed_repair_with_real_node(tmp_path: Path) -> None:
    node = shutil.which("node")
    package = ROOT / "adapters/node/node_modules/typescript"
    if not node or not package.exists():
        pytest.skip("Explicit trusted Node and TypeScript 7.0.2 installation required")
    root = tmp_path / "discount"
    shutil.copytree(ROOT / "examples/typescript_app", root)
    config = Config(commands={"unit": CommandConfig((node, "--test", "test/app.test.mjs"))})
    analyzer = TypeScriptAnalyzer(Path(node), package)
    grants = Grant(write=True, execute=True, trusted_host=True)
    with Workbench(root, config, grants=grants, typescript_analyzer=analyzer) as wb:
        result = wb.impact(["src/app.ts"])
        assert any(row["name"] == "discountedTotal" for row in result["definitions"])
        assert "test/app.test.mjs" in result["affected_paths"]
        context = wb.context(
            "Repair discountedTotal percentage calculation", changed_paths=["src/app.ts"]
        )
        assert context["retrieval"]
        before = wb.test_review("unit", backend="trusted-host")
        failed = wb.test("unit", approval=before["digest"], backend="trusted-host", dry_run=False)
        assert failed["exit_code"] != 0
        source = (root / "src/app.ts").read_text()
        replacement = source.replace(
            "return amountCents - discountPercent;",
            "return Math.floor(amountCents * (100 - discountPercent) / 100);",
        )
        assert source != replacement
        proposal = wb.propose(
            [
                {
                    "path": "src/app.ts",
                    "base_hash": text_hash(source),
                    "content": replacement,
                    "delete": False,
                }
            ],
            rationale="Apply the percentage to the amount",
            instruction="Fix percentage discount",
            evidence=[result["definitions"][0]["evidence"]],
        )
        review = wb.apply(proposal["proposal_id"])
        wb.apply(proposal["proposal_id"], approval=review["digest"], dry_run=False)
        after = wb.test_review("unit", backend="trusted-host")
        verified = wb.test("unit", approval=after["digest"], backend="trusted-host", dry_run=False)
        assert verified["exit_code"] == 0 and not verified["timed_out"]
        assert (root / "test/app.test.mjs").read_bytes() == (
            ROOT / "examples/typescript_app/test/app.test.mjs"
        ).read_bytes()
