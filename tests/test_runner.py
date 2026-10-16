import json
import os
import socket
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

import pytest

from agentic_workbench.config import CommandConfig, Config
from agentic_workbench.errors import WorkbenchError
from agentic_workbench.models import Grant
from agentic_workbench.policy import WorkspacePolicy
from agentic_workbench.runner import Runner
from agentic_workbench.state import StateStore

IMAGE = "node@sha256:" + "a" * 64


def host_runner(tmp_path, code, *, request, grants=None, timeout=3, maximum=4096):
    config = Config(
        commands={
            "unit": CommandConfig(
                (sys.executable, "-c", code), timeout=timeout, max_output_bytes=maximum
            )
        }
    )
    policy = WorkspacePolicy(
        tmp_path, config, grants=grants or Grant(execute=True, trusted_host=True)
    )
    store = StateStore(policy)
    request.addfinalizer(store.close)
    return Runner(policy, store)


def test_host_review_is_read_only_and_permission_is_separate_from_approval(tmp_path, request):
    (tmp_path / "sample.py").write_text("print('sample')\n")
    runner = host_runner(tmp_path, "print('done')", request=request, grants=Grant())
    review = runner.review("unit", "trusted-host")
    assert review["snapshot_files"] == ["sample.py"]
    assert review["backend"] == "trusted-host"
    assert len(review["digest"]) == 64
    with pytest.raises(WorkbenchError, match="APPROVAL_REQUIRED"):
        runner.execute("unit", None, "trusted-host")
    with pytest.raises(WorkbenchError, match="POLICY_DENIED"):
        runner.execute("unit", review["digest"], "trusted-host")
    enabled = WorkspacePolicy(
        tmp_path, runner.policy.config, grants=Grant(execute=True, trusted_host=True)
    )
    outcome = Runner(enabled, runner.store).execute("unit", review["digest"], "trusted-host")
    assert outcome["exit_code"] == 0
    assert outcome["stdout"] == "done\n"
    assert outcome["argv"][0] == review["trusted_executable"]["path"]


def test_trusted_host_uses_sanitized_copy_and_environment(tmp_path, monkeypatch, request):
    monkeypatch.setenv("OPENAI_API_KEY", "runner-fixture-credential-123456789")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path / "malicious"))
    (tmp_path / "ordinary.txt").write_text("safe content")
    (tmp_path / "secret.txt").write_text(os.environ["OPENAI_API_KEY"])
    (tmp_path / ".env").write_text("PRIVATE=value")
    code = (
        "import json,os; print(json.dumps({'files':os.listdir('.'),'cwd':os.getcwd(),"
        "'key':os.getenv('OPENAI_API_KEY'),'path':os.getenv('PYTHONPATH')}))"
    )
    runner = host_runner(tmp_path, code, request=request)
    review = runner.review("unit", "trusted-host")
    assert review["omitted_secret_files"] == ["secret.txt"]
    result = runner.execute("unit", review["digest"], "trusted-host")
    output = json.loads(result["stdout"])
    assert output["files"] == ["ordinary.txt"]
    assert output["cwd"] != str(tmp_path)
    assert output["key"] is None and output["path"] is None
    assert (tmp_path / "ordinary.txt").read_text() == "safe content"


@pytest.mark.parametrize("change", ["source", "config", "executable"])
def test_snapshot_config_backend_and_executable_changes_invalidate_approval(
    tmp_path, monkeypatch, change, request
):
    (tmp_path / "file.txt").write_text("before")
    runner = host_runner(tmp_path, "print('ok')", request=request)
    review = runner.review("unit", "trusted-host")
    if change == "source":
        (tmp_path / "file.txt").write_text("after")
    elif change == "config":
        runner.policy.config.commands["unit"] = replace(
            runner.policy.config.commands["unit"], timeout=4
        )
    elif change == "executable":
        from agentic_workbench import runner as module

        original = module._executable
        monkeypatch.setattr(
            module, "_executable", lambda *args: {**original(*args), "sha256": "changed"}
        )
    with pytest.raises(WorkbenchError, match="STALE_APPROVAL"):
        runner.execute("unit", review["digest"], "trusted-host")


