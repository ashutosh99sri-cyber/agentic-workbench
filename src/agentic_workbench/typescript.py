"""Optional host-selected TypeScript 7 native structural analysis of source snapshots."""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import re
import stat
import subprocess
import tempfile
import threading
import time
from bisect import bisect_right
from io import BufferedReader
from pathlib import Path
from typing import Any, cast

from .errors import WorkbenchError
from .models import canonical_hash, canonical_json, strict_json
from .policy import SourceFile
from .runner import _environment, _kill

_MAX_BYTES = 8 * 1024 * 1024
_MAX_FACTS = 20_000
_EXTENSIONS = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts"}
_HASH = re.compile(r"[0-9a-f]{64}")
_HELPER = Path(__file__).parent / "parsers" / "typescript.mjs"


def _capture(argv: list[str], cwd: Path, timeout: float, data: bytes) -> dict[str, Any]:
    """Bound the combined pipes and kill the whole native compiler process group."""
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    lock = threading.Lock()
    overflow = threading.Event()
    total = 0
    try:
        process = subprocess.Popen(  # noqa: S603 - host-pinned executables and fixed bridge
            argv,
            cwd=cwd,
            env=_environment(cwd),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=os.name == "posix",
        )
    except OSError:
        raise WorkbenchError(
            "INTEGRATION_UNAVAILABLE", "Trusted TypeScript parser cannot start"
        ) from None

    def read(name: str) -> None:
        nonlocal total
        stream = process.stdout if name == "stdout" else process.stderr
        assert stream is not None
        while block := cast(BufferedReader, stream).read1(65_536):
            with lock:
                buffers[name].extend(block[: max(0, _MAX_BYTES - total)])
                total += len(block)
                if total > _MAX_BYTES:
                    overflow.set()
        stream.close()

    def write() -> None:
        assert process.stdin is not None
        try:
            process.stdin.write(data)
        except (BrokenPipeError, OSError):
            pass
        finally:
            try:
                process.stdin.close()
            except (BrokenPipeError, OSError):
                pass

    threads = [threading.Thread(target=read, args=(name,), daemon=True) for name in buffers]
    threads.append(threading.Thread(target=write, daemon=True))
    for thread in threads:
        thread.start()
    timed_out = False
    try:
        deadline = time.monotonic() + timeout
        while process.poll() is None:
            remaining = deadline - time.monotonic()
            if overflow.is_set() or remaining <= 0:
                timed_out = remaining <= 0 and not overflow.is_set()
                break
            overflow.wait(min(0.05, remaining))
    finally:
        _kill(process)
        process.wait(timeout=5)
        for thread in threads:
            thread.join(timeout=5)
    return {
        "exit_code": process.returncode,
        "timed_out": timed_out,
        "output_limited": overflow.is_set(),
        **{name: value.decode("utf-8", errors="replace") for name, value in buffers.items()},
    }


