"""Bounded configuration; project settings cannot grant execution authority."""

from __future__ import annotations

import re
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .errors import WorkbenchError
from .models import canonical_hash


def _bound(name: str, value: int, maximum: int) -> None:
    if type(value) is not int or not 1 <= value <= maximum:
        raise WorkbenchError("CONFIG_ERROR", f"Invalid bounded integer: {name}")


def _text(name: str, value: str, maximum: int = 4096) -> None:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= maximum
        or any(char in value for char in ("\x00", "\r", "\n"))
    ):
        raise WorkbenchError("CONFIG_ERROR", f"Invalid text field: {name}")


@dataclass(frozen=True)
class ScanConfig:
    max_files: int = 10_000
    max_file_bytes: int = 524_288
    max_total_bytes: int = 52_428_800

    def __post_init__(self) -> None:
        _bound("max_files", self.max_files, 100_000)
        _bound("max_file_bytes", self.max_file_bytes, 8_388_608)
        _bound("max_total_bytes", self.max_total_bytes, 1_073_741_824)


@dataclass(frozen=True)
class ProviderConfig:
    name: str = "none"
    model: str | None = None
    embedding_model: str | None = None
    credential_env: str = "OPENAI_API_KEY"

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", self.name):
            raise WorkbenchError("CONFIG_ERROR", "Invalid provider name")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", self.credential_env):
            raise WorkbenchError("CONFIG_ERROR", "Credentials require an environment variable name")
        for model in (self.model, self.embedding_model):
            if model is not None:
                _text("model", model, 200)
                if model.startswith("sk-") or not re.fullmatch(r"[A-Za-z0-9_.:/-]+", model):
                    raise WorkbenchError("CONFIG_ERROR", "Invalid model identifier")


@dataclass(frozen=True)
class Limits:
    provider_requests: int = 8
    tool_rounds: int = 6
    context_bytes: int = 16_000
    max_output_tokens: int = 2_000
    request_timeout: int = 60

    def __post_init__(self) -> None:
        for name, maximum in (
            ("provider_requests", 128),
            ("tool_rounds", 32),
            ("context_bytes", 1_048_576),
            ("max_output_tokens", 32_768),
            ("request_timeout", 300),
        ):
            _bound(name, getattr(self, name), maximum)


READ_TOOLS = (
    "repository_summary",
    "read_source",
    "search_code",
    "lookup_memory",
    "list_symbols",
    "trace_symbol",
)


@dataclass(frozen=True)
class PolicyConfig:
    excludes: tuple[str, ...] = ()
    allowed_tools: tuple[str, ...] = READ_TOOLS

    def __post_init__(self) -> None:
        if not isinstance(self.excludes, tuple) or len(self.excludes) > 100:
            raise WorkbenchError("CONFIG_ERROR", "Invalid exclusion rules")
        for pattern in self.excludes:
            _text("exclusion", pattern, 256)
        if not isinstance(self.allowed_tools, tuple) or not set(self.allowed_tools) <= set(
            READ_TOOLS
        ):
            raise WorkbenchError("CONFIG_ERROR", "Configuration cannot grant additional tools")


@dataclass(frozen=True)
class StateConfig:
    retention_days: int = 30
    backup_retention_days: int = 90

    def __post_init__(self) -> None:
        _bound("retention_days", self.retention_days, 3650)
        _bound("backup_retention_days", self.backup_retention_days, 3650)


