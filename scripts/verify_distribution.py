"""Run with the clean installed environment's Python, from outside the checkout."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from importlib.metadata import distribution, version
from importlib.resources import files
from pathlib import Path
from typing import Any


def invoke(root: Path, arguments: list[str]) -> dict[str, Any]:
    result = subprocess.run(  # noqa: S603 - fixed installed module; disposable owned source
        [sys.executable, "-m", "agentic_workbench.cli", *arguments, "--root", str(root), "--json"],
        capture_output=True,
        text=True,
        check=False,
        cwd=root,
        timeout=30,
    )
    envelope = json.loads(result.stdout)
    assert result.returncode == 0 and envelope["ok"], envelope
    return envelope["data"]  # type: ignore[no-any-return]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-version")
    args = parser.parse_args()
    from agentic_workbench import Workbench
    from agentic_workbench.skills import SkillRegistry

    assert "openai" not in sys.modules, "Offline SDK import must remain provider-lazy"
    installed = version("agentic-workbench")
    if args.expected_version:
        assert installed == args.expected_version
    package = distribution("agentic-workbench")
    notices = {
        Path(item).name: package.locate_file(item).read_text()
        for item in package.files or []
        if ".dist-info/licenses/" in str(item)
    }
    assert "Apache License" in notices["LICENSE"]
    assert "Ponytail" in notices["NOTICE"]
    assert "Copyright (c) 2026 DietrichGebert" in notices["THIRD_PARTY_NOTICES.md"]
    assert "Copyright (c) 2012 Erik Rose" in notices["THIRD_PARTY_NOTICES.md"]
    with tempfile.TemporaryDirectory(prefix="agentic-wheel-") as directory:
        root = Path(directory).resolve()
        source = "def answer():\n    return 41\n"
        (root / "app.py").write_text(source)
        (root / "test_app.py").write_text(
            "import unittest\nfrom app import answer\n"
            "class TestAnswer(unittest.TestCase):\n"
            "    def test_answer(self):\n        self.assertEqual(answer(), 42)\n"
        )
        invoke(root, ["init"])
        environment = root / ".venv-agentic"
        environment.mkdir()
        (environment / "third_party.py").write_text("dependency_code = True\n")
        config = root / ".agentic/config.toml"
        with config.open("a") as output:
            output.write(
                "\n[commands.unit]\nargv = "
                + json.dumps([sys.executable, "-m", "unittest", "-q"])
                + "\n"
            )
        inventory = invoke(root, ["scan"])
        assert inventory["languages"] == ["python"]
        assert not any(row["path"].startswith(".venv-agentic/") for row in inventory["files"])
        assert invoke(root, ["explain", "app.py"])["mode"] == "static"
        execution = invoke(root, ["execute", "Explain answer and its test"])
        assert execution["state"] == "succeeded"
        assert execution["verification"]["evidence"]["scope"] == "source-contracts"
        assert invoke(root, ["trace", execution["task_id"]])["phases"]
        assert len(invoke(root, ["tools"])["tools"]) >= 6
        assert len(invoke(root, ["skills"])["skills"]) == 10
        assert invoke(root, ["context", "answer"])["retrieval"]
        imported = {
            "schema_version": 1,
            "rationale": "Clean distribution acceptance",
            "edits": [
                {
                    "path": "app.py",
                    "base_hash": hashlib.sha256(source.encode()).hexdigest(),
                    "content": source.replace("41", "42"),
                    "delete": False,
                }
            ],
        }
        proposal_file = root / "proposal.json"
        proposal_file.write_text(json.dumps(imported))
        plan = invoke(root, ["plan", "Correct answer", "--proposal-file", str(proposal_file)])
        review = invoke(root, ["apply", plan["proposal_ids"][0], "--dry-run"])
        assert (root / "app.py").read_text() == source
        invoke(root, ["test", "--command-id", "unit", "--trusted-host", "--dry-run"])
        if os.name == "posix":
            applied = invoke(root, ["apply", review["proposal_id"], "--approve", review["digest"]])
            tests = invoke(root, ["test", "--command-id", "unit", "--trusted-host"])
            assert (
                invoke(
                    root,
                    [
                        "test",
                        "--command-id",
                        "unit",
                        "--trusted-host",
                        "--approve",
                        tests["digest"],
                    ],
                )["exit_code"]
                == 0
            )
            rollback = invoke(root, ["apply", "--rollback", applied["change_id"]])
            invoke(
                root, ["apply", "--rollback", applied["change_id"], "--approve", rollback["digest"]]
            )
            assert (root / "app.py").read_text() == source
        assert invoke(root, ["search", "answer"])["chunks"]
        with Workbench(root) as wb:
            skills = SkillRegistry(wb.policy)
            assert len(skills.skills) == 10
        # SDK consumers only get types when the PEP 561 marker is installed.
        assert files("agentic_workbench").joinpath("py.typed").is_file()
    print(
        json.dumps(
            {
                "ok": True,
                "version": installed,
                "packaged_skills": 10,
                "required_commands": 6,
                "typing_marker": True,
                "mutation_platform": os.name,
                "packaged_license_files": sorted(notices),
            }
        )
    )


if __name__ == "__main__":
    main()