def _file_pin(path: Path) -> str:
    info = path.stat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_mode & 0o022
        or os.name == "posix"
        and info.st_uid not in {0, os.geteuid()}
    ):
        raise WorkbenchError("INTEGRATION_UNAVAILABLE", "Parser files must be trusted host files")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1_048_576):
            digest.update(block)
    after = path.stat()
    if (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise WorkbenchError("CONFLICT", "Trusted parser changed while reading")
    return digest.hexdigest()


class TypeScriptAnalyzer:
    """Trusted host integration; never construct it from repository or model arguments."""

    def __init__(
        self, node_executable: Path, typescript_package: Path, timeout: float = 15
    ) -> None:
        if (
            type(timeout) not in {int, float}
            or not 0 < timeout <= 120
            or not math.isfinite(timeout)
        ):
            raise WorkbenchError("VALIDATION_ERROR", "Parser timeout must be within 0..120 seconds")
        self.timeout = timeout
        try:
            if not node_executable.is_absolute() or not typescript_package.is_absolute():
                raise WorkbenchError("INTEGRATION_UNAVAILABLE", "Parser paths must be absolute")
            self.node_executable = node_executable.resolve(strict=True)
            self.typescript_package = typescript_package.resolve(strict=True)
            metadata = json.loads((self.typescript_package / "package.json").read_text())
            if metadata.get("name") != "typescript" or metadata.get("version") != "7.0.2":
                raise WorkbenchError("INTEGRATION_UNAVAILABLE", "TypeScript 7.0.2 is required")
            system = {"Darwin": "darwin", "Linux": "linux", "Windows": "win32"}.get(
                platform.system()
            )
            architecture = {
                "arm64": "arm64",
                "aarch64": "arm64",
                "x86_64": "x64",
                "AMD64": "x64",
            }.get(platform.machine())
            if system is None or architecture is None or os.name != "posix":
                raise WorkbenchError(
                    "INTEGRATION_UNAVAILABLE",
                    "Native parser process control requires supported POSIX",
                )
            native_package = (
                self.typescript_package.parent
                / "@typescript"
                / f"typescript-{system}-{architecture}"
            )
            self.native_metadata = native_package / "package.json"
            native_metadata = json.loads(self.native_metadata.read_text())
            if native_metadata.get("version") != "7.0.2":
                raise WorkbenchError(
                    "INTEGRATION_UNAVAILABLE", "TypeScript native package version differs"
                )
            self.native_executable = (native_package / "lib" / "tsc").resolve(strict=True)
            self._pins = self._identity()
            self.fingerprint = canonical_hash(self._pins)
        except (OSError, ValueError, TypeError, AttributeError):
            raise WorkbenchError(
                "INTEGRATION_UNAVAILABLE", "Trusted TypeScript 7.0.2 is unavailable"
            ) from None

    def _identity(self) -> dict[str, str]:
        paths = [
            self.node_executable,
            self.native_executable,
            self.native_metadata,
            _HELPER,
            self.typescript_package / "package.json",
        ]
        paths.extend(sorted(self.typescript_package.rglob("*.js")))
        paths.extend(sorted(self.typescript_package.rglob("*.cjs")))
        return {str(path): _file_pin(path) for path in paths}

    def analyze(self, sources: dict[str, SourceFile]) -> dict[str, Any]:
        if not isinstance(sources, dict) or len(sources) > 1000:
            raise WorkbenchError("LIMIT_EXCEEDED", "Parser source count exceeds 1000")
        selected: dict[str, SourceFile] = {}
        secret_count = 0
        total = 0
        if any(not isinstance(path, str) for path in sources):
            raise WorkbenchError("VALIDATION_ERROR", "Invalid parser source path")
        for path, source in sorted(sources.items()):
            if (
                not isinstance(path, str)
                or not path
                or len(path) > 4096
                or any(part in {"", ".", ".."} for part in path.split("/"))
                or any(ord(char) < 32 or ord(char) == 127 or char in "\\:" for char in path)
                or not isinstance(source, SourceFile)
                or path != source.path
                or not isinstance(source.text, str)
                or not isinstance(source.source_hash, str)
                or not _HASH.fullmatch(source.source_hash)
                or type(source.size) is not int
                or source.size < 0
                or type(source.contains_secrets) is not bool
            ):
                raise WorkbenchError("VALIDATION_ERROR", "Invalid parser source snapshot")
            if Path(path).suffix.lower() not in _EXTENSIONS:
                continue
            try:
                total += len(source.text.encode("utf-8"))
            except UnicodeError:
                raise WorkbenchError(
                    "VALIDATION_ERROR", "Invalid Unicode source snapshot"
                ) from None
            if total > _MAX_BYTES:
                raise WorkbenchError("LIMIT_EXCEEDED", "Parser snapshots exceed 8 MiB")
            if source.contains_secrets:
                secret_count += 1
            else:
                selected[path] = source
        self.verify()
        data = canonical_json(
            {
                "version": 1,
                "sources": [
                    {"path": source.path, "text": source.text, "source_hash": source.source_hash}
                    for source in selected.values()
                ],
            }
        ).encode()
        if len(data) > _MAX_BYTES:
            raise WorkbenchError("LIMIT_EXCEEDED", "Parser input exceeds 8 MiB")
        with tempfile.TemporaryDirectory(prefix="agentic-typescript-") as temporary:
            outcome = _capture(
                [
                    str(self.node_executable),
                    "--max-old-space-size=256",
                    str(_HELPER),
                    str(self.typescript_package),
                    str(self.native_executable),
                ],
                Path(temporary),
                self.timeout,
                data,
            )
        if outcome["timed_out"]:
            raise WorkbenchError("LIMIT_EXCEEDED", "TypeScript parser timed out")
        if outcome["output_limited"]:
            raise WorkbenchError("LIMIT_EXCEEDED", "TypeScript parser output exceeds 8 MiB")
        if outcome["exit_code"] != 0:
            raise WorkbenchError("INTEGRATION_ERROR", "TypeScript parser failed")
        self.verify()
        try:
            result = self._validate(strict_json(outcome["stdout"], _MAX_BYTES), selected)
        except (KeyError, TypeError, ValueError, WorkbenchError):
            raise WorkbenchError(
                "INTEGRATION_ERROR", "TypeScript parser returned invalid facts"
            ) from None
        result["coverage"]["secret_files_skipped"] = secret_count
        result["coverage"]["files_eligible"] = len(selected) + secret_count
        result["parser"]["fingerprint"] = self.fingerprint
        return result

    def verify(self) -> None:
        """Recheck trusted runtime pins before using cached structural facts."""
        try:
            if self._identity() == self._pins:
                return
        except OSError:
            pass
        raise WorkbenchError("CONFLICT", "Trusted parser identity changed")

    def _validate(self, value: Any, sources: dict[str, SourceFile]) -> dict[str, Any]:
        if (
            not isinstance(value, dict)
            or value.get("version") != 1
            or value.get("parser") != {"name": "typescript-native", "version": "7.0.2", "bridge": 1}
        ):
            raise ValueError
        coverage = value["coverage"]
        if not isinstance(coverage, dict) or set(coverage) != {
            "files_analyzed",
            "parse_errors",
            "nodes_visited",
            "facts_truncated",
        }:
            raise ValueError
        if any(type(count) is not int or not 0 <= count <= 200_000 for count in coverage.values()):
            raise ValueError
        if coverage["files_analyzed"] > len(sources):
            raise ValueError
        limitations = value["limitations"]
        if (
            not isinstance(limitations, list)
            or len(limitations) > 20
            or any(not isinstance(item, str) or len(item) > 1024 for item in limitations)
        ):
            raise ValueError
        keys: dict[str, str] = {}
        positions: dict[str, tuple[bytes, list[int], list[int]]] = {}
        for source in sources.values():
            starts = [0]
            previous = units = 0
            for match in re.finditer(r"\r\n|[\r\n\u2028\u2029]", source.text):
                units += len(source.text[previous : match.end()].encode("utf-16-le")) // 2
                starts.append(units)
                previous = match.end()
            # Evidence follows the SDK reader's splitlines convention, not TS diagnostics.
            evidence_starts = [0]
            previous = units = 0
            for match in re.finditer(r"\r\n|[\r\n\v\f\x1c-\x1e\x85\u2028\u2029]", source.text):
                units += len(source.text[previous : match.end()].encode("utf-16-le")) // 2
                evidence_starts.append(units)
                previous = match.end()
            positions[source.path] = (source.text.encode("utf-16-le"), starts, evidence_starts)
        groups = ("symbols", "calls", "imports", "references")
        if (
            any(not isinstance(value[group], list) for group in groups)
            or sum(len(value[group]) for group in groups) > _MAX_FACTS
        ):
            raise ValueError
        result: dict[str, Any] = {
            "coverage": coverage,
            "parser": value["parser"],
            "limitations": limitations,
        }
        for group in groups:
            result[group] = []
            for row in value[group]:
                if not isinstance(row, dict):
                    raise ValueError
                source = sources[row["path"]]
                start, end = row["start"], row["end"]
                encoded, starts, evidence_starts = positions[source.path]
                length = len(encoded) // 2
                if (
                    type(start) is not int
                    or type(end) is not int
                    or not 0 <= start <= end <= length
                ):
                    raise ValueError
                for position in (start, end):
                    if 0 < position < length and (
                        0xD800
                        <= int.from_bytes(encoded[(position - 1) * 2 : position * 2], "little")
                        <= 0xDBFF
                        and 0xDC00
                        <= int.from_bytes(encoded[position * 2 : (position + 1) * 2], "little")
                        <= 0xDFFF
                    ):
                        raise ValueError

                if (
                    row["source_hash"] != source.source_hash
                    or type(row["start_line"]) is not int
                    or type(row["end_line"]) is not int
                    or row["start_line"] != bisect_right(starts, start)
                    or row["end_line"] != bisect_right(starts, max(start, end - 1))
                ):
                    raise ValueError
                normalized: dict[str, Any] = {
                    "evidence": {
                        "path": source.path,
                        "source_hash": source.source_hash,
                        "start_line": bisect_right(evidence_starts, start),
                        "end_line": bisect_right(evidence_starts, max(start, end - 1)),
                    },
                    "language": "typescript"
                    if Path(source.path).suffix.lower() in {".ts", ".tsx", ".mts", ".cts"}
                    else "javascript",
                }
                names = {
                    "symbols": ("name", "kind"),
                    "calls": ("callee",),
                    "imports": ("module", "imported", "local"),
                    "references": ("name",),
                }[group]
                for name in names:
                    if not isinstance(row[name], str) or len(row[name]) > 4096:
                        raise ValueError
                    normalized[name] = row[name]
                if group == "symbols":
                    key = canonical_json([source.path, start, end])
                    if row["key"] != key or key in keys:
                        raise ValueError
                    normalized["id"] = canonical_hash(
                        {
                            "path": source.path,
                            "start": start,
                            "end": end,
                            "source_hash": source.source_hash,
                        }
                    )
                    keys[key] = normalized["id"]
                else:
                    if row["resolution"] not in {
                        "declaration",
                        "unresolved",
                        "ambiguous",
                        "dynamic",
                    }:
                        raise ValueError
                    normalized["resolution"] = row["resolution"]
                    if row["resolution"] == "declaration":
                        normalized["target_id"] = keys[row["target"]]
                    elif "target" in row:
                        raise ValueError
                result[group].append(normalized)
        return result