@dataclass(frozen=True)
class CommandConfig:
    argv: tuple[str, ...]
    image: str | None = None
    timeout: int = 60
    max_output_bytes: int = 1_048_576

    def __post_init__(self) -> None:
        if not isinstance(self.argv, tuple) or not 1 <= len(self.argv) <= 32:
            raise WorkbenchError("CONFIG_ERROR", "Commands require bounded argument arrays")
        for arg in self.argv:
            _text("command argument", arg)
        executable = Path(self.argv[0]).name.lower().removesuffix(".exe")
        if executable in {"sh", "bash", "zsh", "dash", "fish", "cmd", "pwsh", "powershell"}:
            raise WorkbenchError("CONFIG_ERROR", "Shell interpreter commands are prohibited")
        if (
            not Path(self.argv[0]).is_absolute() and any(char.isspace() for char in self.argv[0])
        ) or self.argv[0].startswith("-"):
            raise WorkbenchError("CONFIG_ERROR", "Invalid command executable")
        _bound("command timeout", self.timeout, 300)
        _bound("command output", self.max_output_bytes, 16_777_216)
        if self.image is not None and not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._/:+-]*@sha256:[a-f0-9]{64}", self.image
        ):
            raise WorkbenchError("CONFIG_ERROR", "Docker images require an immutable digest")


@dataclass(frozen=True)
class Config:
    schema_version: int = 1
    scan: ScanConfig = field(default_factory=ScanConfig)
    provider: ProviderConfig = field(default_factory=ProviderConfig)
    limits: Limits = field(default_factory=Limits)
    policy: PolicyConfig = field(default_factory=PolicyConfig)
    state: StateConfig = field(default_factory=StateConfig)
    commands: dict[str, CommandConfig] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise WorkbenchError("CONFIG_ERROR", "Unsupported configuration version")
        if len(self.commands) > 50 or any(
            not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", key) or not isinstance(value, CommandConfig)
            for key, value in self.commands.items()
        ):
            raise WorkbenchError("CONFIG_ERROR", "Invalid named commands")

    @property
    def fingerprint(self) -> str:
        return canonical_hash(asdict(self))

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Config:
        allowed = {"schema_version", "scan", "provider", "limits", "policy", "state", "commands"}
        if not isinstance(raw, dict) or set(raw) - allowed:
            raise WorkbenchError("CONFIG_ERROR", "Unknown configuration fields")
        try:
            sections = {key: raw.get(key, {}) for key in allowed - {"schema_version"}}
            if not all(isinstance(value, dict) for value in sections.values()):
                raise WorkbenchError("CONFIG_ERROR", "Configuration sections must be tables")
            policy = dict(sections["policy"])
            for key in ("excludes", "allowed_tools"):
                if key in policy:
                    if not isinstance(policy[key], list):
                        raise WorkbenchError("CONFIG_ERROR", "Policy lists require arrays")
                    policy[key] = tuple(policy[key])
            commands: dict[str, CommandConfig] = {}
            for name, values in sections["commands"].items():
                if not isinstance(values, dict) or not isinstance(values.get("argv"), list):
                    raise WorkbenchError("CONFIG_ERROR", "Commands require argument arrays")
                command = dict(values)
                command["argv"] = tuple(command["argv"])
                commands[name] = CommandConfig(**command)
            return cls(
                schema_version=raw.get("schema_version", 1),
                scan=ScanConfig(**sections["scan"]),
                provider=ProviderConfig(**sections["provider"]),
                limits=Limits(**sections["limits"]),
                policy=PolicyConfig(**policy),
                state=StateConfig(**sections["state"]),
                commands=commands,
            )
        except (TypeError, ValueError, AttributeError) as error:
            raise WorkbenchError("CONFIG_ERROR", "Invalid configuration structure") from error

    @classmethod
    def load(cls, path: Path) -> Config:
        try:
            with path.open("rb") as stream:
                data = stream.read(1_048_577)
            if len(data) > 1_048_576:
                raise WorkbenchError("CONFIG_ERROR", "Configuration exceeds byte limit")
            return cls.from_dict(tomllib.loads(data.decode("utf-8")))
        except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
            raise WorkbenchError("CONFIG_ERROR", "Cannot read valid TOML configuration") from error


DEFAULT_CONFIG = """schema_version = 1

[provider]
name = "none"
credential_env = "OPENAI_API_KEY"

[limits]
provider_requests = 8
tool_rounds = 6
context_bytes = 16000
max_output_tokens = 2000
request_timeout = 60

[state]
retention_days = 30
backup_retention_days = 90
"""
