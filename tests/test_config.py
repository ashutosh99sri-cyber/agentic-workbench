from pathlib import Path

import pytest

from agentic_workbench.config import CommandConfig, Config
from agentic_workbench.errors import WorkbenchError


def test_config_defaults_are_offline_and_bounded():
    config = Config.from_dict({"schema_version": 1})
    assert config.provider.name == "none"
    assert config.scan.max_files == 10_000
    assert config.limits.provider_requests == 8
    assert config.fingerprint == Config.from_dict({"schema_version": 1}).fingerprint


@pytest.mark.parametrize(
    "payload",
    [
        {"schema_version": 2},
        {"schema_version": 1, "provider": {"api_key": "never-store-this"}},
        {"schema_version": 1, "provider": {"allow_network": True}},
        {"schema_version": 1, "limits": {"provider_requests": True}},
        {"schema_version": 1, "scan": {"max_files": -1}},
        {"schema_version": 1, "commands": {"bad": {"argv": ["sh", "-c", "echo bad"]}}},
    ],
)
def test_invalid_or_privilege_expanding_config_is_rejected(payload):
    with pytest.raises(WorkbenchError) as error:
        Config.from_dict(payload)
    assert error.value.code == "CONFIG_ERROR"
    assert "never-store-this" not in str(error.value)


def test_toml_roundtrip_and_unknown_fields(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[provider]\nname="openai"\nmodel="approved-model"\n')
    config = Config.load(path)
    assert config.provider.model == "approved-model"
    assert config.provider.credential_env == "OPENAI_API_KEY"
    path.write_text("schema_version=1\nextra=true\n")
    with pytest.raises(WorkbenchError):
        Config.load(path)


def test_command_accepts_absolute_executable_path_with_spaces(tmp_path: Path) -> None:
    executable = tmp_path / "My Project" / "python"
    executable.parent.mkdir()
    executable.touch()
    argv = (str(executable), "-B", "-m", "unittest", "-q")
    assert CommandConfig(argv).argv == argv


@pytest.mark.parametrize("executable", ["python -B", "My Project/bin/python", "-python"])
def test_command_still_rejects_relative_whitespace_and_leading_dash(executable: str) -> None:
    with pytest.raises(WorkbenchError, match="Invalid command executable"):
        CommandConfig((executable,))


@pytest.mark.parametrize("shell", ["sh", "bash", "zsh", "cmd.exe", "powershell.exe"])
def test_command_still_rejects_shells_in_absolute_paths_with_spaces(
    tmp_path: Path, shell: str
) -> None:
    with pytest.raises(WorkbenchError, match="Shell interpreter commands are prohibited"):
        CommandConfig((str(tmp_path / "My Project" / shell),))


@pytest.mark.parametrize("control", ["\x00", "\r", "\n"])
def test_command_still_rejects_control_characters_in_absolute_paths(
    tmp_path: Path, control: str
) -> None:
    with pytest.raises(WorkbenchError, match="Invalid text field: command argument"):
        CommandConfig((str(tmp_path / "My Project" / f"python{control}"),))
