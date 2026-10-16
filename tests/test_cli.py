import getpass
import json
import os
import warnings
from pathlib import Path

import pytest

from agentic_workbench import cli
from agentic_workbench.cli import main
from agentic_workbench.errors import WorkbenchError


def _key_command(root: Path) -> list[str]:
    return [
        "explain",
        "app.py",
        "--root",
        str(root),
        "--provider",
        "openai",
        "--model",
        "gpt-6-luna",
        "--allow-network",
        "--prompt-key",
    ]


@pytest.mark.parametrize("original", [None, "existing-credential-value"])
@pytest.mark.parametrize("outcome", ["success", "error", "interrupt", "io"])
def test_prompt_key_is_temporary_and_redacted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    original: str | None,
    outcome: str,
) -> None:
    name, key = "LOCAL_AUTH", "test-local-credential-with-unrecognized-format"
    config = tmp_path / ".agentic"
    config.mkdir(mode=0o700)
    (config / "config.toml").write_text(f'[provider]\ncredential_env = "{name}"\n')
    if original is None:
        monkeypatch.delenv(name, raising=False)
    else:
        monkeypatch.setenv(name, original)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr(getpass, "getpass", lambda prompt: key)

    def dispatch(args: object) -> dict[str, object]:
        assert os.environ[name] == key
        with cli.Workbench(tmp_path) as workbench:
            assert workbench.policy.redactor.redact(key) == "[REDACTED]"
        if outcome == "error":
            raise WorkbenchError("CONFIG_ERROR", f"Unexpected credential: {key}")
        if outcome == "interrupt":
            raise KeyboardInterrupt
        if outcome == "io":
            raise OSError(key)
        return {"summary": key}

    monkeypatch.setattr(cli, "_dispatch", dispatch)
    assert (
        main(_key_command(tmp_path)) == {"success": 0, "error": 2, "interrupt": 1, "io": 1}[outcome]
    )
    captured = capsys.readouterr()
    envelope = json.loads(captured.out)
    assert envelope["ok"] is (outcome == "success")
    assert key not in captured.out + captured.err
    assert os.environ.get(name) == original
    assert all(key.encode() not in path.read_bytes() for path in config.iterdir() if path.is_file())


@pytest.mark.parametrize(
    "condition", ["pipe", "network", "provider", "model", "lexical", "sdk", "transport", "policy"]
)
def test_prompt_key_requires_interactive_network_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    condition: str,
) -> None:
    args = _key_command(tmp_path)
    monkeypatch.setattr("sys.stdin.isatty", lambda: condition != "pipe")
    if condition == "network":
        args.remove("--allow-network")
    elif condition == "provider":
        args[args.index("openai")] = "none"
    elif condition == "model":
        del args[args.index("--model") : args.index("--model") + 2]
    elif condition == "lexical":
        args[:2] = ["search", "value"]
    elif condition == "sdk":
        monkeypatch.setattr(cli.importlib.util, "find_spec", lambda name: None)
    elif condition == "transport":
        find_spec = cli.importlib.util.find_spec
        monkeypatch.setattr(
            cli.importlib.util,
            "find_spec",
            lambda name: None if name == "httpx2" else find_spec(name),
        )
    elif condition == "policy":
        config = tmp_path / ".agentic"
        config.mkdir(mode=0o700)
        (config / "config.toml").write_text("[policy]\nnetwork_domains = []\n")

    def no_prompt(prompt: str) -> str:
        pytest.fail("Invalid command must fail before collecting a credential")

    monkeypatch.setattr(getpass, "getpass", no_prompt)
    assert main(args) != 0
    assert json.loads(capsys.readouterr().out)["ok"] is False


@pytest.mark.parametrize("problem", ["empty", "newline", "eof", "echo"])
def test_prompt_key_fails_closed_without_hidden_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    problem: str,
) -> None:
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def prompt(message: str) -> str:
        if problem == "eof":
            raise EOFError
        if problem == "echo":
            warnings.warn("Cannot control echo", getpass.GetPassWarning, stacklevel=1)
        return "" if problem == "empty" else "invalid\ncredential"

    monkeypatch.setattr(getpass, "getpass", prompt)
    assert main(_key_command(tmp_path)) != 0
    assert json.loads(capsys.readouterr().out)["ok"] is False
    assert "OPENAI_API_KEY" not in os.environ