def test_timeout_output_bounds_and_real_failure_are_reported(tmp_path, request):
    runner = host_runner(tmp_path, "import time; time.sleep(20)", request=request, timeout=1)
    result = runner.execute("unit", runner.review("unit", "trusted-host")["digest"], "trusted-host")
    assert result["timed_out"] and result["exit_code"] < 0
    runner.policy.config.commands["unit"] = CommandConfig(
        (
            sys.executable,
            "-c",
            "import sys; sys.stdout.write('x'*10000); sys.stderr.write('y'*10000)",
        ),
        max_output_bytes=200,
    )
    result = runner.execute("unit", runner.review("unit", "trusted-host")["digest"], "trusted-host")
    assert result["output_limited"] and result["captured_bytes"] <= 200
    runner.policy.config.commands["unit"] = CommandConfig(
        (sys.executable, "-c", "raise SystemExit(7)")
    )
    result = runner.execute("unit", runner.review("unit", "trusted-host")["digest"], "trusted-host")
    assert result["exit_code"] == 7 and not result["timed_out"]


def test_command_credentials_shell_wrappers_and_missing_executable_are_rejected(
    tmp_path, monkeypatch, request
):
    monkeypatch.setenv("OPENAI_API_KEY", "do-not-put-this-in-argv")
    runner = host_runner(tmp_path, "print('do-not-put-this-in-argv')", request=request)
    with pytest.raises(WorkbenchError, match="POLICY_DENIED"):
        runner.review("unit", "trusted-host")
    runner.policy.config.commands["unit"] = CommandConfig(("env", "sh", "-c", "pwd"))
    with pytest.raises(WorkbenchError, match="POLICY_DENIED"):
        runner.review("unit", "trusted-host")
    runner.policy.config.commands["unit"] = CommandConfig(("agentic-absent-command-fixture",))
    with pytest.raises(WorkbenchError, match="SANDBOX_UNAVAILABLE"):
        runner.review("unit", "trusted-host")


def docker_runner(tmp_path, monkeypatch, request):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "file.js").write_text("console.log('ok')")
    sock = socket.socket(socket.AF_UNIX)
    socket_path = Path(tempfile.mkdtemp(prefix="agentic-sock-")) / "docker.sock"
    sock.bind(str(socket_path))
    config = Config(commands={"unit": CommandConfig(("node", "file.js"), image=IMAGE)})
    policy = WorkspacePolicy(root, config, grants=Grant(execute=True))
    store = StateStore(policy)
    request.addfinalizer(store.close)
    runner = Runner(
        policy,
        store,
        docker_executable=sys.executable,
        docker_endpoint="unix://" + str(socket_path),
    )
    calls = []
    records = {}

    def docker_call(executable, endpoint, args):
        calls.append(args)
        if args[0] == "info":
            output = json.dumps(records.get("daemon-id", "daemon-fixture"))
        elif args[0] == "image":
            output = json.dumps([{"Id": "sha256:" + "b" * 64, "Config": {}}])
        elif args[:2] == ["container", "inspect"]:
            name = args[2]
            output = json.dumps(
                [
                    {
                        "Id": "c" * 64,
                        "Name": "/" + name,
                        "Config": {"Labels": {"io.agentic-workbench.owner": records[name]}},
                    }
                ]
            )
        else:
            output = "removed"
        return {
            "exit_code": 0,
            "stdout": output,
            "stderr": "",
            "timed_out": False,
            "output_limited": False,
        }

    monkeypatch.setattr(runner, "_docker_call", docker_call)
    return runner, sock, calls, records


def close_socket(sock):
    path = Path(sock.getsockname())
    sock.close()
    path.unlink()
    try:
        path.parent.rmdir()
    except OSError:
        pass


