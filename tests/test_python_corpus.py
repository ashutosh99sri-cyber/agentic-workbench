"""Validate the checked-in historical task data without network or upstream execution."""

import ast
import hashlib
import json
import re
from pathlib import Path, PurePosixPath

CORPUS = Path(__file__).resolve().parents[1] / "evaluations" / "python"
REPOSITORIES = {
    "https://github.com/more-itertools/more-itertools": ("MIT", "."),
    "https://github.com/pallets/click": ("BSD-3-Clause", "src"),
    "https://github.com/pypa/packaging": ("Apache-2.0 OR BSD-2-Clause", "src"),
}


def test_historical_task_manifest_and_independent_checks() -> None:
    manifest = json.loads((CORPUS / "manifest.json").read_text())
    assert manifest["schema_version"] == 1
    tasks = manifest["tasks"]
    assert len(tasks) == 30
    assert {task["repo"] for task in tasks} == set(REPOSITORIES)
    assert len({task["id"] for task in tasks}) == len(tasks)
    assert len({(task["repo"], task["fixed_commit"]) for task in tasks}) == len(tasks)
    for task in tasks:
        assert re.fullmatch(r"[a-z][a-z0-9_-]+", task["id"])
        license_id, source_subdir = REPOSITORIES[task["repo"]]
        assert task["license"] == license_id
        assert task["source_subdir"] == source_subdir
        assert task["summary"].strip()
        for key in ("buggy_commit", "fixed_commit"):
            assert re.fullmatch(r"[0-9a-f]{40}", task[key])
        assert task["buggy_commit"] != task["fixed_commit"]
        assert task["editable_paths"]
        for editable in task["editable_paths"]:
            path = PurePosixPath(editable)
            assert not path.is_absolute() and ".." not in path.parts
            assert path.suffix == ".py"
            assert not any(part == "tests" or part.startswith("test_") for part in path.parts)
        checks = []
        for kind in ("reproduction", "holdout"):
            relative = PurePosixPath(task[f"{kind}_file"])
            assert relative.parent == PurePosixPath("checks")
            assert relative.name.endswith(f"_{kind}.py")
            assert ".." not in relative.parts
            source = (CORPUS / relative).read_text()
            tree = ast.parse(source)
            assert any(isinstance(node, ast.Assert) for node in ast.walk(tree))
            package = task["repo"].rsplit("/", 1)[1].replace("-", "_")
            package_alias = next(
                alias.asname or alias.name
                for node in tree.body
                if isinstance(node, ast.Import)
                for alias in node.names
                if alias.name == package
            )
            package_file = f"{package}/__init__.py"
            if source_subdir != ".":
                package_file = f"{source_subdir}/{package_file}"
            guard = ast.parse(
                f"Path({package_alias}.__file__).resolve() == "
                f"Path.cwd().resolve() / {package_file!r}",
                mode="eval",
            ).body
            assert any(
                isinstance(node, ast.Assert) and ast.dump(node.test) == ast.dump(guard)
                for node in tree.body
            ), f"{relative} does not verify the exact prepared source origin"
            assert "pytest" not in source
            checks.append(hashlib.sha256(source.encode()).hexdigest())
        assert checks[0] != checks[1]


def test_archive_lock_covers_every_task_pin() -> None:
    manifest = json.loads((CORPUS / "manifest.json").read_text())
    lock = json.loads((CORPUS / "archives.lock.json").read_text())
    assert lock["schema_version"] == 1
    archives = lock["archives"]
    keys = [(row["repo"], row["commit"]) for row in archives]
    assert len(keys) == len(set(keys))
    for row in archives:
        assert row["repo"] in REPOSITORIES
        assert re.fullmatch(r"[0-9a-f]{40}", row["commit"])
        assert re.fullmatch(r"[0-9a-f]{64}", row["sha256"])
        slug = row["repo"].removeprefix("https://github.com/")
        assert row["url"] == f"https://codeload.github.com/{slug}/zip/{row['commit']}"
    expected = {
        (task["repo"], task[f"{phase}_commit"])
        for task in manifest["tasks"]
        for phase in ("buggy", "fixed")
    }
    assert set(keys) == expected


def test_qualification_evidence_matches_current_checks_and_pins() -> None:
    manifest = json.loads((CORPUS / "manifest.json").read_text())
    qualification = json.loads((CORPUS / "qualification.json").read_text())
    tasks = {task["id"]: task for task in manifest["tasks"]}
    assert qualification["mode"] == "upstream-behavior-preflight-not-agent-repair"
    assert qualification["qualified_tasks"] == len(tasks)
    assert qualification["blocked_tasks"] == []
    assert qualification["live_provider_requests"] == 0
    expected = {
        (task_id, phase, kind)
        for task_id in tasks
        for phase in ("buggy", "fixed")
        for kind in ("reproduction", "holdout")
    }
    actual = set()
    for row in qualification["checks"]:
        key = (row["task_id"], row["phase"], row["check"])
        assert key not in actual
        actual.add(key)
        task = tasks[row["task_id"]]
        assert row["commit"] == task[f"{row['phase']}_commit"]
        source = (CORPUS / task[f"{row['check']}_file"]).read_bytes()
        assert row["check_sha256"] == hashlib.sha256(source).hexdigest()
        assert row["exit_code"] == (0 if row["phase"] == "fixed" else 1)
        assert row["elapsed_ms"] > 0
    assert actual == expected


def test_license_provenance_covers_every_verified_archive() -> None:
    lock = json.loads((CORPUS / "archives.lock.json").read_text())
    provenance = json.loads((CORPUS / "provenance.json").read_text())
    archives = {(row["repo"], row["commit"]) for row in lock["archives"]}
    assert {(row["repo"], row["commit"]) for row in provenance["upstream_licenses"]} == archives
    for row in provenance["upstream_licenses"]:
        assert row["files"]
        for source in row["files"]:
            assert source["path"].startswith("LICENSE")
            assert re.fullmatch(r"[0-9a-f]{64}", source["sha256"])
            assert source["url"] == f"{row['repo']}/blob/{row['commit']}/{source['path']}"
