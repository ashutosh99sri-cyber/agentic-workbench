"""Typed trusted-host tools with policy, receipts and conservative replay control."""

from __future__ import annotations

import inspect
import re
import time
from collections.abc import Callable
from contextlib import suppress
from copy import deepcopy
from dataclasses import asdict, dataclass
from threading import RLock
from typing import Any, Literal, Protocol

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from .errors import WorkbenchError
from .models import bounded_json, canonical_hash, canonical_json
from .policy import WorkspacePolicy
from .state import StateStore

Effect = Literal["read", "execute", "write", "destructive"]
_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,63}")
# Effect results come from bounded transports; this covers two 16 MiB command streams.
_EFFECT_RESULT_BYTES = 67_108_864
# Stored receipts stay under the 1 MiB state record cap.
_STORED_RESULT_BYTES = 1_000_000


def _schema(value: dict[str, Any]) -> None:
    def local(item: Any) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                if key in {"$ref", "$dynamicRef"} and (
                    not isinstance(child, str) or not child.startswith("#/")
                ):
                    raise WorkbenchError("CONFIG_ERROR", "Tool schemas require local references")
                local(child)
        elif isinstance(item, list):
            for child in item:
                local(child)

    try:
        if not isinstance(value, dict) or len(canonical_json(value).encode()) > 32_000:
            raise WorkbenchError("CONFIG_ERROR", "Tool schema exceeds bounds")
        local(value)
        Draft202012Validator.check_schema(value)
    except (SchemaError, RecursionError, TypeError) as error:
        raise WorkbenchError("CONFIG_ERROR", "Invalid tool schema") from error


def _too_deep(value: Any, limit: int = 256) -> bool:
    """Iterative depth check, so a pathological result cannot exhaust the stack."""
    stack: list[tuple[Any, int]] = [(value, 0)]
    while stack:
        item, depth = stack.pop()
        if depth > limit:
            return True
        if isinstance(item, dict):
            stack += [(child, depth + 1) for child in item.values()]
        elif isinstance(item, list):
            stack += [(child, depth + 1) for child in item]
    return False


def _validate(parameters: dict[str, Any], value: Any, maximum: int | None = 1_048_576) -> None:
    if maximum is not None and len(canonical_json(value).encode()) > maximum:
        raise WorkbenchError("LIMIT_EXCEEDED", "Tool JSON exceeds byte limit")
    try:
        Draft202012Validator(parameters).validate(value)
    except ValidationError as error:
        raise WorkbenchError("VALIDATION_ERROR", "Invalid tool input or output") from error


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    effect: Effect = "read"
    backend: str = "python"
    timeout: float = 30
    retries: int = 0
    replay_safe: bool = False
    model_visible: bool = False
    destination: str | None = None
    version: str = "1"

    def __post_init__(self) -> None:
        if (
            not isinstance(self.name, str)
            or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", self.name)
            or not isinstance(self.description, str)
            or not 1 <= len(self.description) <= 2048
            or self.effect not in {"read", "execute", "write", "destructive"}
            or self.backend not in {"repository", "python", "cli", "mcp", "api"}
            or type(self.timeout) not in (int, float)
            or not 0 < self.timeout <= 300
            or type(self.retries) is not int
            or not 0 <= self.retries <= 2
            or type(self.replay_safe) is not bool
            or type(self.model_visible) is not bool
            or (self.model_visible and self.effect != "read")
            or (self.retries and not self.replay_safe)
            or not isinstance(self.version, str)
            or not 1 <= len(self.version) <= 64
            or (self.destination is not None and not re.fullmatch(r"[a-z0-9.-]+", self.destination))
        ):
            raise WorkbenchError("CONFIG_ERROR", "Invalid tool descriptor")
        _schema(self.input_schema)
        _schema(self.output_schema)
        if self.input_schema.get("type") != "object":
            raise WorkbenchError("CONFIG_ERROR", "Tool arguments require an object schema")
        # Freeze caller-owned schema dictionaries by copying at the registration boundary.
        object.__setattr__(self, "input_schema", deepcopy(self.input_schema))
        object.__setattr__(self, "output_schema", deepcopy(self.output_schema))


@dataclass(frozen=True)
class ToolCall:
    timeout: float
    task_id: str | None
    review: dict[str, Any]


