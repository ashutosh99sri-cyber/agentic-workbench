"""Root confinement and host-owned permission checks for every source operation."""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path

from pathspec import GitIgnoreSpec

from .config import Config
from .errors import WorkbenchError
from .models import Grant, canonical_hash
from .secrets import SecretRedactor

_DIRECTORIES = {
    ".git",
    ".agentic",
    ".venv",
    ".venv-initial",
    "venv",
    "node_modules",
    "vendor",
    "dist",
    "build",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".cache",
    ".next",
    ".ssh",
    ".aws",
    ".idea",
    ".vscode",
    "htmlcov",
}
_FILES = {
    ".npmrc",
    ".pypirc",
    ".netrc",
    "id_rsa",
    "id_ed25519",
    "credentials",
    "credentials.json",
    "secrets.json",
    "secrets.toml",
    "authorized_keys",
    ".flaskenv",
    ".dev.vars",
}


@dataclass(frozen=True)
class SourceFile:
    path: str
    text: str
    source_hash: str
    size: int
    contains_secrets: bool


class WorkspacePolicy:
    def __init__(
        self,
        root: Path | str,
        config: Config | None = None,
        *,
        grants: Grant | None = None,
        redactor: SecretRedactor | None = None,
    ) -> None:
        original = Path(root).expanduser()
        if original.is_symlink():
            raise WorkbenchError("POLICY_DENIED", "Workspace root cannot be a symlink")
        try:
            self.root = original.resolve(strict=True)
            info = self.root.stat()
        except OSError as error:
            raise WorkbenchError("CONFIG_ERROR", "Workspace root is unavailable") from error
        if not stat.S_ISDIR(info.st_mode):
            raise WorkbenchError("CONFIG_ERROR", "Workspace root must be a directory")
        self._identity = (info.st_dev, info.st_ino)
        self.workspace_id = canonical_hash({"root": str(self.root), "identity": self._identity})
        self.config = config if config is not None else Config()
        self.grants = grants if grants is not None else Grant()
        self.redactor = (
            redactor
            if redactor is not None
            else SecretRedactor.from_environment([self.config.provider.credential_env])
        )
        self._exclusions = GitIgnoreSpec.from_lines(self.config.policy.excludes)

    @property
    def fingerprint(self) -> str:
        return canonical_hash(
            {
                "workspace": self.workspace_id,
                "config": self.config.fingerprint,
                "grants": asdict(self.grants),
            }
        )

    def parts(self, relative: str) -> tuple[str, ...]:
        if (
            not isinstance(relative, str)
            or not relative
            or len(relative) > 4096
            or any(ord(char) < 32 or ord(char) == 127 or char in "\\:" for char in relative)
        ):
            raise WorkbenchError("POLICY_DENIED", "Unsafe relative path")
        parts = tuple(relative.split("/"))
        if any(part in {"", ".", ".."} for part in parts):
            raise WorkbenchError("POLICY_DENIED", "Unsafe relative path")
        return parts

    def is_excluded(self, relative: str) -> bool:
        parts = self.parts(relative)
        leaf = parts[-1].lower()
        return (
            any(part.lower() in _DIRECTORIES for part in parts)
            or any(part.lower().startswith(".venv-") for part in parts)
            or leaf in _FILES
            # Environment files anywhere in the path: .env*, .envrc, .envs/, production.env
            or any(
                part.lower().startswith(".env") or part.lower().endswith(".env") for part in parts
            )
            or leaf.startswith(".dev.vars.")
            or leaf.endswith((".pem", ".key", ".p12", ".pfx"))
            or leaf.startswith(".agentic-stage-")
            or self._exclusions.match_file(relative)
        )

    def check_source(self, relative: str) -> tuple[str, ...]:
        parts = self.parts(relative)
        if self.is_excluded(relative):
            raise WorkbenchError("POLICY_DENIED", "Protected or excluded source path")
        return parts

    def _check_root(self) -> None:
        try:
            info = self.root.lstat()
        except OSError as error:
            raise WorkbenchError("CONFLICT", "Workspace identity changed") from error
        if not stat.S_ISDIR(info.st_mode) or (info.st_dev, info.st_ino) != self._identity:
            raise WorkbenchError("CONFLICT", "Workspace identity changed")

    @contextmanager
    def directory(self, parts: Sequence[str]) -> Iterator[int]:
        """Open a pinned POSIX directory chain; never resolve source symlinks."""
        if os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
            raise WorkbenchError("POLICY_DENIED", "Guarded directory access requires POSIX")
        self._check_root()
        descriptors: list[int] = []
        opened = False
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        try:
            fd = os.open(self.root, flags)
            descriptors.append(fd)
            info = os.fstat(fd)
            if (info.st_dev, info.st_ino) != self._identity:
                raise WorkbenchError("CONFLICT", "Workspace identity changed")
            for part in parts:
                if part in {"", ".", ".."} or "/" in part or "\\" in part:
                    raise WorkbenchError("POLICY_DENIED", "Unsafe directory component")
                fd = os.open(part, flags, dir_fd=fd)
                descriptors.append(fd)
            opened = True
            yield fd
        except OSError as error:
            if opened:
                raise
            raise WorkbenchError("POLICY_DENIED", "Unsafe or unavailable directory") from error
        finally:
            for descriptor in reversed(descriptors):
                os.close(descriptor)

    def _read_fd(self, fd: int) -> bytes:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise WorkbenchError("POLICY_DENIED", "Source must be an unaliased regular file")
        limit = self.config.scan.max_file_bytes
        if before.st_size > limit:
            raise WorkbenchError("LIMIT_EXCEEDED", "Source file exceeds byte limit")
        chunks: list[bytes] = []
        count = 0
        while True:
            block = os.read(fd, min(65_536, limit + 1 - count))
            if not block:
                break
            count += len(block)
            if count > limit:
                raise WorkbenchError("LIMIT_EXCEEDED", "Source file exceeds byte limit")
            chunks.append(block)
        after = os.fstat(fd)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise WorkbenchError("CONFLICT", "Source changed while being read")
        self._check_root()
        return b"".join(chunks)

    def read_bytes(self, relative: str) -> bytes:
        parts = self.check_source(relative)
        try:
            if os.name == "posix":
                with self.directory(parts[:-1]) as parent:
                    fd = os.open(
                        parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent
                    )
                    try:
                        return self._read_fd(fd)
                    finally:
                        os.close(fd)
            self._check_root()
            target = self.root.joinpath(*parts)
            current = self.root
            for part in parts:
                current /= part
                if current.is_symlink() or current.resolve() != current:
                    raise WorkbenchError("POLICY_DENIED", "Source aliases are prohibited")
            before = target.lstat()
            fd = os.open(target, os.O_RDONLY | getattr(os, "O_BINARY", 0))
            try:
                opened = os.fstat(fd)
                if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
                    raise WorkbenchError("CONFLICT", "Source identity changed")
                data = self._read_fd(fd)
                if target.resolve() != self.root.joinpath(*parts):
                    raise WorkbenchError("CONFLICT", "Source parent identity changed")
                return data
            finally:
                os.close(fd)
        except OSError as error:
            raise WorkbenchError("POLICY_DENIED", "Unsafe or unavailable source") from error

    def read_source(self, relative: str) -> SourceFile:
        data = self.read_bytes(relative)
        try:
            text = data.decode("utf-8")
        except UnicodeError as error:
            raise WorkbenchError("POLICY_DENIED", "Source is not UTF-8 text") from error
        if "\x00" in text:
            raise WorkbenchError("POLICY_DENIED", "Binary source is excluded")
        return SourceFile(
            relative,
            self.redactor.redact(text),
            hashlib.sha256(data).hexdigest(),
            len(data),
            self.redactor.contains_secret(text),
        )

    def check_write(self, relative: str) -> None:
        self.check_source(relative)
        self._check_root()
        if not self.grants.write or os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
            raise WorkbenchError(
                "POLICY_DENIED", "Source mutation requires a POSIX host write grant"
            )

    def check_network(self, host: str) -> None:
        if not self.grants.network or host not in self.grants.provider_hosts:
            raise WorkbenchError("POLICY_DENIED", "Provider network access requires a host grant")

    def prepare_state_dir(self) -> Path:
        self._check_root()
        if os.name == "posix":
            with self.directory(()) as parent:
                try:
                    os.mkdir(".agentic", mode=0o700, dir_fd=parent)
                except FileExistsError:
                    pass
                try:
                    fd = os.open(
                        ".agentic", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent
                    )
                    try:
                        info = os.fstat(fd)
                        if info.st_uid != os.geteuid() or info.st_mode & 0o077:
                            raise WorkbenchError("POLICY_DENIED", "State directory must be private")
                    finally:
                        os.close(fd)
                except OSError as error:
                    raise WorkbenchError("POLICY_DENIED", "Unsafe state directory") from error
        else:
            target = self.root / ".agentic"
            if target.is_symlink() or target.resolve() != target:
                raise WorkbenchError("POLICY_DENIED", "State aliases are prohibited")
            target.mkdir(mode=0o700, exist_ok=True)
        return self.root / ".agentic"
