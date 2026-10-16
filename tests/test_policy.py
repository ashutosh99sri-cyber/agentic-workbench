import os
from pathlib import Path

import pytest

from agentic_workbench.config import Config
from agentic_workbench.errors import WorkbenchError
from agentic_workbench.models import Grant, text_hash
from agentic_workbench.policy import WorkspacePolicy
from agentic_workbench.secrets import SecretRedactor


def test_dedicated_install_environment_is_protected(tmp_path: Path) -> None:
    directory = tmp_path / ".venv-agentic"
    directory.mkdir()
    (directory / "package.py").write_text("third_party=1\n")
    policy = WorkspacePolicy(tmp_path)
    assert policy.is_excluded(".venv-agentic")
    with pytest.raises(WorkbenchError):
        policy.read_source(".venv-agentic/package.py")


def test_regular_source_read_is_bounded_and_hashed(tmp_path):
    (tmp_path / "app.py").write_text("def total():\n    return 3\n")
    policy = WorkspacePolicy(tmp_path)
    source = policy.read_source("app.py")
    assert source.text.endswith("return 3\n")
    assert source.source_hash == text_hash(source.text)
    assert source.path == "app.py"
    assert policy.workspace_id == WorkspacePolicy(tmp_path).workspace_id


@pytest.mark.parametrize(
    ("path", "content", "value"),
    [
        ("settings.yml", "password: plainword\n", "plainword"),
        ("settings.toml", "api_key = local-development-key\n", "local-development-key"),
        ("app.py", "token = abc123\n", "abc123"),
        ("settings.txt", "PASSWORD=anotherword\n", "anotherword"),
        ("settings.txt", "API_KEY=YWJjZA==\n", "YWJjZA=="),
        ("settings.yml", "password: p@$$w0rd\n", "p@$$w0rd"),
    ],
)
def test_source_read_never_returns_named_unquoted_credentials(tmp_path, path, content, value):
    (tmp_path / path).write_text(content)
    source = WorkspacePolicy(tmp_path, redactor=SecretRedactor()).read_source(path)
    assert value not in source.text
    assert source.contains_secrets
    assert source.source_hash == text_hash(content)
    assert source.text.count("\n") == content.count("\n")


@pytest.mark.parametrize(
    "path", ["../outside", "/etc/passwd", "a/../b", "C:\\x", "a:b", "a//b", "", "x\x00"]
)
def test_unsafe_paths_fail_before_access(tmp_path, path):
    with pytest.raises(WorkbenchError) as error:
        WorkspacePolicy(tmp_path).read_source(path)
    assert error.value.code == "POLICY_DENIED"


@pytest.mark.parametrize(
    "path",
    [
        ".git/config",
        ".agentic/state.sqlite3",
        ".env",
        ".env.example",
        ".envrc",
        "config/.env-production",
        ".envs/.production/.postgres",
        "deploy/production.env",
        ".flaskenv",
        "worker/.dev.vars",
        "worker/.dev.vars.production",
        "key.pem",
        "node_modules/x.js",
    ],
)
def test_protected_files_are_never_source_tools(tmp_path, path):
    policy = WorkspacePolicy(tmp_path)
    assert policy.is_excluded(path)
    with pytest.raises(WorkbenchError):
        policy.read_source(path)


def test_symlinks_hardlinks_and_special_files_are_denied(tmp_path):
    outside = tmp_path.parent / f"outside-{tmp_path.name}"
    outside.write_text("outside data")
    (tmp_path / "link").symlink_to(outside)
    os.link(outside, tmp_path / "hardlink")
    os.mkfifo(tmp_path / "fifo")
    policy = WorkspacePolicy(tmp_path)
    for name in ("link", "hardlink", "fifo"):
        with pytest.raises(WorkbenchError):
            policy.read_source(name)


def test_symlink_parent_and_root_swap_are_denied(tmp_path):
    outside = tmp_path.parent / f"directory-{tmp_path.name}"
    outside.mkdir()
    (outside / "app.py").write_text("outside data")
    (tmp_path / "dir").symlink_to(outside, target_is_directory=True)
    policy = WorkspacePolicy(tmp_path)
    with pytest.raises(WorkbenchError):
        policy.read_source("dir/app.py")
    original = tmp_path.with_name(tmp_path.name + "-original")
    tmp_path.rename(original)
    tmp_path.mkdir()
    (tmp_path / "app.py").write_text("replacement data")
    with pytest.raises(WorkbenchError):
        policy.read_source("app.py")


def test_limits_and_explicit_write_grant(tmp_path):
    (tmp_path / "large.txt").write_text("abcdef")
    config = Config.from_dict({"scan": {"max_file_bytes": 3}})
    with pytest.raises(WorkbenchError, match="LIMIT_EXCEEDED"):
        WorkspacePolicy(tmp_path, config).read_source("large.txt")
    with pytest.raises(WorkbenchError, match="POLICY_DENIED"):
        WorkspacePolicy(tmp_path).check_write("app.py")
    WorkspacePolicy(tmp_path, grants=Grant(write=True)).check_write("app.py")


def test_state_directory_is_private_and_never_follows_a_link(tmp_path):
    policy = WorkspacePolicy(tmp_path)
    state = policy.prepare_state_dir()
    assert state == tmp_path / ".agentic"
    assert state.stat().st_mode & 0o777 == 0o700
    state.rmdir()
    state.symlink_to(tmp_path.parent, target_is_directory=True)
    with pytest.raises(WorkbenchError):
        policy.prepare_state_dir()


@pytest.mark.parametrize("path", [".env/private.py", ".envs/.production/settings.py"])
def test_files_inside_env_directories_are_denied_everywhere(tmp_path, path):
    from agentic_workbench.repository import scan_workspace
    from agentic_workbench.state import StateStore
    from agentic_workbench.tools import ReadTools

    target = tmp_path / path
    target.parent.mkdir(parents=True)
    target.write_text("PRIVATE_MARKER = 1\n")
    (tmp_path / "app.py").write_text("value = 1\n")
    policy = WorkspacePolicy(tmp_path)
    with pytest.raises(WorkbenchError, match="POLICY_DENIED"):
        policy.read_source(path)
    index = scan_workspace(policy)
    assert path not in index.files and "app.py" in index.files
    with StateStore(policy) as store:
        with pytest.raises(WorkbenchError, match="POLICY_DENIED"):
            ReadTools(policy, index, store).execute(
                "read_source", {"path": path, "start_line": 1, "end_line": 1, "source_hash": None}
            )