@dataclass(frozen=True)
class ToolResult:
    tool: str
    status: Literal["succeeded", "failed"]
    data: dict[str, Any] | None
    error: dict[str, object] | None
    elapsed_ms: float
    attempts: int
    backend: str
    cached: bool = False
    # A stored receipt too large to keep whole holds a bounded copy of the data.
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        # Shallow on purpose: asdict would deep-copy data recursively and fail on deep nesting.
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


ToolHandler = Callable[[dict[str, Any], ToolCall], dict[str, Any]]
Reviewer = Callable[[dict[str, Any]], dict[str, Any]]


class MCPClient(Protocol):
    """Trusted transport enforces timeout and owns process/network isolation."""

    def call_tool(
        self, name: str, arguments: dict[str, Any], *, timeout: float
    ) -> dict[str, Any]: ...


class ToolRegistry:
    """Repository content cannot register handlers or pass approval in arguments.

    Python callbacks are trusted host code with cooperative deadlines. Executable
    Python/CLI tools use register_command and the existing approved Runner sandbox.
    """

    def __init__(
        self,
        policy: WorkspacePolicy,
        store: StateStore,
        *,
        maximum_calls: int = 128,
    ) -> None:
        if type(maximum_calls) is not int or not 1 <= maximum_calls <= 10_000:
            raise WorkbenchError("CONFIG_ERROR", "Invalid tool call budget")
        self.policy, self.store, self.maximum_calls = policy, store, maximum_calls
        self._specs: dict[str, ToolSpec] = {}
        self._factories: dict[str, Callable[[], ToolHandler]] = {}
        self._handlers: dict[str, ToolHandler] = {}
        self._reviewers: dict[str, Reviewer] = {}
        self._lock = RLock()
        self._scope: tuple[str, ...] | None = None
        self._calls = 0
        self.task_id: str | None = None

    def register(
        self, spec: ToolSpec, handler: ToolHandler, *, reviewer: Reviewer | None = None
    ) -> None:
        if not callable(handler):
            raise WorkbenchError("CONFIG_ERROR", "Tool handler must be callable")
        self.register_lazy(spec, lambda: handler, reviewer=reviewer)

    def register_lazy(
        self,
        spec: ToolSpec,
        factory: Callable[[], ToolHandler],
        *,
        reviewer: Reviewer | None = None,
    ) -> None:
        with self._lock:
            if (
                not isinstance(spec, ToolSpec)
                or spec.name in self._specs
                or len(self._specs) >= 64
                or not callable(factory)
                or (reviewer is not None and not callable(reviewer))
                or self._scope is not None
            ):
                raise WorkbenchError("CONFIG_ERROR", "Invalid or duplicate tool registration")
            self._specs[spec.name] = deepcopy(spec)
            self._factories[spec.name] = factory
            if reviewer:
                self._reviewers[spec.name] = reviewer

    @property
    def fingerprint(self) -> str:
        return canonical_hash(
            {"tools": [asdict(s) for s in self._specs.values()], "policy": self.policy.fingerprint}
        )

    @property
    def model_tools(self) -> tuple[str, ...]:
        return tuple(s.name for s in self._specs.values() if s.model_visible and s.effect == "read")

    @property
    def allowed(self) -> tuple[str, ...]:
        return self._scope if self._scope is not None else tuple(self._specs)

    def scoped(
        self, required_tools: tuple[str, ...], *, task_id: str | None = None
    ) -> ToolRegistry:
        # Views share loaded handlers and the lock, while each role has its own scope.
        view = ToolRegistry(self.policy, self.store, maximum_calls=self.maximum_calls)
        view._specs, view._factories = self._specs, self._factories
        view._handlers, view._reviewers, view._lock = self._handlers, self._reviewers, self._lock
        view.task_id = task_id
        names = tuple(dict.fromkeys((*required_tools, *self.model_tools)))
        view._scope = tuple(
            name
            for name in names
            if name in self._specs
            and self._specs[name].effect == "read"
            and (
                self._specs[name].backend != "repository"
                or name in self.policy.config.policy.allowed_tools
            )
        )
        return view

    def discover(self) -> list[dict[str, Any]]:
        return [asdict(self._specs[name]) for name in self.allowed]

    @property
    def schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "name": spec.name,
                "description": spec.description,
                "strict": True,
                "parameters": deepcopy(spec.input_schema),
            }
            for name in self.allowed
            if (spec := self._specs[name]).effect == "read"
        ]

    def _spec(self, name: str, arguments: dict[str, Any]) -> ToolSpec:
        if name not in self.allowed or name not in self._specs:
            raise WorkbenchError("POLICY_DENIED", "Tool is not in the effective host scope")
        spec = self._specs[name]
        _validate(spec.input_schema, arguments)
        if self.policy.redactor.contains_secret(canonical_json(arguments)):
            raise WorkbenchError("POLICY_DENIED", "Tool arguments cannot contain credentials")
        if spec.destination:
            self.policy.check_network(spec.destination)
        if spec.effect in {"write", "destructive"} and not self.policy.grants.write:
            raise WorkbenchError("POLICY_DENIED", "Tool requires the host write grant")
        if spec.effect == "execute" and not self.policy.grants.execute:
            raise WorkbenchError("POLICY_DENIED", "Tool requires the host execute grant")
        return spec

    def _public(self, raw: WorkbenchError) -> WorkbenchError:
        """Redacted, bounded copy of a host callback error for every returned or raised sink."""
        try:
            code = getattr(raw, "code", None)
            code = code if isinstance(code, str) and _CODE.fullmatch(code) else ""
            if not code or self.policy.redactor.contains_secret(code):
                code = "TOOL_FAILED"
            message = self.policy.redactor.redact(str(getattr(raw, "message", "")))[:1000]
            retryable = getattr(raw, "retryable", False) is True
        except Exception:
            return WorkbenchError("TOOL_FAILED", "Tool error could not be sanitized")
        return WorkbenchError(code, message, retryable=retryable)

    def review(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        spec = self._spec(name, arguments)
        detail: dict[str, Any] = {}
        if name in self._reviewers:
            failure: WorkbenchError | None = None
            try:
                detail = self._reviewers[name](arguments)
            except WorkbenchError as raw:
                failure = self._public(raw)
            except BaseException:
                failure = WorkbenchError("TOOL_FAILED", "Tool reviewer failed")
            # Raised outside the except block, so the raw error is not kept as __context__.
            if failure is not None:
                raise failure
        reviewed = {
            "tool": name,
            "descriptor": asdict(spec),
            "arguments": deepcopy(arguments),
            "policy": self.policy.fingerprint,
            "external_review": detail,
        }
        return {**reviewed, "digest": canonical_hash(reviewed)}

    def _handler(self, name: str, task_id: str | None) -> ToolHandler:
        with self._lock:
            if name not in self._handlers:
                if task_id is not None and self.store.cancelled(task_id):
                    raise WorkbenchError("CANCELLED", "Tool task was cancelled by the host")
                failure: WorkbenchError | None = None
                try:
                    handler = self._factories[name]()
                except WorkbenchError as raw:
                    failure = self._public(raw)
                except BaseException:
                    failure = WorkbenchError("CONFIG_ERROR", "Tool loader failed")
                if failure is not None:
                    raise failure
                if not callable(handler):
                    raise WorkbenchError("CONFIG_ERROR", "Tool loader did not return a handler")
                self._handlers[name] = handler
            return self._handlers[name]

    def invoke(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        approval: str | None = None,
        idempotency_key: str | None = None,
        task_id: str | None = None,
    ) -> ToolResult:
        spec = self._spec(name, arguments)
        review = self.review(name, arguments)
        if spec.effect != "read":
            if approval is None:
                raise WorkbenchError(
                    "APPROVAL_REQUIRED", "Tool execution needs exact host approval"
                )
            if approval != review["digest"]:
                raise WorkbenchError("STALE_APPROVAL", "Tool operation review changed")
            if idempotency_key is None:
                raise WorkbenchError(
                    "VALIDATION_ERROR", "Effectful tools require an idempotency key"
                )
        if idempotency_key is not None and (
            not isinstance(idempotency_key, str) or not 1 <= len(idempotency_key) <= 256
        ):
            raise WorkbenchError("VALIDATION_ERROR", "Invalid tool idempotency key")
        fingerprint = canonical_hash({"operation": review, "task_id": task_id})
        key = canonical_hash({"tool": name, "key": idempotency_key})
        operation_kind = "tool-operation"
        if idempotency_key is not None:
            known = self.store.operation(operation_kind, key)
            if known and known.get("fingerprint") == fingerprint and known["state"] == "received":
                # A completed operation replays its receipt even after a cancel; nothing runs.
                return ToolResult(**{**known["result"], "cached": True})
        if task_id is not None and self.store.cancelled(task_id):
            raise WorkbenchError("CANCELLED", "Tool task was cancelled by the host")
        claimed = dispatched = False
        if idempotency_key is not None:
            prior = self.store.begin_operation(operation_kind, key, fingerprint)
            claimed = prior is None
            if prior is not None:
                if prior["fingerprint"] != fingerprint:
                    raise WorkbenchError("CONFLICT", "Idempotency key identifies another operation")
                if prior["state"] != "received":
                    raise WorkbenchError("OUTCOME_UNKNOWN", "Tool operation has no durable receipt")
                return ToolResult(**{**prior["result"], "cached": True})
        started = time.monotonic()
        try:
            with self._lock:
                self._calls += 1
                if self._calls > self.maximum_calls:
                    raise WorkbenchError("LIMIT_EXCEEDED", "Tool call budget is exhausted")
            if task_id is not None:
                root_id = self.store.get_task(task_id)["root_id"]
                self.store.reserve_tool_call(root_id, self.maximum_calls)
                self.store.event(task_id, "tool.authorized", {"tool": name, "status": spec.effect})
            handler = self._handler(name, task_id)
            error_data: dict[str, object] | None = None
            data: dict[str, Any] | None = None
            attempts = 0
            cancelled = truncated = False
            rejected: WorkbenchError | None = None
            for attempt in range(spec.retries + 1):
                # Recheck before every dispatch: a cancel during one attempt stops the retry.
                if task_id is not None and self.store.cancelled(task_id):
                    if not dispatched:
                        raise WorkbenchError("CANCELLED", "Tool task was cancelled by the host")
                    cancelled = True
                    error_data = WorkbenchError("CANCELLED", "Tool task was cancelled").to_dict()
                    data = None
                    break
                remaining = spec.timeout - (time.monotonic() - started)
                if remaining <= 0:
                    if rejected is None:
                        raise WorkbenchError(
                            "DEADLINE_EXCEEDED", "Tool deadline elapsed before dispatch"
                        )
                    # Only a known rejection reaches a retry, so that outcome stands.
                    error_data, data = rejected.to_dict(), None
                    break
                attempts = attempt + 1
                failure: WorkbenchError | None = None
                dispatched = True
                try:
                    data = handler(deepcopy(arguments), ToolCall(remaining, task_id, review))
                    if time.monotonic() - started > spec.timeout:
                        raise WorkbenchError(
                            "OUTCOME_UNKNOWN", "Tool completed beyond its deadline"
                        )
                    if not isinstance(data, dict):
                        raise WorkbenchError("VALIDATION_ERROR", "Tool result requires an object")
                    if spec.effect != "read" and _too_deep(data):
                        # The effect completed, but its result cannot be represented safely.
                        data, truncated = None, True
                        break
                    # Validate the handler's own result before redaction: replacing a typed value
                    # with "[REDACTED]" must not turn a known outcome into an invalid receipt.
                    # Effects validate whole (their transports are bounded) and are bounded below.
                    _validate(
                        spec.output_schema, data, 1_048_576 if spec.effect == "read" else None
                    )
                    data = self.policy.redactor.clean(data)
                    if (
                        spec.effect != "read"
                        and len(canonical_json(data).encode()) > _EFFECT_RESULT_BYTES
                    ):
                        data = bounded_json(data, _EFFECT_RESULT_BYTES)
                        truncated = True
                    # Only reads reach model context; effects are host-only and keep receipts.
                    if spec.effect == "read" and len(canonical_json(data).encode()) > 12_000:
                        raise WorkbenchError(
                            "LIMIT_EXCEEDED", "Tool result exceeds context byte limit"
                        )
                    break
                except WorkbenchError as raw:
                    failure = self._public(raw)
                # Handled outside the except block: no raw error stays reachable as __context__.
                assert failure is not None
                if failure.code == "OUTCOME_UNKNOWN":
                    raise failure
                safe_retry = (
                    spec.replay_safe
                    and failure.retryable
                    and failure.code == "TOOL_REJECTED"
                    and attempt < spec.retries
                )
                if safe_retry:
                    rejected = failure
                    continue
                if spec.effect != "read" and failure.code != "TOOL_REJECTED":
                    raise WorkbenchError(
                        "OUTCOME_UNKNOWN", "Effectful tool has no valid receipt"
                    ) from failure
                error_data = failure.to_dict()
                data = None
                break
            result = ToolResult(
                name,
                "failed" if error_data else "succeeded",
                data,
                error_data,
                round((time.monotonic() - started) * 1000, 3),
                attempts,
                spec.backend,
                truncated=truncated,
            )
            if idempotency_key is not None:
                stored = result.to_dict()
                if len(canonical_json(stored).encode()) > _STORED_RESULT_BYTES:
                    # The outcome is known: keep a bounded receipt rather than leave it pending.
                    stored["data"] = bounded_json(stored["data"], _STORED_RESULT_BYTES - 4_096)
                    stored["truncated"] = True
                self.store.finish_operation(operation_kind, key, fingerprint, stored)
            if task_id:
                self.store.event(
                    task_id,
                    "tool.received",
                    {"tool": name, "status": result.status, "elapsed_ms": result.elapsed_ms},
                )
            if cancelled:
                raise WorkbenchError("CANCELLED", "Tool task was cancelled by the host")
            return result
        except WorkbenchError:
            if claimed and not dispatched:
                self._release(operation_kind, key, fingerprint)
            raise
        except BaseException:
            if claimed and not dispatched:
                self._release(operation_kind, key, fingerprint)
            stopped = True
        # Pending operation remains durable, so interrupted effects cannot replay. Raised here,
        # outside the except block, so the raw exception is not kept as __context__.
        assert stopped
        if not dispatched:
            raise WorkbenchError("TOOL_FAILED", "Tool stopped before dispatch")
        raise WorkbenchError("OUTCOME_UNKNOWN", "Tool stopped without a validated receipt")

    def _release(self, kind: str, key: str, fingerprint: str) -> None:
        # Nothing was dispatched, so the claim carries no effect and the key stays usable.
        with suppress(WorkbenchError):
            self.store.release_operation(kind, key, fingerprint)

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = self.invoke(name, arguments, task_id=self.task_id)
        if result.error:
            raise WorkbenchError(
                str(result.error["code"]),
                str(result.error["message"]),
                retryable=bool(result.error["retryable"]),
            )
        assert result.data is not None
        return result.data

    def register_read_tools(self, tools: Any) -> None:
        for item in tools.schemas:
            name = item["name"]

            def bind(tool_name: str) -> ToolHandler:
                def execute(arguments: dict[str, Any], call: ToolCall) -> dict[str, Any]:
                    return tools.execute(tool_name, arguments)  # type: ignore[no-any-return]

                return execute

            self.register(
                ToolSpec(
                    name,
                    item["description"],
                    item["parameters"],
                    {"type": "object"},
                    backend="repository",
                    version=tools.index.fingerprint,
                ),
                bind(name),
            )

    def register_command(
        self, name: str, command_id: str, *, backend: str = "docker", python: bool = False
    ) -> None:
        from .runner import Runner

        if command_id not in self.policy.config.commands:
            raise WorkbenchError("CONFIG_ERROR", "Tool command must be declared in configuration")
        runner = Runner(self.policy, self.store)
        self.register(
            ToolSpec(
                name,
                f"Execute reviewed named command {command_id}",
                {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
                {"type": "object"},
                effect="execute",
                backend="python" if python else "cli",
                timeout=self.policy.config.commands[command_id].timeout,
            ),
            lambda arguments, call: runner.execute(
                command_id, call.review["external_review"]["digest"], backend
            ),
            reviewer=lambda arguments: runner.review(command_id, backend),
        )

    def register_mcp(
        self,
        spec: ToolSpec,
        client: MCPClient,
        remote_name: str,
        *,
        reviewer: Reviewer | None = None,
    ) -> None:
        if spec.backend != "mcp":
            raise WorkbenchError("CONFIG_ERROR", "MCP binding requires an MCP descriptor")
        if getattr(client, "execution_effect", None) == "execute" and (
            spec.effect != "execute" or spec.model_visible or reviewer is None
        ):
            raise WorkbenchError("CONFIG_ERROR", "MCP processes require exact execution approval")
        # Reads feed model context; effect receipts get the registry's result bound. Host
        # clients that predate the limit keyword keep working without it.
        limit = {"limit": 64_000 if spec.effect == "read" else 1_048_576}
        if "limit" not in inspect.signature(client.call_tool).parameters:
            limit = {}
        self.register(
            spec,
            lambda arguments, call: client.call_tool(
                remote_name, arguments, timeout=call.timeout, **limit
            ),
            reviewer=lambda arguments: {
                "remote_name": remote_name,
                "transport": reviewer(arguments) if reviewer is not None else {},
            },
        )
