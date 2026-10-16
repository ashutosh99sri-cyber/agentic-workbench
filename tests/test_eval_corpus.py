"""Corpus inputs cannot turn evaluation setup into arbitrary file/network access."""

from __future__ import annotations

import hashlib
import json
import stat
import zipfile
from pathlib import Path

import pytest

from agentic_workbench.errors import WorkbenchError
from agentic_workbench.eval_corpus import fetch_archive, load_corpus, materialize


def corpus_files(tmp_path: Path) -> Path:
    checks = tmp_path / "checks"
    checks.mkdir()
    (checks / "public.py").write_text("assert True\n")
    (checks / "hidden.py").write_text("assert True\n")
    task = {
        "id": "example-defect",
        "repo": "https://github.com/example/project",
        "buggy_commit": "a" * 40,
        "fixed_commit": "b" * 40,
        "summary": "A historical defect",
        "license": "MIT",
        "editable_paths": ["src/example.py"],
        "source_subdir": "src",
        "reproduction_file": "checks/public.py",
        "holdout_file": "checks/hidden.py",
    }
    (tmp_path / "manifest.json").write_text(json.dumps({"schema_version": 1, "tasks": [task]}))
    archives = [
        {
            "repo": task["repo"],
            "commit": commit,
            "url": f"https://codeload.github.com/example/project/zip/{commit}",
            "sha256": "c" * 64,
        }
        for commit in ("a" * 40, "b" * 40)
    ]
    (tmp_path / "archives.lock.json").write_text(
        json.dumps({"schema_version": 1, "archives": archives})
    )
    return tmp_path / "manifest.json"


def test_loads_explicit_source_and_separate_grader(tmp_path: Path) -> None:
    manifest = corpus_files(tmp_path)
    corpus = load_corpus(manifest)
    assert corpus.tasks[0].editable_paths == ("src/example.py",)
    assert corpus.tasks[0].holdout_file == tmp_path / "checks/hidden.py"
    assert len(corpus.archives) == 2


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("repo", "https://github.com/example/project?token=secret"),
        ("buggy_commit", "main"),
        ("editable_paths", ["../outside.py"]),
        ("editable_paths", ["tests/test_example.py"]),
        ("editable_paths", ["src/conftest.py"]),
        ("source_subdir", "../source"),
        ("reproduction_file", "../outside.py"),
    ],
)
def test_manifest_rejects_unpinned_or_escaping_inputs(
    tmp_path: Path, field: str, value: object
) -> None:
    manifest = corpus_files(tmp_path)
    data = json.loads(manifest.read_text())
    data["tasks"][0][field] = value
    manifest.write_text(json.dumps(data))
    with pytest.raises(WorkbenchError, match="CORPUS_INVALID"):
        load_corpus(manifest)


def test_corpus_does_not_count_duplicate_defects(tmp_path: Path) -> None:
    manifest = corpus_files(tmp_path)
    data = json.loads(manifest.read_text())
    duplicate = {**data["tasks"][0], "id": "renamed-same-defect"}
    data["tasks"].append(duplicate)
    manifest.write_text(json.dumps(data))
    with pytest.raises(WorkbenchError, match="CORPUS_INVALID"):
        load_corpus(manifest)


def test_archive_lock_is_bound_to_the_exact_official_url(tmp_path: Path) -> None:
    manifest = corpus_files(tmp_path)
    lock = tmp_path / "archives.lock.json"
    data = json.loads(lock.read_text())
    data["archives"][0]["url"] = "https://attacker.example/source.zip"
    lock.write_text(json.dumps(data))
    with pytest.raises(WorkbenchError, match="CORPUS_INVALID"):
        load_corpus(manifest)


def test_cache_is_offline_by_default_and_checks_bytes(tmp_path: Path) -> None:
    corpus = load_corpus(corpus_files(tmp_path))
    artifact = next(iter(corpus.archives.values()))
    cache = tmp_path / "cache"
    with pytest.raises(WorkbenchError, match="CORPUS_UNAVAILABLE"):
        fetch_archive(artifact, cache)
    cache.mkdir(exist_ok=True)
    (cache / f"{artifact.sha256}.zip").write_bytes(b"wrong cached bytes")
    with pytest.raises(WorkbenchError, match="CORPUS_INTEGRITY"):
        fetch_archive(artifact, cache)


def test_valid_cached_archive_never_needs_network(tmp_path: Path) -> None:
    manifest = corpus_files(tmp_path)
    payload = b"verified source archive"
    digest = hashlib.sha256(payload).hexdigest()
    lock = tmp_path / "archives.lock.json"
    data = json.loads(lock.read_text())
    data["archives"][0]["sha256"] = digest
    lock.write_text(json.dumps(data))
    artifact = next(iter(load_corpus(manifest).archives.values()))
    cache = tmp_path / "cache"
    cache.mkdir()
    expected = cache / f"{digest}.zip"
    expected.write_bytes(payload)
    assert fetch_archive(artifact, cache) == expected


@pytest.mark.parametrize("kind", ["traversal", "symlink", "case-alias", "two-roots"])
def test_rejects_unsafe_archives_before_writing(tmp_path: Path, kind: str) -> None:
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as stream:
        stream.writestr("project/src/module.py", "answer = 42\n")
        if kind == "traversal":
            stream.writestr("project/../../outside.py", "bad\n")
        elif kind == "symlink":
            entry = zipfile.ZipInfo("project/alias")
            entry.create_system = 3
            entry.external_attr = (stat.S_IFLNK | 0o777) << 16
            stream.writestr(entry, "../../outside")
        elif kind == "case-alias":
            stream.writestr("project/src/MODULE.py", "different\n")
        else:
            stream.writestr("other/module.py", "different\n")
    destination = tmp_path / "workspace"
    with pytest.raises(WorkbenchError, match="CORPUS_INVALID"):
        materialize(archive, destination)
    assert not destination.exists()
    assert not (tmp_path / "outside.py").exists()


def test_materializes_one_project_without_its_archive_prefix(tmp_path: Path) -> None:
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as stream:
        stream.writestr("project-commit/src/module.py", "answer = 42\n")
        stream.writestr("project-commit/LICENSE", "MIT\n")
    destination = tmp_path / "workspace"
    assert materialize(archive, destination) == destination
    assert (destination / "src/module.py").read_text() == "answer = 42\n"
    assert (destination / "LICENSE").read_text() == "MIT\n"
