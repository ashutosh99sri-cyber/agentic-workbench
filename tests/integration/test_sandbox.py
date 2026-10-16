"""Actual Docker confinement checks; run with an explicitly supplied local image."""

import _thread
import json
import os
import re
import threading

import pytest

from agentic_workbench.config import CommandConfig, Config
from agentic_workbench.models import Grant
from agentic_workbench.policy import WorkspacePolicy
from agentic_workbench.runner import Runner
from agentic_workbench.state import StateStore
from agentic_workbench.tool_registry import ToolRegistry

pytestmark = pytest.mark.docker


@pytest.fixture
def make_runner(tmp_path, request):
    image = os.environ.get("AGENTIC_DOCKER_IMAGE")
    assert image and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/:+-]*@sha256:[a-f0-9]{64}", image), (
        "Set AGENTIC_DOCKER_IMAGE to an explicitly approved, already-local digest image; "
        "Docker acceptance requirements are not silently skipped."
    )

    def make(script, *, timeout=10, maximum=4096):
        (tmp_path / "test.js").write_text(script)
        config = Config(
            commands={
                "unit": CommandConfig(
                    ("node", "test.js"), image=image, timeout=timeout, max_output_bytes=maximum
                )
            }
        )
        policy = WorkspacePolicy(tmp_path, config, grants=Grant(execute=True))
        store = StateStore(policy)
        request.addfinalizer(store.close)
        return Runner(policy, store, docker_endpoint=os.environ.get("AGENTIC_DOCKER_ENDPOINT"))

    return make


def assert_cleaned(runner, result):
    assert result["cleanup"]["state"] == "cleaned"
    record = runner.store.load("container", result["cleanup"]["record_id"])
    assert record["state"] == "cleaned"
    assert re.fullmatch(r"[a-f0-9]{64}", record["container_id"])
    inspected = runner._docker_call(
        record["trusted_executable"],
        record["endpoint"],
        ["container", "inspect", record["container_id"]],
    )
    assert inspected["exit_code"] != 0 and "No such" in inspected["stderr"]


def test_actual_container_is_nonroot_readonly_and_cannot_access_host_or_credentials(
    tmp_path, monkeypatch, make_runner
):
    secret = "runner-docker-fixture-credential-123456789"
    monkeypatch.setenv("RUNNER_HOST_SECRET", secret)
    (tmp_path / "secret.txt").write_text(secret)
    (tmp_path / ".env").write_text("PRIVATE=unavailable")
    host_path = json.dumps(str(tmp_path))
    script = """
const fs=require('node:fs');
const denied=(path)=>{try{fs.writeFileSync(path,'mutated');return false;}catch{return true;}};
const status=fs.readFileSync('/proc/self/status','utf8');
console.log(JSON.stringify({uid:process.getuid(),snapshotWriteDenied:denied('/workspace/test.js'),
rootWriteDenied:denied('/root-write-check'),secretFile:fs.existsSync('/workspace/secret.txt'),
envFile:fs.existsSync('/workspace/.env'),state:fs.existsSync('/workspace/.agentic'),
dockerSocket:fs.existsSync('/var/run/docker.sock'),credential:process.env.RUNNER_HOST_SECRET??null,
capabilities:/CapEff:\\s+0+\\b/.test(status),noNewPrivileges:/NoNewPrivs:\\s+1\\b/.test(status),
hostPath:fs.existsSync(HOST_PATH)}));
""".replace("HOST_PATH", host_path)
    runner = make_runner(script)
    review = runner.review("unit")
    assert review["omitted_secret_files"] == ["secret.txt"]
    result = runner.execute("unit", review["digest"])
    assert result["exit_code"] == 0, result["stderr"]
    output = json.loads(result["stdout"])
    assert output == {
        "uid": 65534,
        "snapshotWriteDenied": True,
        "rootWriteDenied": True,
        "secretFile": False,
        "envFile": False,
        "state": False,
        "dockerSocket": False,
        "credential": None,
        "capabilities": True,
        "noNewPrivileges": True,
        "hostPath": False,
    }
    assert (tmp_path / "test.js").read_text() == script
    assert_cleaned(runner, result)


def test_actual_interruption_persists_cleanup_receipt(make_runner, monkeypatch):
    from agentic_workbench import runner as module

    runner = make_runner("setInterval(()=>{},1000);", timeout=30)
    review = runner.review("unit")
    original = module._capture

    def interrupted_capture(argv, cwd, timeout, maximum):
        if "run" not in argv:
            return original(argv, cwd, timeout, maximum)
        timer = threading.Timer(1, _thread.interrupt_main)
        timer.start()
        try:
            return original(argv, cwd, timeout, maximum)
        finally:
            timer.cancel()

    monkeypatch.setattr(module, "_capture", interrupted_capture)
    with pytest.raises(KeyboardInterrupt):
        runner.execute("unit", review["digest"])
    receipts = runner.store.list_records("container")
    assert len(receipts) == 1
    assert receipts[0]["value"]["interrupted"]
    assert_cleaned(runner, {"cleanup": {"record_id": receipts[0]["id"], "state": "cleaned"}})


def test_actual_container_network_is_disabled(make_runner):
    runner = make_runner("""
const net=require('node:net');const os=require('node:os');
const socket=net.createConnection({host:'203.0.113.1',port:80});
socket.on('error',error=>console.log(JSON.stringify({error:error.code,interfaces:Object.keys(os.networkInterfaces())})));
socket.on('connect',()=>{console.log(JSON.stringify({connected:true}));socket.destroy();});
socket.setTimeout(2000,()=>{console.log(JSON.stringify({timeout:true}));socket.destroy();});
""")
    result = runner.execute("unit", runner.review("unit")["digest"])
    assert result["exit_code"] == 0, result["stderr"]
    output = json.loads(result["stdout"])
    assert output["interfaces"] == ["lo"]
    assert output["error"] in {"ENETUNREACH", "EHOSTUNREACH"}
    assert_cleaned(runner, result)


def test_registry_command_uses_real_docker_isolation_and_receipt(make_runner):
    runner = make_runner("console.log(JSON.stringify({uid:process.getuid()}));")
    registry = ToolRegistry(runner.policy, runner.store)
    registry.register_command("sandboxed_probe", "unit")
    digest = registry.review("sandboxed_probe", {})["digest"]
    result = registry.invoke("sandboxed_probe", {}, approval=digest, idempotency_key="docker-probe")
    assert result.data is not None and result.data["backend"] == "docker"
    assert json.loads(result.data["stdout"]) == {"uid": 65534}
    assert_cleaned(runner, result.data)
    assert registry.invoke(
        "sandboxed_probe", {}, approval=digest, idempotency_key="docker-probe"
    ).cached


@pytest.mark.parametrize(
    "script,timeout,maximum,flag",
    [
        ("setInterval(()=>{},1000);", 1, 4096, "timed_out"),
        (
            "process.stdout.write('x'.repeat(100000));setInterval(()=>{},1000);",
            10,
            256,
            "output_limited",
        ),
        (
            "process.stderr.write('x'.repeat(100000));setInterval(()=>{},1000);",
            10,
            256,
            "output_limited",
        ),
    ],
    ids=["timeout", "stdout-overflow", "stderr-overflow"],
)
def test_actual_timeout_and_output_overflow_cleanup_exact_owned_container(
    make_runner, script, timeout, maximum, flag
):
    runner = make_runner(script, timeout=timeout, maximum=maximum)
    result = runner.execute("unit", runner.review("unit")["digest"])
    assert result[flag]
    assert result["captured_bytes"] <= maximum
    assert_cleaned(runner, result)
