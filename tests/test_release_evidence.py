"""Release receipts must bind actual test cases and archive bytes to source."""

import importlib.util
import io
import json
import subprocess
import tarfile
import zipfile
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "release_evidence", Path(__file__).resolve().parents[1] / "scripts/record_release_evidence.py"
)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def git(root, *args):
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True, timeout=10
    ).stdout.strip()


def tar(path, contents):
    with tarfile.open(path, "w:gz") as archive:
        for name, content in contents.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))


@pytest.fixture
def candidate(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    source = {"agentic_workbench/__init__.py": b"# candidate\n", "agentic_workbench/py.typed": b""}
    for name, content in source.items():
        path = root / "src" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    (root / "pyproject.toml").write_text(
        '[project.scripts]\nagentic = "agentic_workbench.cli:main"\n'
    )
    git(root, "init")
    git(root, "add", ".")
    git(
        root,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-m",
        "source",
    )
    commit = git(root, "rev-parse", "HEAD")
    artifacts = tmp_path / "dist"
    artifacts.mkdir()
    metadata = b"Metadata-Version: 2.4\nName: agentic-workbench\nVersion: 1.2.3\n"
    with zipfile.ZipFile(artifacts / "agentic_workbench-1.2.3-py3-none-any.whl", "w") as archive:
        for name, content in source.items():
            archive.writestr(name, content)
        archive.writestr("agentic_workbench-1.2.3.dist-info/METADATA", metadata)
        archive.writestr(
            "agentic_workbench-1.2.3.dist-info/entry_points.txt",
            "[console_scripts]\nagentic = agentic_workbench.cli:main\n",
        )
    tar(
        artifacts / "agentic_workbench-1.2.3.tar.gz",
        {
            **{f"agentic_workbench-1.2.3/src/{name}": data for name, data in source.items()},
            "agentic_workbench-1.2.3/PKG-INFO": metadata,
        },
    )
    junit, receipts = {}, {}
    images = {"node": "node@sha256:" + "a" * 64, "python": "python@sha256:" + "b" * 64}
    cases = {
        "python": ["test_unit"],
        "docker-node": [
            *module.NODE_CASES,
            *[module.TIMEOUT_CASE + f"[{name}]" for name in module.TIMEOUT_IDS],
        ],
        "docker-python": [module.PYTHON_CASE],
    }
    for label, names in cases.items():
        junit[label] = tmp_path / f"{label}.xml"
        junit[label].write_text(
            '<testsuites><testsuite tests="'
            + str(len(names))
            + '" failures="0" errors="0" skipped="0">'
            + "".join(
                f'<testcase classname="tests.integration.test_sandbox" name="{name}"/>'
                for name in names
            )
            + "</testsuite></testsuites>"
        )
        receipts[label] = tmp_path / f"{label}.json"
        data = {"commit": commit}
        if label.startswith("docker-"):
            kind = label.removeprefix("docker-")
            data[kind + "_image"] = images[kind]
        receipts[label].write_text(json.dumps(data))
    return {
        "root": root,
        "expected_commit": commit,
        "artifacts": artifacts,
        "junit": junit,
        "source_receipts": receipts,
        "node_image": images["node"],
        "python_image": images["python"],
    }


def test_valid_candidate_is_explicitly_not_publication_authority(candidate):
    receipt = module.collect(**candidate)
    assert receipt["local_candidate_verified"] is True
    assert receipt["publication_ready"] is False
    assert receipt["commit"] == candidate["expected_commit"]
    assert len(receipt["artifacts"]) == 2
    assert receipt["suites"]["docker-node"]["tests"] == 7


@pytest.mark.parametrize(
    "change",
    [
        "dirty",
        "untracked",
        "stale",
        "image",
        "receipt",
        "empty",
        "skip",
        "failure",
        "missing-case",
        "dtd",
        "tamper",
        "missing-source",
        "extra-runtime",
        "unsafe-path",
        "version",
    ],
)
def test_candidate_rejects_unverified_evidence(candidate, change):
    root, junit, receipts = candidate["root"], candidate["junit"], candidate["source_receipts"]
    if change == "dirty":
        (root / "src/agentic_workbench/__init__.py").write_text("changed")
    elif change == "untracked":
        (root / "extra.py").write_text("changed")
    elif change == "stale":
        candidate["expected_commit"] = "0" * 40
    elif change == "image":
        candidate["node_image"] = "node:latest"
    elif change == "receipt":
        receipts["docker-node"].write_text(json.dumps({"commit": "0" * 40}))
    elif change in {"empty", "skip", "failure", "missing-case", "dtd"}:
        path = junit["docker-node"]
        text = path.read_text()
        if change == "empty":
            text = '<testsuite tests="0"/>'
        elif change == "skip":
            text = text.replace("/>", "><skipped/></testcase>", 1)
        elif change == "failure":
            text = text.replace('failures="0"', 'failures="1"')
        elif change == "missing-case":
            text = text.replace(module.NODE_CASES[0], "test_mocked")
        else:
            text = '<!DOCTYPE test [<!ENTITY x "value">]>' + text
        path.write_text(text)
    elif change == "version":
        candidate["expected_version"] = "9.9.9"
    else:
        path = next(candidate["artifacts"].glob("*.whl"))
        with zipfile.ZipFile(path) as archive:
            contents = {item.filename: archive.read(item) for item in archive.infolist()}
        if change == "tamper":
            contents["agentic_workbench/__init__.py"] = b"tampered"
        elif change == "missing-source":
            contents.pop("agentic_workbench/py.typed")
        elif change == "extra-runtime":
            contents["startup.pth"] = b"import injected"
        else:
            contents["../escape.py"] = b"bad"
        with zipfile.ZipFile(path, "w") as archive:
            for name, data in contents.items():
                archive.writestr(name, data)
    with pytest.raises(ValueError):
        module.collect(**candidate)


def test_sdist_tamper_is_rejected(candidate):
    path = next(candidate["artifacts"].glob("*.tar.gz"))
    with tarfile.open(path) as archive:
        contents = {
            member.name: archive.extractfile(member).read() for member in archive.getmembers()
        }
    contents["agentic_workbench-1.2.3/src/agentic_workbench/__init__.py"] = b"different"
    tar(path, contents)
    with pytest.raises(ValueError, match="source"):
        module.collect(**candidate)


def test_example_owner_file_cannot_mark_publication_ready(candidate):
    path = candidate["root"] / ".github/release-owner.example.json"
    path.parent.mkdir()
    path.write_text('{"publication_ready":true}')
    git(candidate["root"], "add", ".")
    git(
        candidate["root"],
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-m",
        "template",
    )
    commit = git(candidate["root"], "rev-parse", "HEAD")
    candidate["expected_commit"] = commit
    for path in candidate["source_receipts"].values():
        data = json.loads(path.read_text())
        data["commit"] = commit
        path.write_text(json.dumps(data))
    assert module.collect(**candidate)["publication_ready"] is False


def test_duplicate_timeout_cannot_replace_output_limit_acceptance(candidate):
    path = candidate["junit"]["docker-node"]
    text = (
        path.read_text().replace("stdout-overflow", "timeout").replace("stderr-overflow", "timeout")
    )
    path.write_text(text)
    with pytest.raises(ValueError, match="Node Docker"):
        module.collect(**candidate)


def test_utf16_entity_reports_are_forbidden(tmp_path):
    path = tmp_path / "report.xml"
    path.write_bytes(
        (
            '<?xml version="1.0" encoding="UTF-16"?>'
            '<!DOCTYPE report [<!ENTITY x "expanded">]>'
            '<testsuite><testcase name="&x;"/></testsuite>'
        ).encode("utf-16")
    )
    with pytest.raises(ValueError):
        module.suite(path, "python")


def test_unsafe_directory_entry_is_rejected(tmp_path):
    path = tmp_path / "source.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        directory = tarfile.TarInfo("../../outside")
        directory.type = tarfile.DIRTYPE
        archive.addfile(directory)
        info = tarfile.TarInfo("root/file")
        info.size = 1
        archive.addfile(info, io.BytesIO(b"x"))
    with pytest.raises(ValueError, match="Unsafe"):
        module.archive_files(path)


def test_wheel_cli_entrypoints_must_match_committed_project(candidate):
    path = next(candidate["artifacts"].glob("*.whl"))
    with zipfile.ZipFile(path) as archive:
        contents = {item.filename: archive.read(item) for item in archive.infolist()}
    contents["agentic_workbench-1.2.3.dist-info/entry_points.txt"] = (
        b"[console_scripts]\nagentic = os:_exit\n"
    )
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in contents.items():
            archive.writestr(name, data)
    with pytest.raises(ValueError, match="entry points"):
        module.collect(**candidate)