@pytest.mark.parametrize("mode", ["semantic", "combined"])
def test_prompt_key_semantic_search_uses_embedding_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], mode: str
) -> None:
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr(getpass, "getpass", lambda prompt: "local-embedding-credential")
    monkeypatch.setattr(cli, "_dispatch", lambda args: {"mode": "semantic"})
    args = _key_command(tmp_path)
    args[:2] = ["search", "value", f"--{mode}"]
    args[args.index("--model")] = "--embedding-model"
    args[args.index("gpt-6-luna")] = "text-embedding-model"
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out)["data"]["mode"] == "semantic"


@pytest.mark.parametrize(
    "command",
    [
        ("init",),
        ("scan",),
        ("explain", "app.py"),
        ("plan", "Improve value"),
        ("run", "architecture", "Review value"),
        ("search", "value"),
        ("state", "export"),
    ],
)
def test_cli_single_envelope(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], command: tuple[str, ...]
) -> None:
    (tmp_path / "app.py").write_text("value = 1\n")
    assert main([*command, "--root", str(tmp_path), "--json"]) == 0
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["schema_version"] == 1 and envelope["ok"] is True


def test_cli_bad_input_and_protected_configuration(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["missing"]) == 2
    assert json.loads(capsys.readouterr().out)["ok"] is False
    directory = tmp_path / ".agentic"
    directory.mkdir(mode=0o700)
    outside = tmp_path / "outside.toml"
    outside.write_text('[provider]\nname="none"')
    (directory / "config.toml").symlink_to(outside)
    assert main(["init", "--root", str(tmp_path)]) in {1, 3}
    assert json.loads(capsys.readouterr().out)["ok"] is False


def test_invalid_model_override_closes_the_opened_store(tmp_path, monkeypatch, capsys):
    from agentic_workbench import cli

    created = []
    original = cli.Workbench

    def track(*args, **kwargs):
        created.append(original(*args, **kwargs))
        return created[-1]

    monkeypatch.setattr(cli, "Workbench", track)
    code = main(["explain", "app.py", "--root", str(tmp_path), "--model", "bad model"])
    assert code == 2 and json.loads(capsys.readouterr().out)["error"]["code"] == "CONFIG_ERROR"
    assert len(created) == 1 and created[0].store._closed


def test_index_impact_and_context_cli(tmp_path, capsys):
    (tmp_path / "app.py").write_text("def total(x):\n    return x * 2\n")
    assert main(["impact", "app.py", "--root", str(tmp_path)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] and result["data"]["changed_paths"] == ["app.py"]
    assert (
        main(["context", "change total", "--changed-path", "app.py", "--root", str(tmp_path)]) == 0
    )
    assert json.loads(capsys.readouterr().out)["ok"]


def test_structural_cli_requires_explicit_host_paths(tmp_path, capsys):
    assert main(["scan", "--root", str(tmp_path), "--typescript-package", str(tmp_path)]) == 2
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "VALIDATION_ERROR"
    assert main(["search", "x", "--semantic", "--combined", "--root", str(tmp_path)]) == 2
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("command", ["execute", "repair"])
def test_prompt_key_preserves_current_execution_command_arguments(
    tmp_path, monkeypatch, capsys, command
):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr(getpass, "getpass", lambda prompt: "local-execution-credential")
    args = _key_command(tmp_path)
    args[:2] = [command, "Review synthetic change"]
    if command == "repair":
        args.extend(["--command-id", "unit", "--edit-path", "app.py"])

    def dispatch(parsed):
        assert parsed.command == command
        assert parsed.approve is None and parsed.approve_test is None
        return {"mode": command, "approval_required": True}

    monkeypatch.setattr(cli, "_dispatch", dispatch)
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out)["data"]["approval_required"] is True
