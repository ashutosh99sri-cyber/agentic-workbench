"""POSIX single-writer lock and no-follow, directory-relative atomic replacements."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from .errors import WorkbenchError
from .policy import WorkspacePolicy


@contextmanager
def writer_lock(policy: WorkspacePolicy) -> Iterator[None]:
    if os.name != "posix":
        raise WorkbenchError("POLICY_DENIED", "Guarded writes require POSIX")
    import fcntl

    policy.prepare_state_dir()
    with policy.directory((".agentic",)) as directory:
        fd = os.open("write.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        try:
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or info.st_mode & 0o077
                or info.st_uid != os.geteuid()
            ):
                raise WorkbenchError("POLICY_DENIED", "Unsafe writer lock")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise WorkbenchError("CONFLICT", "Another workspace writer is active") from error
            yield
        finally:
            os.close(fd)


def _identity(info: os.stat_result) -> list[int]:
    return [info.st_dev, info.st_ino]


def ensure_parents(
    policy: WorkspacePolicy,
    relative: str,
    created: list[dict[str, Any]],
    *,
    persist: Callable[[], None],
) -> None:
    parts = policy.check_source(relative)
    policy.check_write(relative)
    for depth in range(1, len(parts)):
        with policy.directory(parts[: depth - 1]) as parent:
            try:
                info = os.stat(parts[depth - 1], dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                record: dict[str, Any] = {
                    "path": "/".join(parts[:depth]),
                    "parent_identity": _identity(os.fstat(parent)),
                    "identity": None,
                    "state": "pending",
                }
                created.append(record)
                persist()
                try:
                    os.mkdir(parts[depth - 1], mode=0o755, dir_fd=parent)
                except FileExistsError as error:
                    record["state"] = "not_created"
                    persist()
                    raise WorkbenchError(
                        "CONFLICT", "Source parent appeared before creation"
                    ) from error
                os.fsync(parent)
                with policy.directory(parts[:depth]) as opened:
                    record["identity"] = _identity(os.fstat(opened))
                record["state"] = "created"
                persist()
            else:
                if not stat.S_ISDIR(info.st_mode):
                    raise WorkbenchError("POLICY_DENIED", "Unsafe source parent")
        with policy.directory(parts[:depth]):
            pass


def _clean_stage(policy: WorkspacePolicy, record: dict[str, Any]) -> str | None:
    if record.get("state") == "cleaned":
        return None
    parts = policy.parts(record["path"])
    target = policy.parts(record["target"])
    policy.check_write(record["target"])
    if parts[:-1] != target[:-1] or not re.fullmatch(r"[.]agentic-stage-[a-f0-9]{32}", parts[-1]):
        raise WorkbenchError("POLICY_DENIED", "Invalid recorded stage path")
    try:
        with policy.directory(parts[:-1]) as parent:
            if _identity(os.fstat(parent)) != record["parent_identity"]:
                return "stage_parent_changed"
            try:
                info = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                record["state"] = "cleaned"
                return None
            if record.get("identity") is None:
                return "stage_creation_unknown"
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or info.st_uid != os.geteuid()
                or _identity(info) != record["identity"]
            ):
                return "stage_identity_changed"
            fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            try:
                if _identity(os.fstat(fd)) != record["identity"]:
                    return "stage_identity_changed"
                if hashlib.sha256(policy._read_fd(fd)).hexdigest() not in record["hashes"]:
                    return "stage_content_changed"
                current = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
                if _identity(current) != record["identity"]:
                    return "stage_identity_changed"
                os.unlink(parts[-1], dir_fd=parent)
                os.fsync(parent)
                record["state"] = "cleaned"
                return None
            finally:
                os.close(fd)
    except (OSError, WorkbenchError):
        return "stage_cleanup_unavailable"


def cleanup_stages(
    policy: WorkspacePolicy,
    records: list[dict[str, Any]],
    *,
    persist: Callable[[], None],
) -> list[str]:
    issues = []
    for record in records:
        issue = _clean_stage(policy, record)
        if issue:
            issues.append(f"{issue}:{record['path']}")
        persist()
    return issues


def replace_source(
    policy: WorkspacePolicy,
    relative: str,
    content: str | None,
    mode: int,
    expected_hash: str | None,
    *,
    stages: list[dict[str, Any]],
    persist: Callable[[], None],
) -> None:
    policy.check_write(relative)
    parts = policy.parts(relative)
    with policy.directory(parts[:-1]) as parent:
        record: dict[str, Any] | None = None
        try:
            if content is not None:
                staged = f".agentic-stage-{uuid.uuid4().hex}"
                data = content.encode("utf-8")
                full_hash = hashlib.sha256(data).hexdigest()
                record = {
                    "path": "/".join((*parts[:-1], staged)),
                    "target": relative,
                    "parent_identity": _identity(os.fstat(parent)),
                    "identity": None,
                    "hashes": [hashlib.sha256(b"").hexdigest(), full_hash],
                    "state": "pending",
                }
                stages.append(record)
                persist()
                fd = os.open(
                    staged,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    mode & 0o777,
                    dir_fd=parent,
                )
                try:
                    record["identity"] = _identity(os.fstat(fd))
                    record["state"] = "writing"
                    persist()
                    offset = 0
                    while offset < len(data):
                        end = min(offset + 65_536, len(data))
                        record["hashes"] = [
                            hashlib.sha256(data[:offset]).hexdigest(),
                            hashlib.sha256(data[:end]).hexdigest(),
                        ]
                        persist()
                        written = os.write(fd, data[offset:end])
                        if written <= 0:
                            raise WorkbenchError("STATE_ERROR", "Stage write made no progress")
                        offset += written
                        os.fsync(fd)
                        record["hashes"] = [hashlib.sha256(data[:offset]).hexdigest(), full_hash]
                        persist()
                    os.fchmod(fd, mode & 0o777)
                    os.fsync(fd)
                    record["hashes"] = [full_hash]
                    record["state"] = "ready"
                    persist()
                finally:
                    os.close(fd)
            with policy.directory(parts[:-1]) as current:
                if (os.fstat(current).st_dev, os.fstat(current).st_ino) != (
                    os.fstat(parent).st_dev,
                    os.fstat(parent).st_ino,
                ):
                    raise WorkbenchError("CONFLICT", "Source parent changed before replacement")
                try:
                    target = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
                    if not stat.S_ISREG(target.st_mode) or target.st_nlink != 1:
                        raise WorkbenchError("POLICY_DENIED", "Unsafe replacement target")
                    source_fd = os.open(
                        parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent
                    )
                    try:
                        opened = os.fstat(source_fd)
                        if (target.st_dev, target.st_ino) != (opened.st_dev, opened.st_ino):
                            raise WorkbenchError(
                                "CONFLICT", "Target identity changed before replacement"
                            )
                        if hashlib.sha256(policy._read_fd(source_fd)).hexdigest() != expected_hash:
                            raise WorkbenchError(
                                "CONFLICT", "Source changed while replacement was staged"
                            )
                    finally:
                        os.close(source_fd)
                except FileNotFoundError:
                    if content is None or expected_hash is not None:
                        raise WorkbenchError("CONFLICT", "Deletion target disappeared") from None
                if content is None:
                    os.unlink(parts[-1], dir_fd=parent)
                else:
                    os.replace(staged, parts[-1], src_dir_fd=parent, dst_dir_fd=parent)
                os.fsync(parent)
        finally:
            if record is not None:
                issue = _clean_stage(policy, record)
                if issue is None:
                    persist()


def remove_created_directories(
    policy: WorkspacePolicy,
    records: list[dict[str, Any] | str],
    *,
    persist: Callable[[], None],
) -> list[str]:
    issues = []
    for record in reversed(records):
        if isinstance(record, str):
            issues.append(f"legacy_directory_ownership_unknown:{record}")
            continue
        if record.get("state") in {"removed", "not_created"}:
            continue
        policy.check_write(record["path"])
        parts = policy.parts(record["path"])
        try:
            with policy.directory(parts[:-1]) as parent:
                if _identity(os.fstat(parent)) != record["parent_identity"]:
                    issues.append(f"directory_parent_changed:{record['path']}")
                    continue
                try:
                    info = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
                except FileNotFoundError:
                    record["state"] = "removed"
                    persist()
                    continue
                if record.get("identity") is None:
                    issues.append(f"directory_creation_unknown:{record['path']}")
                elif (
                    not stat.S_ISDIR(info.st_mode)
                    or _identity(info) != record["identity"]
                    or info.st_uid != os.geteuid()
                ):
                    issues.append(f"directory_identity_changed:{record['path']}")
                else:
                    os.rmdir(parts[-1], dir_fd=parent)
                    os.fsync(parent)
                    record["state"] = "removed"
                    persist()
        except (OSError, WorkbenchError):
            issues.append(f"directory_cleanup_unavailable:{record['path']}")
    return issues
