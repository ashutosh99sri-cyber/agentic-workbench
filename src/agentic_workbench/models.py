"""Typed internal contracts and validation at JSON boundaries."""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from importlib.resources import files
from typing import Any, Literal

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from .errors import WorkbenchError


def canonical_json(value: Any) -> str:
    try:
        rendered = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        )
        rendered.encode("utf-8")
        return rendered
    except (TypeError, ValueError, RecursionError) as error:
        raise WorkbenchError("VALIDATION_ERROR", "Value is not finite JSON") from error


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


TRUNCATED = "...[truncated]"
_KEPT_CHARS = 1_024


def bounded_json(data: Any, limit: int) -> Any:
    """Copy of JSON data whose canonical form fits ``limit`` bytes, or None if irreducible.

    Long strings are cut first, measured in encoded JSON bytes; strings up to 1 KiB are kept,
    so identifiers, digests and paths survive. Then trailing entries of the largest list or
    object are dropped.
    """
    bounded = deepcopy(data)
    for _ in range(64):
        size = len(canonical_json(bounded).encode())
        if size <= limit:
            return bounded
        excess = size - limit
        strings: list[tuple[int, Any, Any]] = []
        containers: list[Any] = []
        stack: list[Any] = [bounded] if isinstance(bounded, (dict, list)) else []
        while stack:
            node = stack.pop()
            for key, item in node.items() if isinstance(node, dict) else enumerate(node):
                if isinstance(item, str) and len(item) > _KEPT_CHARS + 2 * len(TRUNCATED):
                    strings.append((len(canonical_json(item).encode()), node, key))
                elif isinstance(item, (dict, list)):
                    if len(item) > 1:
                        containers.append(item)
                    stack.append(item)
        if strings:
            encoded, node, key = max(strings, key=lambda entry: entry[0])
            text = node[key]
            per_char = max(1.0, (encoded - 2) / len(text))
            remove = int((excess + 6 * len(TRUNCATED)) / per_char) + 1
            node[key] = text[: max(_KEPT_CHARS, len(text) - remove)] + TRUNCATED
        elif containers:
            largest = max(containers, key=len)
            keep = max(1, int(len(largest) * limit / size * 0.9))
            if isinstance(largest, list):
                del largest[keep:]
            else:
                for name in list(largest)[keep:]:
                    del largest[name]
        else:
            break
    return bounded if len(canonical_json(bounded).encode()) <= limit else None


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@lru_cache(maxsize=1)
def _definitions() -> dict[str, Any]:
    resource = files("agentic_workbench").joinpath("schemas/contracts.json")
    return json.loads(resource.read_text(encoding="utf-8"))["$defs"]  # type: ignore[no-any-return]


def _schema(name: str) -> dict[str, Any]:
    definitions = _definitions()
    if name not in definitions:
        raise WorkbenchError("VALIDATION_ERROR", "Unknown contract")
    return {**definitions[name], "$defs": definitions}


def schema(name: str) -> dict[str, Any]:
    return deepcopy(_schema(name))


def validate(name: str, value: Any) -> None:
    canonical_json(value)
    failure = None
    try:
        # Only packaged definitions are shared; validator/resolver state stays call-local.
        Draft202012Validator(_schema(name)).validate(value)
    except ValidationError as error:
        failure = deepcopy(error)
    if failure is not None:
        # Raise outside the handler so neither cause nor context exposes shared definitions.
        raise WorkbenchError("VALIDATION_ERROR", f"Invalid {name} contract") from failure
    findings = [value] if name == "Finding" else value.get("findings", [])
    if any(finding["kind"] == "fact" and not finding["evidence"] for finding in findings):
        raise WorkbenchError("VALIDATION_ERROR", "Fact findings require source evidence")


def strict_json(text: str, max_bytes: int = 1_048_576) -> Any:
    try:
        size = len(text.encode("utf-8"))
    except UnicodeError as error:
        raise WorkbenchError("VALIDATION_ERROR", "Invalid JSON encoding") from error
    if size > max_bytes:
        raise WorkbenchError("LIMIT_EXCEEDED", "JSON input exceeds the byte limit")

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise WorkbenchError("VALIDATION_ERROR", "Duplicate JSON property")
            result[key] = value
        return result

    try:
        value = json.loads(text, object_pairs_hook=pairs)
        canonical_json(value)
        return value
    except (ValueError, RecursionError) as error:
        raise WorkbenchError("VALIDATION_ERROR", "Invalid JSON input") from error


@dataclass(frozen=True)
class Grant:
    """Authority supplied by trusted host code, never by model/tool arguments."""

    network: bool = False
    write: bool = False
    execute: bool = False
    trusted_host: bool = False
    provider_hosts: tuple[str, ...] = ("api.openai.com",)

    def __post_init__(self) -> None:
        if any(
            type(value) is not bool
            for value in (self.network, self.write, self.execute, self.trusted_host)
        ):
            raise WorkbenchError("VALIDATION_ERROR", "Grants require boolean values")
        if not isinstance(self.provider_hosts, tuple) or not all(
            isinstance(host, str) and re.fullmatch(r"[a-z0-9.-]+", host)
            for host in self.provider_hosts
        ):
            raise WorkbenchError("VALIDATION_ERROR", "Grants require host names, not URLs")


@dataclass(frozen=True)
class Evidence:
    path: str
    start_line: int
    end_line: int
    source_hash: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Finding:
    title: str
    details: str
    kind: Literal["fact", "inference", "unknown"] = "inference"
    severity: Literal["info", "low", "medium", "high", "critical"] = "info"
    evidence: list[Evidence] = field(default_factory=list)

    def __post_init__(self) -> None:
        validate("Finding", asdict(self))


@dataclass(frozen=True)
class Usage:
    requests: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    unknown_receipts: int = 0
    estimated_cost_usd: float | None = None


@dataclass(frozen=True)
class AgentResult:
    task_id: str
    agent: str
    mode: Literal["static", "llm"]
    summary: str
    evidence: list[Evidence] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    proposal_ids: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        validate("AgentResult", data)
        return data
