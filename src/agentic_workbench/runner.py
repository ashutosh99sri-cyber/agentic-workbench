"""Reviewed test execution in a disposable Docker or explicit trusted-host snapshot."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import signal
import stat
import subprocess
import tempfile
import threading
import time
from io import BufferedReader
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from .config import CommandConfig
from .errors import WorkbenchError
from .models import canonical_hash, strict_json
from .policy import SourceFile, WorkspacePolicy
from .repository import scan_workspace
from .state import StateStore
from .writer import writer_lock

_OWNER_LABEL = "io.agentic-workbench.owner"
_SHELLS = {"sh", "bash", "zsh", "dash", "fish", "cmd", "pwsh", "powershell", "env", "busybox"}
_DOCKER_FLAGS = [
    "--pull=never",
    "--network=none",
    "--read-only",
    "--user=65534:65534",
    "--cap-drop=ALL",
    "--security-opt=no-new-privileges",
    "--pids-limit=64",
    "--memory=256m",
    "--memory-swap=256m",
    "--cpus=1",
    "--ulimit=nofile=256:256",
    "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=16m,mode=1777",
    "--shm-size=16m",
    "--no-healthcheck",
    "--log-driver=none",
    "--workdir=/workspace",
    "--env=HOME=/tmp",
    "--env=TMPDIR=/tmp",
]


def _environment(home: Path) -> dict[str, str]:
    result = {
        "PATH": os.environ.get("PATH", os.defpath),
        "HOME": str(home),
        "TMPDIR": str(home),
        "TEMP": str(home),
        "TMP": str(home),
        "LANG": "C.UTF-8",
    }
    for name in ("SystemRoot", "WINDIR"):
        if name in os.environ:
            result[name] = os.environ[name]
    return result


def _kill(process: subprocess.Popen[bytes]) -> None:
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except ProcessLookupError:
        pass
    except PermissionError:
        try:
            # Darwin can report EPERM for a zombie-only group until its leader is reaped.
            process.wait(timeout=5)
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except (PermissionError, subprocess.TimeoutExpired):
            raise WorkbenchError(
                "EXECUTION_ERROR", "The execution process group could not be terminated"
            ) from None


def _capture(argv: list[str], cwd: Path, timeout: int, maximum: int) -> dict[str, Any]:
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    lock = threading.Lock()
    overflow = threading.Event()
    count = 0
    limited = False
    timed_out = False
    try:
        process = subprocess.Popen(  # noqa: S603 - reviewed argv, trusted executable, no shell
            argv,
            cwd=cwd,
            env=_environment(cwd),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=os.name == "posix",
        )
    except OSError:
        raise WorkbenchError("EXECUTION_ERROR", "The reviewed executable could not start") from None

    def read(name: str) -> None:
        nonlocal count, limited
        stream = process.stdout if name == "stdout" else process.stderr
        assert stream is not None
        while block := cast(BufferedReader, stream).read1(65_536):
            with lock:
                remaining = max(0, maximum - count)
                buffers[name].extend(block[:remaining])
                count += len(block)
                if count > maximum:
                    limited = True
                    overflow.set()
        stream.close()

    threads = [threading.Thread(target=read, args=(name,), daemon=True) for name in buffers]
    for thread in threads:
        thread.start()
    try:
        deadline = time.monotonic() + timeout
        while process.poll() is None:
            remaining = deadline - time.monotonic()
            if overflow.is_set() or remaining <= 0:
                timed_out = remaining <= 0 and not overflow.is_set()
                break
            overflow.wait(min(0.05, remaining))
    finally:
        # Also close descendants that outlive a successful parent in its process group.
        _kill(process)
        process.wait(timeout=5)
        for thread in threads:
            thread.join(timeout=5)
    return {
        "exit_code": process.returncode,
        "timed_out": timed_out,
        "output_limited": limited,
        "stdout": buffers["stdout"].decode("utf-8", errors="replace"),
        "stderr": buffers["stderr"].decode("utf-8", errors="replace"),
        "captured_bytes": sum(len(value) for value in buffers.values()),
    }


def _executable(name: str, workspace: Path) -> dict[str, Any]:
    found = shutil.which(name)
    if found is None:
        raise WorkbenchError("SANDBOX_UNAVAILABLE", "The configured executable is unavailable")
    try:
        path = Path(found).resolve(strict=True)
        before = path.stat()
        if (
            path.is_relative_to(workspace)
            or not stat.S_ISREG(before.st_mode)
            or before.st_mode & 0o022
            or os.name == "posix"
            and before.st_uid not in {0, os.geteuid()}
        ):
            raise WorkbenchError("POLICY_DENIED", "Execution requires a trusted host executable")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while block := stream.read(1_048_576):
                digest.update(block)
        after = path.stat()
        identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        if identity != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            raise WorkbenchError("CONFLICT", "Executable changed during review")
        return {"path": str(path), "sha256": digest.hexdigest(), "identity": list(identity)}
    except OSError:
        raise WorkbenchError(
            "SANDBOX_UNAVAILABLE", "The trusted executable is unavailable"
        ) from None


class Runner:
    def __init__(
        self,
        policy: WorkspacePolicy,
        store: StateStore,
        *,
        docker_executable: str = "docker",
        docker_endpoint: str | None = None,
    ) -> None:
        if store.policy.workspace_id != policy.workspace_id:
            raise WorkbenchError("POLICY_DENIED", "Runner state must belong to this workspace")
        self.policy = policy
        self.store = store
        self.docker_executable = docker_executable
        self.docker_endpoint = docker_endpoint

    def _endpoint(self) -> dict[str, Any]:
        endpoint = self.docker_endpoint or os.environ.get("DOCKER_HOST")
        if endpoint is None:
            candidates = [Path("/var/run/docker.sock"), Path.home() / ".docker/run/docker.sock"]
            endpoint = (
                "npipe:////./pipe/docker_engine"
                if os.name == "nt"
                else "unix://"
                + str(next((path for path in candidates if path.exists()), candidates[0]))
            )
        if endpoint.startswith("unix://"):
            try:
                original = Path(endpoint[7:])
                if not original.is_absolute() or any(char in endpoint for char in "\x00\r\n?#"):
                    raise WorkbenchError(
                        "POLICY_DENIED", "Docker requires an absolute local socket"
                    )
                path = original.resolve(strict=True)
                info = path.stat()
                if not stat.S_ISSOCK(info.st_mode) or info.st_uid not in {0, os.geteuid()}:
                    raise WorkbenchError("POLICY_DENIED", "Docker requires a trusted local socket")
                return {
                    "endpoint": "unix://" + str(path),
                    "identity": [info.st_dev, info.st_ino, info.st_uid],
                }
            except OSError:
                raise WorkbenchError(
                    "SANDBOX_UNAVAILABLE", "The local Docker socket is unavailable"
                ) from None
        if os.name == "nt" and re.fullmatch(r"npipe:////\./pipe/[A-Za-z0-9_.-]+", endpoint):
            return {"endpoint": endpoint, "identity": [endpoint]}
        raise WorkbenchError("POLICY_DENIED", "Remote Docker endpoints are not supported")

    def _docker_call(
        self, executable: dict[str, Any], endpoint: dict[str, Any], args: list[str]
    ) -> dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix="agentic-docker-client-") as temporary:
            directory = Path(temporary)
            return _capture(
                [
                    executable["path"],
                    "--config",
                    str(directory),
                    "--host",
                    endpoint["endpoint"],
                    *args,
                ],
                directory,
                10,
                65_536,
            )

    def _docker_identity(
        self, executable: dict[str, Any], endpoint: dict[str, Any], command: CommandConfig
    ) -> dict[str, Any]:
        daemon = self._docker_call(executable, endpoint, ["info", "--format", "{{json .ID}}"])
        if daemon["exit_code"] != 0 or daemon["timed_out"] or daemon["output_limited"]:
            raise WorkbenchError("SANDBOX_UNAVAILABLE", "The local Docker daemon is unavailable")
        daemon_id = strict_json(daemon["stdout"], 65_536)
        if not isinstance(daemon_id, str) or not daemon_id:
            raise WorkbenchError("SANDBOX_UNAVAILABLE", "Docker did not report a daemon identity")
        if command.image is None:
            raise WorkbenchError(
                "SANDBOX_UNAVAILABLE", "Docker execution requires a configured digest-pinned image"
            )
        image = self._docker_call(executable, endpoint, ["image", "inspect", command.image])
        if image["exit_code"] != 0 or image["timed_out"] or image["output_limited"]:
            raise WorkbenchError(
                "SANDBOX_UNAVAILABLE", "The approved Docker image must already exist locally"
            )
        data = strict_json(image["stdout"], 65_536)
        if (
            not isinstance(data, list)
            or len(data) != 1
            or not isinstance(data[0], dict)
            or not isinstance(data[0].get("Config"), dict)
            or not isinstance(data[0].get("Id"), str)
            or not re.fullmatch(r"sha256:[a-f0-9]{64}", data[0]["Id"])
            or data[0]["Config"].get("Volumes")
        ):
            raise WorkbenchError(
                "POLICY_DENIED", "The Docker image must not declare extra filesystem volumes"
            )
        if endpoint != self._endpoint():
            raise WorkbenchError("CONFLICT", "Docker socket identity changed during review")
        return {**endpoint, "daemon_id": daemon_id, "image_id": data[0]["Id"]}

    def _prepare(self, command_id: str, backend: str) -> tuple[dict[str, Any], list[SourceFile]]:
        if backend not in {"docker", "trusted-host"}:
            raise WorkbenchError("VALIDATION_ERROR", "Unknown execution backend")
        command = self.policy.config.commands.get(command_id)
        if command is None:
            raise WorkbenchError("CONFIG_ERROR", "Unknown configured test command")
        if Path(command.argv[0]).name.lower().removesuffix(".exe") in _SHELLS:
            raise WorkbenchError(
                "POLICY_DENIED", "Shell and environment-interpreter commands are prohibited"
            )
        if self.policy.redactor.contains_secret(" ".join(command.argv)):
            raise WorkbenchError("POLICY_DENIED", "Test arguments cannot contain credentials")
        index = scan_workspace(self.policy)
        if index.coverage["limit_reached"]:
            raise WorkbenchError(
                "LIMIT_EXCEEDED", "A complete bounded snapshot could not be prepared"
            )
        files = [source for _, source in sorted(index.files.items()) if not source.contains_secrets]
        omitted = [source.path for source in index.files.values() if source.contains_secrets]
        executable = _executable(
            self.docker_executable if backend == "docker" else command.argv[0], self.policy.root
        )
        review: dict[str, Any] = {
            "command_id": command_id,
            "argv": list(command.argv),
            "backend": backend,
            "workspace_id": self.policy.workspace_id,
            "config_fingerprint": self.policy.config.fingerprint,
            "source_fingerprint": index.fingerprint,
            "snapshot_hash": canonical_hash({source.path: source.source_hash for source in files}),
            "snapshot_files": [source.path for source in files],
            "omitted_secret_files": sorted(omitted),
            "coverage": index.coverage,
            "trusted_executable": executable,
            "timeout": command.timeout,
            "max_output_bytes": command.max_output_bytes,
            "command_fingerprint": canonical_hash(
                {
                    "argv": command.argv,
                    "image": command.image,
                    "timeout": command.timeout,
                    "output": command.max_output_bytes,
                }
            ),
        }
        if backend == "docker":
            review["docker"] = self._docker_identity(executable, self._endpoint(), command)
            review["image"] = command.image
            review["isolation_flags"] = _DOCKER_FLAGS
        else:
            review["limitations"] = ["Trusted-host mode is a temporary copy, not an OS sandbox."]
        return {**review, "digest": canonical_hash(review)}, files

    def review(self, command_id: str, backend: str = "docker") -> dict[str, Any]:
        return self.policy.redactor.clean(self._prepare(command_id, backend)[0])  # type: ignore[no-any-return]

    def _cleanup(self, record_id: str, record: dict[str, Any]) -> dict[str, Any]:
        try:
            executable = _executable(self.docker_executable, self.policy.root)
            endpoint = self._endpoint()
            if executable != record["trusted_executable"] or endpoint != record["endpoint"]:
                raise WorkbenchError("CONFLICT", "Cleanup endpoint or executable identity changed")
            daemon = self._docker_call(executable, endpoint, ["info", "--format", "{{json .ID}}"])
            if (
                daemon["exit_code"] != 0
                or daemon["timed_out"]
                or daemon["output_limited"]
                or strict_json(daemon["stdout"], 65_536) != record["daemon_id"]
            ):
                raise WorkbenchError(
                    "SANDBOX_UNAVAILABLE", "The recorded Docker daemon is unavailable"
                )
            info = self._docker_call(executable, endpoint, ["container", "inspect", record["name"]])
            if info["timed_out"] or info["output_limited"]:
                raise WorkbenchError("EXECUTION_ERROR", "Owned container cleanup inspection failed")
            if info["exit_code"] != 0:
                if "No such" not in info["stderr"]:
                    raise WorkbenchError(
                        "EXECUTION_ERROR", "Owned container inspection could not establish absence"
                    )
            else:
                data = strict_json(info["stdout"], 65_536)
                container = data[0] if isinstance(data, list) and len(data) == 1 else None
                config = container.get("Config") if isinstance(container, dict) else None
                labels = config.get("Labels") if isinstance(config, dict) else None
                if (
                    not isinstance(container, dict)
                    or not isinstance(labels, dict)
                    or labels.get(_OWNER_LABEL) != record["owner"]
                    or container.get("Name") != "/" + record["name"]
                    or not isinstance(container.get("Id"), str)
                    or not re.fullmatch(r"[a-f0-9]{64}", container["Id"])
                ):
                    raise WorkbenchError(
                        "POLICY_DENIED", "Container ownership could not be verified"
                    )
                record["container_id"] = container["Id"]
                removed = self._docker_call(
                    executable, endpoint, ["container", "rm", "--force", container["Id"]]
                )
                if removed["exit_code"] != 0 or removed["timed_out"] or removed["output_limited"]:
                    raise WorkbenchError("EXECUTION_ERROR", "Owned container cleanup failed")
            record["state"] = "cleaned"
        except WorkbenchError as error:
            record["state"] = "cleanup_required"
            record["cleanup_error"] = error.code
        self.store.update("container", record_id, record)
        return record

    def cleanup_pending(self) -> list[dict[str, Any]]:
        with writer_lock(self.policy):
            return [
                self._cleanup(row["id"], row["value"])
                for row in self.store.list_records("container")
                if row["value"].get("state") != "cleaned"
            ]

    def execute(
        self, command_id: str, approval: str | None, backend: str = "docker"
    ) -> dict[str, Any]:
        if not approval:
            raise WorkbenchError(
                "APPROVAL_REQUIRED", "Test execution requires the exact review digest"
            )
        if (
            not self.policy.grants.execute
            or backend == "trusted-host"
            and not self.policy.grants.trusted_host
        ):
            raise WorkbenchError(
                "POLICY_DENIED", "Test execution requires explicit host and backend grants"
            )
        with writer_lock(self.policy):
            review, files = self._prepare(command_id, backend)
            if approval != review["digest"]:
                raise WorkbenchError(
                    "STALE_APPROVAL",
                    "The command, snapshot, configuration or backend review changed",
                )
            with tempfile.TemporaryDirectory(prefix="agentic-runner-") as temporary:
                directory = Path(temporary)
                if any(char in str(directory) for char in ",\r\n\x00"):
                    raise WorkbenchError("POLICY_DENIED", "Unsafe temporary snapshot mount path")
                snapshot = directory / "snapshot"
                snapshot.mkdir()
                for source in files:
                    path = snapshot.joinpath(*self.policy.parts(source.path))
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(source.text, encoding="utf-8", newline="")
                    path.chmod(0o444)
                for path in sorted(snapshot.rglob("*"), reverse=True):
                    if path.is_dir():
                        path.chmod(0o555)
                snapshot.chmod(0o555)
                record_id: str | None = None
                record: dict[str, Any] = {}
                if backend == "docker":
                    record_id = uuid4().hex
                    record = {
                        "name": "agentic-" + record_id,
                        "owner": record_id,
                        "state": "prepared",
                        "endpoint": self._endpoint(),
                        "daemon_id": review["docker"]["daemon_id"],
                        "trusted_executable": review["trusted_executable"],
                        "snapshot_hash": review["snapshot_hash"],
                        "digest": approval,
                    }
                    self.store.save("container", record_id, record)
                    client = directory / "docker-config"
                    client.mkdir(mode=0o700)
                    argv = [
                        review["trusted_executable"]["path"],
                        "--config",
                        str(client),
                        "--host",
                        review["docker"]["endpoint"],
                        "run",
                        "--name",
                        record["name"],
                        "--label",
                        _OWNER_LABEL + "=" + record["owner"],
                        *_DOCKER_FLAGS,
                        "--mount",
                        "type=bind,src=" + str(snapshot) + ",dst=/workspace,readonly",
                        "--entrypoint",
                        review["argv"][0],
                        review["image"],
                        *review["argv"][1:],
                    ]
                else:
                    argv = [review["trusted_executable"]["path"], *review["argv"][1:]]
                try:
                    outcome = _capture(
                        argv, snapshot, review["timeout"], review["max_output_bytes"]
                    )
                    if record_id is not None:
                        record.update(
                            state="finished",
                            exit_code=outcome["exit_code"],
                            timed_out=outcome["timed_out"],
                            output_limited=outcome["output_limited"],
                        )
                        self.store.update("container", record_id, record)
                except BaseException:
                    if record_id is not None:
                        record.update(state="interrupted", interrupted=True)
                        self.store.update("container", record_id, record)
                    raise
                finally:
                    if record_id is not None:
                        record = self._cleanup(record_id, record)
                result = {
                    "command_id": command_id,
                    "command": review["argv"],
                    "argv": argv,
                    "command_fingerprint": review["command_fingerprint"],
                    "snapshot_hash": review["snapshot_hash"],
                    "backend": backend,
                    "digest": approval,
                    **outcome,
                }
                if record_id is not None:
                    result["cleanup"] = {
                        "record_id": record_id,
                        "state": record["state"],
                        "container_id": record.get("container_id"),
                    }
                    if record["state"] != "cleaned":
                        raise WorkbenchError(
                            "EXECUTION_ERROR", "Owned container cleanup requires recovery"
                        )
                return self.policy.redactor.clean(result)  # type: ignore[no-any-return]
