"""Pinned public-source corpus inputs; setup never grants execution authority."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import tempfile
import unicodedata
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn

from .errors import WorkbenchError
from .models import strict_json

_ARCHIVE_BYTES = 33_554_432
_EXPANDED_BYTES = 134_217_728
_MEMBER_BYTES = 8_388_608
_MEMBERS = 20_000


@dataclass(frozen=True)
class CorpusTask:
    id: str
    repo: str
    buggy_commit: str
    fixed_commit: str
    summary: str
    license: str
    editable_paths: tuple[str, ...]
    source_subdir: str
    reproduction_file: Path
    holdout_file: Path


@dataclass(frozen=True)
class Archive:
    repo: str
    commit: str
    url: str
    sha256: str
    bytes: int | None = None

    def __post_init__(self) -> None:
        repo, commit = _repo(self.repo), _commit(self.commit)
        expected = (
            f"https://codeload.github.com/{repo.removeprefix('https://github.com/')}/zip/{commit}"
        )
        if (
            self.url != expected
            or not re.fullmatch(r"[0-9a-f]{64}", self.sha256)
            or (
                self.bytes is not None
                and (type(self.bytes) is not int or not 1 <= self.bytes <= _ARCHIVE_BYTES)
            )
        ):
            _invalid("Archive descriptor must match its pinned official source")


@dataclass(frozen=True)
class Corpus:
    tasks: tuple[CorpusTask, ...]
    archives: dict[tuple[str, str], Archive]


def _invalid(message: str) -> NoReturn:
    raise WorkbenchError("CORPUS_INVALID", message)


def _text(value: Any, maximum: int = 4096) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= maximum
        or any(ord(c) < 32 for c in value)
    ):
        _invalid("Corpus text is missing or invalid")
    return value


def _relative(value: Any, *, root: bool = False) -> str:
    text = _text(value)
    if text == "." and root:
        return text
    path = PurePosixPath(text)
    if (
        path.is_absolute()
        or "\\" in text
        or ":" in text
        or any(part in {"", ".", ".."} for part in text.split("/"))
    ):
        _invalid("Corpus paths must remain relative to their declared root")
    return text


def _source(value: Any) -> str:
    text = _relative(value)
    path = PurePosixPath(text)
    if (
        path.suffix != ".py"
        or any(part in {"test", "tests"} for part in path.parts)
        or path.name == "conftest.py"
        or path.name.startswith("test_")
        or path.name.endswith("_test.py")
    ):
        _invalid("Editable corpus paths must be Python source, excluding test machinery")
    return text


def _repo(value: Any) -> str:
    text = _text(value)
    if not re.fullmatch(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", text):
        _invalid("Corpus sources require an explicit GitHub repository")
    return text


def _commit(value: Any) -> str:
    text = _text(value, 40)
    if not re.fullmatch(r"[0-9a-f]{40}", text):
        _invalid("Corpus commits must be full immutable Git hashes")
    return text


def _check(root: Path, value: Any) -> Path:
    path = root / _relative(value)
    if (
        path.suffix != ".py"
        or path.is_symlink()
        or not path.is_file()
        or not path.resolve().is_relative_to(root.resolve())
        or path.stat().st_size > 262_144
    ):
        _invalid("Corpus checks must be bounded regular Python files inside the corpus")
    return path


def load_corpus(manifest: Path) -> Corpus:
    """Validate task and artifact identity before any network or executable work."""
    try:
        data = strict_json(manifest.read_text(), 2_097_152)
        lock = strict_json(manifest.with_name("archives.lock.json").read_text(), 2_097_152)
    except (OSError, UnicodeError, WorkbenchError):
        _invalid("Cannot read valid corpus manifest and archive lock")
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        _invalid("Unsupported corpus manifest version")
    if not isinstance(lock, dict) or lock.get("schema_version") != 1:
        _invalid("Unsupported corpus archive lock version")
    rows, entries = data.get("tasks"), lock.get("archives")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 1000:
        _invalid("Corpus task count is outside its bounds")
    if not isinstance(entries, list) or not 1 <= len(entries) <= 2000:
        _invalid("Corpus archive count is outside its bounds")
    archives: dict[tuple[str, str], Archive] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            _invalid("Invalid corpus archive descriptor")
        repo, commit = _repo(entry.get("repo")), _commit(entry.get("commit"))
        url = f"https://codeload.github.com/{repo.removeprefix('https://github.com/')}/zip/{commit}"
        digest = _text(entry.get("sha256"), 64)
        size = entry.get("bytes")
        if (
            entry.get("url") != url
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
            or (size is not None and (type(size) is not int or not 1 <= size <= _ARCHIVE_BYTES))
            or (repo, commit) in archives
        ):
            _invalid("Archive lock does not match its pinned official source")
        archives[repo, commit] = Archive(repo, commit, url, digest, size)
    tasks: list[CorpusTask] = []
    ids: set[str] = set()
    defects: set[tuple[str, str, str]] = set()
    for row in rows:
        if not isinstance(row, dict):
            _invalid("Invalid corpus task")
        identifier, repo = _text(row.get("id"), 100), _repo(row.get("repo"))
        buggy, fixed = _commit(row.get("buggy_commit")), _commit(row.get("fixed_commit"))
        paths = row.get("editable_paths")
        if (
            not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", identifier)
            or identifier in ids
            or buggy == fixed
            or (repo, buggy, fixed) in defects
            or not isinstance(paths, list)
            or not 1 <= len(paths) <= 20
        ):
            _invalid("Corpus task identity or source scope is invalid or duplicated")
        editable = tuple(_source(path) for path in paths)
        if len(set(editable)) != len(editable):
            _invalid("Corpus edit scope contains duplicates")
        if any((repo, commit) not in archives for commit in (buggy, fixed)):
            _invalid("Corpus source is missing from its archive lock")
        reproduction = _check(manifest.parent, row.get("reproduction_file"))
        holdout = _check(manifest.parent, row.get("holdout_file"))
        if reproduction.resolve() == holdout.resolve():
            _invalid("Public and holdout checks must be separate files")
        tasks.append(
            CorpusTask(
                identifier,
                repo,
                buggy,
                fixed,
                _text(row.get("summary")),
                _text(row.get("license"), 200),
                editable,
                _relative(row.get("source_subdir"), root=True),
                reproduction,
                holdout,
            )
        )
        ids.add(identifier)
        defects.add((repo, buggy, fixed))
    return Corpus(tuple(tasks), archives)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        return None


def fetch_archive(artifact: Archive, cache: Path, *, download: bool = False) -> Path:
    """Read a verified cache entry; downloading is a separate explicit host choice."""
    cache.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = cache / f"{artifact.sha256}.zip"
    if target.exists() or target.is_symlink():
        if (
            target.is_symlink()
            or not target.is_file()
            or target.stat().st_size > _ARCHIVE_BYTES
            or (artifact.bytes is not None and target.stat().st_size != artifact.bytes)
            or hashlib.sha256(target.read_bytes()).hexdigest() != artifact.sha256
        ):
            raise WorkbenchError("CORPUS_INTEGRITY", "Cached archive differs from its lock")
        return target
    if not download:
        raise WorkbenchError("CORPUS_UNAVAILABLE", "Pinned archive is absent; fetch it explicitly")
    descriptor, temporary = tempfile.mkstemp(prefix="archive-", dir=cache)
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        # Archive validates the exact HTTPS host, repository and commit URL.
        request = urllib.request.Request(  # noqa: S310
            artifact.url, headers={"User-Agent": "Agentic-Workbench"}
        )
        with os.fdopen(descriptor, "wb") as output, opener.open(request, timeout=30) as response:
            size = 0
            digest = hashlib.sha256()
            while chunk := response.read(65_536):
                size += len(chunk)
                if size > _ARCHIVE_BYTES:
                    raise WorkbenchError(
                        "CORPUS_INTEGRITY", "Source archive exceeds its byte limit"
                    )
                output.write(chunk)
                digest.update(chunk)
        if digest.hexdigest() != artifact.sha256 or (
            artifact.bytes is not None and size != artifact.bytes
        ):
            raise WorkbenchError("CORPUS_INTEGRITY", "Downloaded archive differs from its lock")
        os.replace(temporary, target)
    except (OSError, urllib.error.URLError):
        raise WorkbenchError("CORPUS_UNAVAILABLE", "Cannot fetch pinned public source") from None
    finally:
        Path(temporary).unlink(missing_ok=True)
    return target


def materialize(archive: Path, destination: Path) -> Path:
    """Extract one bounded regular-file project into a new disposable directory."""
    if destination.exists() or destination.is_symlink():
        _invalid("Corpus destination must be a new directory")
    if archive.is_symlink() or not archive.is_file() or archive.stat().st_size > _ARCHIVE_BYTES:
        _invalid("Source archive must be a bounded regular file")
    try:
        with zipfile.ZipFile(archive) as stream:
            entries = stream.infolist()
            if not entries or len(entries) > _MEMBERS:
                _invalid("Source archive entry count exceeds its limit")
            total = 0
            roots: set[str] = set()
            aliases: set[str] = set()
            prepared: list[tuple[zipfile.ZipInfo, PurePosixPath]] = []
            for entry in entries:
                name = _relative(entry.filename.rstrip("/"))
                path = PurePosixPath(name)
                roots.add(path.parts[0])
                alias = unicodedata.normalize("NFC", name).casefold()
                kind = stat.S_IFMT(entry.external_attr >> 16)
                total += entry.file_size
                if (
                    alias in aliases
                    or kind not in {0, stat.S_IFREG, stat.S_IFDIR}
                    or entry.file_size > _MEMBER_BYTES
                    or total > _EXPANDED_BYTES
                    or entry.flag_bits & 1
                    or (len(path.parts) == 1 and not entry.is_dir())
                ):
                    _invalid("Source archive contains unsafe or oversized entries")
                aliases.add(alias)
                if len(path.parts) > 1:
                    prepared.append((entry, PurePosixPath(*path.parts[1:])))
            if len(roots) != 1:
                _invalid("Source archive must contain exactly one project root")
            destination.mkdir(parents=True, mode=0o700)
            for entry, relative in prepared:
                target = destination.joinpath(*relative.parts)
                if entry.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with stream.open(entry) as source, target.open("xb") as output:
                        written = 0
                        while chunk := source.read(65_536):
                            written += len(chunk)
                            if written > _MEMBER_BYTES:
                                _invalid("Expanded source file exceeds its byte limit")
                            output.write(chunk)
                    if written != entry.file_size:
                        _invalid("Source archive file length is inconsistent")
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError):
        _invalid("Cannot materialize a valid bounded source archive")
    return destination
