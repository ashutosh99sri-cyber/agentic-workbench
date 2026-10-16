import importlib.metadata
import importlib.resources
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import agentic_workbench

_SPEC = importlib.util.spec_from_file_location(
    "check_release", Path(__file__).resolve().parents[1] / "scripts/check_release.py"
)
assert _SPEC is not None and _SPEC.loader is not None
check_release = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(check_release)


def test_public_version_matches_installed_distribution():
    assert agentic_workbench.__version__ == importlib.metadata.version("agentic-workbench")


def test_package_exposes_typing_marker():
    assert importlib.resources.files("agentic_workbench").joinpath("py.typed").is_file()


def test_public_sdk_import_works_in_isolated_python(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            "from agentic_workbench import Workbench; import sys; "
            "assert Workbench.__module__ == 'agentic_workbench.sdk'; "
            "assert 'openai' not in sys.modules",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.distribution
@pytest.mark.parametrize(
    ("annotation", "error_code"),
    [("dict[str, Any]", None), ("int", "[assignment]")],
    ids=["valid-call", "invalid-assignment"],
)
def test_installed_sdk_types_accept_valid_call_and_reject_invalid_assignment(
    tmp_path, annotation, error_code
):
    python = os.environ.get("AGENTIC_INSTALLED_PYTHON")
    assert python is not None and Path(python).is_absolute(), (
        "Supply clean installed package Python"
    )
    consumer = tmp_path / "consumer.py"
    source = (
        "from pathlib import Path\n"
        "from typing import Any\n"
        "from agentic_workbench import Workbench\n"
        "with Workbench(Path('.')) as wb:\n"
        f"    inventory: {annotation} = wb.scan()\n"
    )
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.pop("MYPYPATH", None)
    command = [
        sys.executable,
        "-m",
        "mypy",
        "--strict",
        "--no-incremental",
        "--follow-imports=silent",
        "--python-executable",
        python,
        str(consumer),
    ]
    consumer.write_text(source)
    result = subprocess.run(
        command,
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if error_code is None:
        assert result.returncode == 0, result.stdout + result.stderr
    else:
        assert result.returncode != 0 and error_code in result.stdout, result.stdout + result.stderr


def test_cli_version_works_outside_source_checkout(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "agentic_workbench.cli", "--version"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"agentic {agentic_workbench.__version__}"


def git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments], cwd=root, capture_output=True, text=True, check=True, timeout=10
    ).stdout.strip()


@pytest.mark.parametrize("version", ["", "v1.2.3", "1.2", "1.2.3rc1", "01.2.3", "1.2.3;id"])
def test_release_requires_plain_semantic_version(tmp_path, version):
    with pytest.raises(ValueError, match="X.Y.Z"):
        check_release.release_provenance(tmp_path, version)


def test_release_requires_existing_exact_tag_and_head_commit(tmp_path):
    git(tmp_path, "init")
    git(
        tmp_path,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "--allow-empty",
        "-m",
        "release",
    )
    git(tmp_path, "branch", "v1.2.3")
    with pytest.raises(ValueError, match="existing tag"):
        check_release.release_provenance(tmp_path, "1.2.3")
    git(
        tmp_path,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "tag",
        "-a",
        "v1.2.3",
        "-m",
        "release",
        "--",
        "HEAD",
    )
    commit = git(tmp_path, "rev-parse", "HEAD")
    assert check_release.release_provenance(tmp_path, "1.2.3") == {
        "tag": "refs/tags/v1.2.3",
        "commit": commit,
    }
    git(
        tmp_path,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "--allow-empty",
        "-m",
        "later",
    )
    with pytest.raises(ValueError, match="HEAD"):
        check_release.release_provenance(tmp_path, "1.2.3")


def test_local_candidate_check_does_not_require_a_release_tag(tmp_path):
    result = subprocess.run(
        [sys.executable, str(Path(check_release.__file__))],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert '"ok": true' in result.stdout
    assert '"tag"' not in result.stdout


def test_tagged_release_rejects_dirty_source(tmp_path):
    git(tmp_path, "init")
    path = tmp_path / "source.py"
    path.write_text("# original\n")
    git(tmp_path, "add", ".")
    git(
        tmp_path,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-m",
        "source",
    )
    git(tmp_path, "tag", "v1.2.3")
    path.write_text("# changed\n")
    with pytest.raises(ValueError, match="clean"):
        check_release.release_provenance(tmp_path, "1.2.3")


@pytest.mark.parametrize(
    "change",
    [
        None,
        {"version": "0.2.0"},
        {"private": True},
        {"private": "false"},
        {"publishConfig": {"access": "restricted"}},
    ],
)
def test_node_release_metadata_requires_matching_public_distribution(tmp_path, change):
    node = {
        "version": "0.1.0",
        "publishConfig": {"access": "public", "registry": "https://registry.npmjs.org/"},
    }
    if change:
        node.update(change)
    directory = tmp_path / "adapters/node"
    directory.mkdir(parents=True)
    (directory / "package.json").write_text(json.dumps(node))
    if change:
        with pytest.raises(ValueError, match="Node release"):
            check_release.node_release_metadata(tmp_path, "0.1.0")
    else:
        check_release.node_release_metadata(tmp_path, "0.1.0")