def test_docker_argv_snapshot_and_cleanup_are_owned_and_durable(tmp_path, monkeypatch, request):
    runner, sock, calls, records = docker_runner(tmp_path, monkeypatch, request)
    review = runner.review("unit")
    from agentic_workbench import runner as module

    def capture(argv, cwd, timeout, maximum):
        name = argv[argv.index("--name") + 1]
        owner = argv[argv.index("--label") + 1].split("=", 1)[1]
        records[name] = owner
        assert str(runner.policy.root) not in " ".join(argv)
        assert (cwd / "file.js").read_text() == "console.log('ok')"
        assert not (cwd / ".agentic").exists()
        assert ",dst=/workspace,readonly" in argv[argv.index("--mount") + 1]
        assert "--pull=never" in argv and "--network=none" in argv
        assert "--read-only" in argv and "--cap-drop=ALL" in argv
        assert "--user=65534:65534" in argv and "--security-opt=no-new-privileges" in argv
        assert list(Path(argv[argv.index("--config") + 1]).iterdir()) == []
        return {
            "exit_code": 0,
            "stdout": "ok\n",
            "stderr": "",
            "timed_out": False,
            "output_limited": False,
            "captured_bytes": 3,
        }

    monkeypatch.setattr(module, "_capture", capture)
    try:
        result = runner.execute("unit", review["digest"])
        assert result["cleanup"]["state"] == "cleaned"
        record = runner.store.load("container", result["cleanup"]["record_id"])
        assert record["state"] == "cleaned" and record["container_id"] == "c" * 64
        assert ["container", "rm", "--force", "c" * 64] in calls
    finally:
        close_socket(sock)


def test_remote_endpoint_missing_image_and_changed_socket_never_fall_back(
    tmp_path, monkeypatch, request
):
    runner, sock, calls, records = docker_runner(tmp_path, monkeypatch, request)
    try:
        runner.docker_endpoint = "tcp://example.invalid:2375"
        with pytest.raises(WorkbenchError, match="POLICY_DENIED"):
            runner.review("unit")
        runner.docker_endpoint = "unix://" + sock.getsockname()
        runner.policy.config.commands["unit"] = replace(
            runner.policy.config.commands["unit"], image=None
        )
        with pytest.raises(WorkbenchError, match="SANDBOX_UNAVAILABLE"):
            runner.review("unit")
        runner.policy.config.commands["unit"] = replace(
            runner.policy.config.commands["unit"], image=IMAGE
        )
        review = runner.review("unit")
        other = socket.socket(socket.AF_UNIX)
        other.bind(str(Path(sock.getsockname()).with_name("other.sock")))
        runner.docker_endpoint = "unix://" + other.getsockname()
        try:
            with pytest.raises(WorkbenchError, match="STALE_APPROVAL"):
                runner.execute("unit", review["digest"])
        finally:
            close_socket(other)
        assert not any(args[:2] == ["container", "rm"] for args in calls)
    finally:
        close_socket(sock)


def test_cleanup_refuses_an_unowned_container(tmp_path, monkeypatch, request):
    runner, sock, calls, records = docker_runner(tmp_path, monkeypatch, request)
    try:
        review = runner.review("unit")
        records["agentic-recovery"] = "someone-else"
        receipt = {
            "name": "agentic-recovery",
            "owner": "expected-owner",
            "state": "prepared",
            "endpoint": runner._endpoint(),
            "daemon_id": "daemon-fixture",
            "trusted_executable": review["trusted_executable"],
        }
        runner.store.save("container", "recovery", receipt)
        result = runner.cleanup_pending()
        assert result[0]["state"] == "cleanup_required"
        assert not any(args[:2] == ["container", "rm"] for args in calls)
    finally:
        close_socket(sock)


def test_backend_and_daemon_identity_changes_invalidate_docker_approval(
    tmp_path, monkeypatch, request
):
    runner, sock, calls, records = docker_runner(tmp_path, monkeypatch, request)
    try:
        review = runner.review("unit")
        runner.policy.grants = Grant(execute=True, trusted_host=True)
        with pytest.raises(WorkbenchError, match="STALE_APPROVAL"):
            runner.execute("unit", review["digest"], "trusted-host")
        records["daemon-id"] = "replacement-daemon"
        with pytest.raises(WorkbenchError, match="STALE_APPROVAL"):
            runner.execute("unit", review["digest"])
        assert not any(args[:2] == ["container", "rm"] for args in calls)
    finally:
        close_socket(sock)
