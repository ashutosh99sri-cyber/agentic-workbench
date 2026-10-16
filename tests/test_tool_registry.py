import time
from pathlib import Path

import pytest

from agentic_workbench import Grant, WorkbenchError
from agentic_workbench.policy import WorkspacePolicy
from agentic_workbench.secrets import SecretRedactor
from agentic_workbench.state import StateStore
from agentic_workbench.tool_registry import ToolRegistry, ToolSpec

EMPTY = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}
OUTPUT = {
    "type": "object",
    "properties": {"value": {"type": "integer"}},
    "required": ["value"],
    "additionalProperties": False,
}


def test_discovery_lazy_loading_schema_and_host_scope(tmp_path: Path) -> None:
    policy = WorkspacePolicy(tmp_path)
    with StateStore(policy) as store:
        registry = ToolRegistry(policy, store)
        loaded = []

        def factory():
            loaded.append(True)
            return lambda arguments, call: {"value": 7}

        spec = ToolSpec("counter", "Read a host counter", EMPTY, OUTPUT, model_visible=True)
        registry.register_lazy(spec, factory)
        assert loaded == []
        assert registry.scoped(()).allowed == ("counter",)
        assert registry.execute("counter", {})["value"] == 7
        assert loaded == [True]
        with pytest.raises(WorkbenchError, match="VALIDATION_ERROR"):
            registry.execute("counter", {"approve": True})
        with pytest.raises(WorkbenchError, match="CONFIG_ERROR"):
            registry.register_lazy(spec, factory)
        registry.register(ToolSpec("hidden", "Host only", EMPTY, OUTPUT), factory())
        with pytest.raises(WorkbenchError, match="POLICY_DENIED"):
            registry.scoped(()).execute("hidden", {})


def test_model_schema_projection_preserves_scope_order_and_nested_isolation(tmp_path):
    parameters = {
        "type": "object",
        "properties": {"message": {"type": "string", "minLength": 1}},
        "required": ["message"],
        "additionalProperties": False,
    }
    with StateStore(WorkspacePolicy(tmp_path)) as store:
        registry = ToolRegistry(store.policy, store)
        for name in ("first", "second"):
            registry.register(
                ToolSpec(name, name, parameters, OUTPUT, model_visible=True),
                lambda arguments, call: {"value": 1},
            )
        registry.register(ToolSpec("hidden", "Host only", EMPTY, OUTPUT), lambda a, c: {})
        registry.register(
            ToolSpec("write", "Host write", EMPTY, OUTPUT, effect="write"), lambda a, c: {}
        )
        # Unscoped registries are trusted host views; scoped model views omit hidden reads.
        assert [item["name"] for item in registry.schemas] == ["first", "second", "hidden"]
        scoped = registry.scoped(("second",))
        assert [item["name"] for item in scoped.schemas] == ["second", "first"]
        exposed = scoped.schemas
        exposed[0]["parameters"]["properties"]["message"]["minLength"] = 0
        parameters["properties"]["message"]["minLength"] = 0
        assert scoped.schemas[0]["parameters"]["properties"]["message"]["minLength"] == 1
        assert scoped.execute("second", {"message": "ok"}) == {"value": 1}
        with pytest.raises(WorkbenchError, match="VALIDATION_ERROR"):
            scoped.execute("second", {"message": ""})


def test_effect_approval_and_durable_idempotency(tmp_path: Path) -> None:
    policy = WorkspacePolicy(tmp_path, grants=Grant(write=True))
    calls = []
    with StateStore(policy) as store:
        registry = ToolRegistry(policy, store)
        registry.register(
            ToolSpec("write_counter", "Host write", EMPTY, OUTPUT, effect="write"),
            lambda arguments, call: calls.append(True) or {"value": 1},
        )
        review = registry.review("write_counter", {})
        with pytest.raises(WorkbenchError, match="APPROVAL_REQUIRED"):
            registry.invoke("write_counter", {}, idempotency_key="one")
        result = registry.invoke(
            "write_counter", {}, approval=review["digest"], idempotency_key="one"
        )
        assert result.status == "succeeded"
        assert registry.invoke(
            "write_counter", {}, approval=review["digest"], idempotency_key="one"
        ).cached
        assert calls == [True]
    with StateStore(policy) as store:
        registry = ToolRegistry(policy, store)
        registry.register(
            ToolSpec("write_counter", "Host write", EMPTY, OUTPUT, effect="write"),
            lambda arguments, call: pytest.fail("replayed a completed write"),
        )
        assert registry.invoke(
            "write_counter", {}, approval=review["digest"], idempotency_key="one"
        ).cached


def test_retry_unknown_effects_and_result_validation(tmp_path: Path) -> None:
    policy = WorkspacePolicy(tmp_path, grants=Grant(write=True))
    with StateStore(policy) as store:
        registry = ToolRegistry(policy, store)
        attempts = []

        def retry(arguments, call):
            attempts.append(1)
            if len(attempts) == 1:
                raise WorkbenchError("TOOL_REJECTED", "Not admitted", retryable=True)
            return {"value": 2}

        registry.register(
            ToolSpec("retry", "Replay safe read", EMPTY, OUTPUT, retries=1, replay_safe=True),
            retry,
        )
        assert registry.invoke("retry", {}).attempts == 2
        registry.register(
            ToolSpec("bad", "Invalid output", EMPTY, OUTPUT),
            lambda arguments, call: {"value": "invalid"},
        )
        with pytest.raises(WorkbenchError, match="VALIDATION_ERROR"):
            registry.execute("bad", {})

        def unknown(arguments, call):
            raise TimeoutError("secret transport body")

        registry.register(ToolSpec("effect", "Write", EMPTY, OUTPUT, effect="write"), unknown)
        digest = registry.review("effect", {})["digest"]
        for _ in range(2):
            with pytest.raises(WorkbenchError, match="OUTCOME_UNKNOWN"):
                registry.invoke("effect", {}, approval=digest, idempotency_key="uncertain")


def test_schemas_cannot_fetch_remote_refs_or_expose_effects() -> None:
    with pytest.raises(WorkbenchError):
        ToolSpec("remote", "Bad schema", {**EMPTY, "$ref": "https://example.com/schema"}, OUTPUT)
    with pytest.raises(WorkbenchError):
        ToolSpec("write", "Bad exposure", EMPTY, OUTPUT, effect="write", model_visible=True)


def test_cancellation_between_attempts_stops_dispatch_with_a_known_outcome(
    tmp_path: Path,
) -> None:
    policy = WorkspacePolicy(tmp_path, grants=Grant(write=True))
    with StateStore(policy) as store:
        task = store.create_task("reviewer", "Cancel before retry", {})
        calls = []

        def handler(arguments, call):
            calls.append(store.get_task(task)["state"])
            store.cancel_tree(task)
            raise WorkbenchError("TOOL_REJECTED", "Known admission refusal", retryable=True)

        registry = ToolRegistry(policy, store)
        registry.register(
            ToolSpec("effect", "Write", EMPTY, OUTPUT, effect="write", retries=1, replay_safe=True),
            handler,
        )
        digest = registry.review("effect", {})["digest"]
        with pytest.raises(WorkbenchError, match="CANCELLED"):
            registry.invoke("effect", {}, approval=digest, idempotency_key="one", task_id=task)
        assert calls == ["pending"]
        [operation] = store.list_records("tool-operation")
        assert operation["value"]["state"] == "received"


@pytest.mark.parametrize("during_load", [False, True])
def test_cancellation_stops_lazy_loading_and_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, during_load: bool
) -> None:
    policy = WorkspacePolicy(tmp_path, grants=Grant(write=True))
    with StateStore(policy) as store:
        root = store.create_task("reviewer", "Root", {})
        task = store.create_task("reviewer", "Linked", {}, root_id=root)
        loaded: list[int] = []
        calls: list[int] = []

        def factory():
            loaded.append(1)
            if during_load:
                store.cancel_tree(root)
            return lambda arguments, call: calls.append(1) or {"value": 1}

        original = store.event

        def cancel_before_load(task_id: str, name: str, metadata: dict[str, object]) -> int:
            event = original(task_id, name, metadata)
            if name == "tool.authorized" and not during_load:
                store.cancel_tree(root)
            return event

        monkeypatch.setattr(store, "event", cancel_before_load)
        registry = ToolRegistry(policy, store)
        registry.register_lazy(ToolSpec("effect", "Write", EMPTY, OUTPUT, effect="write"), factory)
        digest = registry.review("effect", {})["digest"]
        with pytest.raises(WorkbenchError, match="CANCELLED"):
            registry.invoke("effect", {}, approval=digest, idempotency_key="one", task_id=task)
        assert loaded == ([1] if during_load else []) and calls == []
        assert store.list_records("tool-operation") == []


def test_large_effect_result_keeps_its_receipt_while_reads_stay_bounded(tmp_path: Path) -> None:
    policy = WorkspacePolicy(tmp_path, grants=Grant(write=True))
    log = {
        "type": "object",
        "properties": {"log": {"type": "string"}},
        "required": ["log"],
        "additionalProperties": False,
    }
    with StateStore(policy) as store:
        registry = ToolRegistry(policy, store)
        registry.register(
            ToolSpec("effect", "Write", EMPTY, log, effect="write"),
            lambda arguments, call: {"log": "x" * 13_000},
        )
        digest = registry.review("effect", {})["digest"]
        first = registry.invoke("effect", {}, approval=digest, idempotency_key="one")
        assert first.status == "succeeded" and first.data == {"log": "x" * 13_000}
        assert registry.invoke("effect", {}, approval=digest, idempotency_key="one").cached
        registry.register(
            ToolSpec("big_read", "Read", EMPTY, log, model_visible=True),
            lambda arguments, call: {"log": "x" * 13_000},
        )
        with pytest.raises(WorkbenchError, match="LIMIT_EXCEEDED"):
            registry.execute("big_read", {})


def test_tool_errors_are_redacted_and_bounded(tmp_path: Path) -> None:
    marker = "synthetic-tool-credential-value"
    policy = WorkspacePolicy(tmp_path, redactor=SecretRedactor((marker,)))
    with StateStore(policy) as store:
        registry = ToolRegistry(policy, store)

        def reject(arguments, call):
            raise WorkbenchError("TOOL_REJECTED", "Transport failed for " + marker + "x" * 5000)

        registry.register(
            ToolSpec("probe", "Read probe", EMPTY, OUTPUT, model_visible=True), reject
        )
        result = registry.scoped(()).invoke("probe", {})
        assert result.error is not None
        assert marker not in str(result.error["message"])
        assert len(str(result.error["message"])) <= 1000
        with pytest.raises(WorkbenchError) as raised:
            registry.scoped(()).execute("probe", {})
        assert marker not in str(raised.value) and marker not in raised.value.message


def test_prefixed_structured_credentials_never_reach_tool_output_or_state(tmp_path: Path) -> None:
    marker = "synthetic-structured-credential"
    policy = WorkspacePolicy(tmp_path)
    with StateStore(policy) as store:
        registry = ToolRegistry(policy, store)
        registry.register(
            ToolSpec("read_config", "Read config", EMPTY, {"type": "object"}, model_visible=True),
            lambda arguments, call: {"SERVICE_AUTH_TOKEN": marker, "clientSecret": marker},
        )
        assert marker not in str(registry.scoped(()).execute("read_config", {}))
        store.save("fixture", "one", {"SERVICE_AUTH_TOKEN": marker})
        assert marker not in str(store.export())


MARKER = "synthetic-configured-credential"


def _exception_chain(error: BaseException | None) -> list[BaseException]:
    seen: list[BaseException] = []
    stack = [error]
    while stack:
        item = stack.pop()
        if item is not None and all(item is not other for other in seen):
            seen.append(item)
            stack += [item.__cause__, item.__context__]
    return seen


def _reject(*args: object) -> dict[str, object]:
    raise WorkbenchError("TOOL_REJECTED", "Transport failed for " + MARKER)


@pytest.mark.parametrize("sink", ["lazy_factory", "reviewer", "error_code"])
def test_public_tool_error_sinks_never_disclose_credentials(tmp_path: Path, sink: str) -> None:
    policy = WorkspacePolicy(tmp_path, redactor=SecretRedactor((MARKER,)))
    with StateStore(policy) as store:
        registry = ToolRegistry(policy, store)
        spec = ToolSpec("probe", "Read probe", EMPTY, OUTPUT, model_visible=True)
        if sink == "lazy_factory":
            registry.register_lazy(spec, _reject)  # type: ignore[arg-type]
        elif sink == "reviewer":
            registry.register(spec, lambda arguments, call: {"value": 1}, reviewer=_reject)
        else:

            def handler(arguments: object, call: object) -> dict[str, object]:
                raise WorkbenchError(MARKER, "Safe message")

            registry.register(spec, handler)
        try:
            public = registry.scoped(()).invoke("probe", {}).to_dict()
            chain: list[BaseException] = []
        except WorkbenchError as error:
            public, chain = error.to_dict(), _exception_chain(error)
        assert MARKER not in str(public)
        assert all(MARKER not in str(item) for item in chain)


def test_legitimate_error_codes_survive_sanitizing(tmp_path: Path) -> None:
    policy = WorkspacePolicy(tmp_path, redactor=SecretRedactor((MARKER,)))
    with StateStore(policy) as store:
        registry = ToolRegistry(policy, store)
        registry.register(
            ToolSpec("probe", "Read probe", EMPTY, OUTPUT, model_visible=True), _reject
        )
        error = registry.scoped(()).invoke("probe", {}).error
        assert error is not None and error["code"] == "TOOL_REJECTED"
        assert MARKER not in str(error["message"])


@pytest.mark.parametrize(
    "failure",
    [
        WorkbenchError("OUTCOME_UNKNOWN", "Uncertain " + MARKER),
        WorkbenchError("WRITE_FAILED", "Failed " + MARKER),
        TimeoutError("transport body " + MARKER),
    ],
    ids=["unknown", "effect-error", "non-workbench"],
)
def test_raised_tool_errors_keep_no_raw_exception_in_their_chain(
    tmp_path: Path, failure: BaseException
) -> None:
    policy = WorkspacePolicy(tmp_path, grants=Grant(write=True), redactor=SecretRedactor((MARKER,)))
    with StateStore(policy) as store:
        registry = ToolRegistry(policy, store)

        def handler(arguments: object, call: object) -> dict[str, object]:
            raise failure

        registry.register(ToolSpec("effect", "Write", EMPTY, OUTPUT, effect="write"), handler)
        digest = registry.review("effect", {})["digest"]
        with pytest.raises(WorkbenchError) as raised:
            registry.invoke("effect", {}, approval=digest, idempotency_key="one")
        assert raised.value.code == "OUTCOME_UNKNOWN"
        assert all(MARKER not in str(item) for item in _exception_chain(raised.value))


def test_root_cancellation_stops_retries_of_root_linked_tasks(tmp_path: Path) -> None:
    policy = WorkspacePolicy(tmp_path, grants=Grant(write=True))
    with StateStore(policy) as store:
        root = store.create_task("reviewer", "root", {})
        linked = store.create_task("reviewer", "linked budget", {}, root_id=root)
        calls: list[int] = []

        def handler(arguments: object, call: object) -> dict[str, object]:
            calls.append(1)
            store.cancel_tree(root)
            raise WorkbenchError("TOOL_REJECTED", "Known refusal", retryable=True)

        registry = ToolRegistry(policy, store)
        registry.register(
            ToolSpec("effect", "Write", EMPTY, OUTPUT, effect="write", retries=1, replay_safe=True),
            handler,
        )
        digest = registry.review("effect", {})["digest"]
        with pytest.raises(WorkbenchError, match="CANCELLED"):
            registry.invoke("effect", {}, approval=digest, idempotency_key="one", task_id=linked)
        assert calls == [1]


def test_failures_before_dispatch_leave_no_pending_operation(tmp_path: Path) -> None:
    policy = WorkspacePolicy(tmp_path, grants=Grant(write=True))
    spec = ToolSpec("effect", "Write", EMPTY, OUTPUT, effect="write")
    with StateStore(policy) as store:

        def broken_loader() -> object:
            raise WorkbenchError("CONFIG_ERROR", "Loader unavailable")

        registry = ToolRegistry(policy, store)
        registry.register_lazy(spec, broken_loader)  # type: ignore[arg-type]
        digest = registry.review("effect", {})["digest"]
        with pytest.raises(WorkbenchError, match="CONFIG_ERROR"):
            registry.invoke("effect", {}, approval=digest, idempotency_key="one")
        assert store.list_records("tool-operation") == []
        calls: list[int] = []
        limited = ToolRegistry(policy, store, maximum_calls=1)
        limited.register(spec, lambda arguments, call: calls.append(1) or {"value": 1})
        assert limited.invoke("effect", {}, approval=digest, idempotency_key="one").status == (
            "succeeded"
        )
        with pytest.raises(WorkbenchError, match="LIMIT_EXCEEDED"):
            limited.invoke("effect", {}, approval=digest, idempotency_key="two")
        states = {r["value"]["state"] for r in store.list_records("tool-operation")}
        assert calls == [1] and states == {"received"}
        root = store.create_task("reviewer", "root", {})
        linked = store.create_task("reviewer", "linked", {}, root_id=root)
        store.cancel_tree(root)
        with pytest.raises(WorkbenchError, match="CANCELLED"):
            limited.invoke("effect", {}, approval=digest, idempotency_key="three", task_id=linked)
        assert len(store.list_records("tool-operation")) == 1


def test_result_near_the_storage_ceiling_keeps_a_bounded_known_receipt(tmp_path: Path) -> None:
    policy = WorkspacePolicy(tmp_path, grants=Grant(write=True))
    log = {
        "type": "object",
        "properties": {"log": {"type": "string"}, "exit_code": {"type": "integer"}},
        "required": ["log", "exit_code"],
        "additionalProperties": False,
    }
    data = {"log": "x" * 1_048_400, "exit_code": 0}
    calls: list[int] = []
    with StateStore(policy) as store:
        registry = ToolRegistry(policy, store)
        registry.register(
            ToolSpec("effect", "Write", EMPTY, log, effect="write"),
            lambda arguments, call: calls.append(1) or data,
        )
        digest = registry.review("effect", {})["digest"]
        first = registry.invoke("effect", {}, approval=digest, idempotency_key="one")
        assert first.status == "succeeded" and first.data == data and not first.truncated
        replay = registry.invoke("effect", {}, approval=digest, idempotency_key="one")
        assert replay.cached and replay.truncated and replay.data is not None
        assert replay.data["exit_code"] == 0 and len(replay.data["log"]) < 1_048_400
        [operation] = store.list_records("tool-operation")
        assert calls == [1] and operation["value"]["state"] == "received"


@pytest.mark.parametrize("size,output_limited", [(13_000, False), (1_200_000, True)])
def test_command_output_over_context_limit_keeps_a_known_receipt(
    tmp_path: Path, size: int, output_limited: bool
) -> None:
    import sys

    from agentic_workbench import CommandConfig, Config

    (tmp_path / "noisy.py").write_text(f"print('x' * {size})\n")
    config = Config(commands={"noisy": CommandConfig((sys.executable, "noisy.py"))})
    policy = WorkspacePolicy(tmp_path, config, grants=Grant(execute=True, trusted_host=True))
    with StateStore(policy) as store:
        registry = ToolRegistry(policy, store)
        registry.register_command("noisy", "noisy", backend="trusted-host")
        digest = registry.review("noisy", {})["digest"]
        first = registry.invoke("noisy", {}, approval=digest, idempotency_key="one")
        # The runner stops a command at its output limit; that is still a known receipt.
        assert first.status == "succeeded" and first.data is not None
        assert first.data["output_limited"] is output_limited
        if not output_limited:
            assert first.data["exit_code"] == 0 and first.data["stdout"] == "x" * size + "\n"
            assert first.data["timed_out"] is False
        [operation] = store.list_records("tool-operation")
        assert operation["value"]["state"] == "received"
    with StateStore(policy) as store:
        registry = ToolRegistry(policy, store)
        registry.register_command("noisy", "noisy", backend="trusted-host")
        replay = registry.invoke("noisy", {}, approval=digest, idempotency_key="one")
        assert replay.cached and replay.truncated is output_limited and replay.data is not None
        assert replay.data["exit_code"] == first.data["exit_code"]
        assert replay.data["output_limited"] is output_limited
        if not output_limited:
            assert replay.data["stdout"] == first.data["stdout"]


def test_json_escaping_past_the_effect_cap_keeps_a_bounded_known_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sys

    from agentic_workbench import CommandConfig, Config, tool_registry

    # Control bytes escape to six JSON bytes each; a small cap stands in for 64 MiB.
    monkeypatch.setattr(tool_registry, "_EFFECT_RESULT_BYTES", 50_000)
    (tmp_path / "noisy.py").write_text("import sys\nsys.stdout.buffer.write(b'\\x01' * 20_000)\n")
    config = Config(commands={"noisy": CommandConfig((sys.executable, "noisy.py"))})
    policy = WorkspacePolicy(tmp_path, config, grants=Grant(execute=True, trusted_host=True))
    with StateStore(policy) as store:
        registry = ToolRegistry(policy, store)
        registry.register_command("noisy", "noisy", backend="trusted-host")
        digest = registry.review("noisy", {})["digest"]
        first = registry.invoke("noisy", {}, approval=digest, idempotency_key="one")
        assert first.status == "succeeded" and first.truncated and first.data is not None
        assert first.data["exit_code"] == 0 and first.data["output_limited"] is False
        replay = registry.invoke("noisy", {}, approval=digest, idempotency_key="one")
        assert replay.cached and replay.truncated and replay.data["exit_code"] == 0
        [operation] = store.list_records("tool-operation")
        assert operation["value"]["state"] == "received"


def test_failures_before_dispatch_report_known_codes_and_leave_the_key_usable(
    tmp_path: Path,
) -> None:
    policy = WorkspacePolicy(tmp_path, grants=Grant(write=True))
    calls: list[int] = []
    with StateStore(policy) as store:

        def slow_loader() -> object:
            time.sleep(0.2)
            return lambda arguments, call: calls.append(1) or {"value": 1}

        def interrupted_loader() -> object:
            raise KeyboardInterrupt

        for key, loader, code in (
            ("slow", slow_loader, "DEADLINE_EXCEEDED"),
            ("interrupted", interrupted_loader, "CONFIG_ERROR"),
        ):
            registry = ToolRegistry(policy, store)
            spec = ToolSpec("effect", "Write", EMPTY, OUTPUT, effect="write", timeout=0.05)
            registry.register_lazy(spec, loader)  # type: ignore[arg-type]
            digest = registry.review("effect", {})["digest"]
            with pytest.raises(WorkbenchError) as raised:
                registry.invoke("effect", {}, approval=digest, idempotency_key=key)
            assert raised.value.code == code
            assert store.list_records("tool-operation") == []
        assert calls == []


def test_stored_receipts_keep_integrity_fields_and_a_useful_prefix(tmp_path: Path) -> None:
    policy = WorkspacePolicy(tmp_path, grants=Grant(write=True))
    cases: dict[str, dict[str, object]] = {
        "cjk": {"stdout": "测" * 600_000, "digest": "a" * 64, "snapshot_hash": "b" * 64},
        "many-keys": {"results": {f"id{i}": "ok" for i in range(80_000)}, "digest": "a" * 64},
    }
    with StateStore(policy) as store:
        for key, data in cases.items():
            registry = ToolRegistry(policy, store)
            registry.register(
                ToolSpec("effect", "Write", EMPTY, {"type": "object"}, effect="write"),
                lambda arguments, call, data=data: data,
            )
            digest = registry.review("effect", {})["digest"]
            assert registry.invoke("effect", {}, approval=digest, idempotency_key=key).data == data
            replay = registry.invoke("effect", {}, approval=digest, idempotency_key=key)
            assert replay.cached and replay.truncated and replay.data is not None
            assert replay.data["digest"] == "a" * 64
            if key == "cjk":
                assert replay.data["snapshot_hash"] == "b" * 64
                assert len(replay.data["stdout"]) > 100_000
            else:
                assert 0 < len(replay.data["results"]) < 80_000


def test_effect_results_over_the_cap_are_validated_whole_then_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agentic_workbench import tool_registry

    monkeypatch.setattr(tool_registry, "_EFFECT_RESULT_BYTES", 50_000)
    schema = {
        "type": "object",
        "properties": {
            "written": {"type": "object"},
            "blob": {"type": "string", "pattern": "^[A-Za-z0-9+/=]*$"},
        },
        "required": ["written", "blob"],
        "additionalProperties": False,
    }
    data = {"written": {f"k{i}": 1 for i in range(10_000)}, "blob": "QUJD" * 20_000}
    policy = WorkspacePolicy(tmp_path, grants=Grant(write=True))
    with StateStore(policy) as store:
        registry = ToolRegistry(policy, store)
        registry.register(
            ToolSpec("effect", "Write", EMPTY, schema, effect="write"),
            lambda arguments, call: data,
        )
        digest = registry.review("effect", {})["digest"]
        first = registry.invoke("effect", {}, approval=digest, idempotency_key="one")
        assert first.status == "succeeded" and first.truncated and first.data is not None
        assert set(first.data) == {"written", "blob"}
        assert registry.invoke("effect", {}, approval=digest, idempotency_key="one").cached
        [operation] = store.list_records("tool-operation")
        assert operation["value"]["state"] == "received"


def test_completed_effects_replay_their_receipt_after_a_cancel(tmp_path: Path) -> None:
    policy = WorkspacePolicy(tmp_path, grants=Grant(write=True))
    with StateStore(policy) as store:
        root = store.create_task("reviewer", "root", {})
        linked = store.create_task("reviewer", "linked", {}, root_id=root)
        calls: list[int] = []
        registry = ToolRegistry(policy, store)
        registry.register(
            ToolSpec("effect", "Write", EMPTY, OUTPUT, effect="write"),
            lambda arguments, call: calls.append(1) or {"value": 1},
        )
        digest = registry.review("effect", {})["digest"]
        for task in (root, linked):
            registry.invoke("effect", {}, approval=digest, idempotency_key=task, task_id=task)
        store.cancel_tree(root)
        for task in (root, linked):
            replay = registry.invoke(
                "effect", {}, approval=digest, idempotency_key=task, task_id=task
            )
            assert replay.cached and replay.status == "succeeded"
        with pytest.raises(WorkbenchError, match="CANCELLED"):
            registry.invoke("effect", {}, approval=digest, idempotency_key="new", task_id=linked)
        assert calls == [1, 1]


class _Aborted(BaseException):
    pass


class _LegacyError(WorkbenchError):
    def __init__(self, message: str) -> None:
        Exception.__init__(self, message)  # skips WorkbenchError.__init__: no code or message


@pytest.mark.parametrize("sink", ["reviewer-base", "reviewer-legacy", "handler-legacy"])
def test_unusual_callback_errors_are_sanitized(tmp_path: Path, sink: str) -> None:
    policy = WorkspacePolicy(tmp_path, redactor=SecretRedactor((MARKER,)))
    with StateStore(policy) as store:
        registry = ToolRegistry(policy, store)
        spec = ToolSpec("probe", "Read probe", EMPTY, OUTPUT, model_visible=True)

        def raise_it(*args: object) -> dict[str, object]:
            if sink == "reviewer-base":
                raise _Aborted("handshake failed with token " + MARKER)
            raise _LegacyError("legacy failure " + MARKER)

        if sink.startswith("reviewer"):
            registry.register(spec, lambda arguments, call: {"value": 1}, reviewer=raise_it)
        else:
            registry.register(spec, raise_it)
        try:
            public = registry.scoped(()).invoke("probe", {}).to_dict()
            chain: list[BaseException] = []
        except WorkbenchError as error:
            public, chain = error.to_dict(), _exception_chain(error)
        assert MARKER not in str(public)
        assert all(MARKER not in str(item) for item in chain)


def test_a_deadline_before_a_retry_keeps_the_known_rejection(tmp_path: Path) -> None:
    policy = WorkspacePolicy(tmp_path, grants=Grant(write=True))
    calls: list[int] = []
    with StateStore(policy) as store:

        def handler(arguments: object, call: object) -> dict[str, object]:
            calls.append(1)
            time.sleep(0.1)
            raise WorkbenchError("TOOL_REJECTED", "Late refusal", retryable=True)

        registry = ToolRegistry(policy, store)
        spec = ToolSpec(
            "effect",
            "Write",
            EMPTY,
            OUTPUT,
            effect="write",
            timeout=0.05,
            retries=1,
            replay_safe=True,
        )
        registry.register(spec, handler)
        digest = registry.review("effect", {})["digest"]
        first = registry.invoke("effect", {}, approval=digest, idempotency_key="one")
        assert first.status == "failed" and first.error is not None
        assert first.error["code"] == "TOOL_REJECTED"
        assert registry.invoke("effect", {}, approval=digest, idempotency_key="one").cached
        [operation] = store.list_records("tool-operation")
        assert calls == [1] and operation["value"]["state"] == "received"


def test_redaction_cannot_break_a_typed_output_schema(tmp_path: Path) -> None:
    schema = {
        "type": "object",
        "properties": {"user_id": {"type": "string"}, "has_password": {"type": "boolean"}},
        "required": ["user_id", "has_password"],
        "additionalProperties": False,
    }
    policy = WorkspacePolicy(tmp_path, grants=Grant(write=True))
    calls: list[int] = []
    with StateStore(policy) as store:
        registry = ToolRegistry(policy, store)
        registry.register(
            ToolSpec("create_user", "Create a user", EMPTY, schema, effect="write"),
            lambda arguments, call: calls.append(1) or {"user_id": "u1", "has_password": False},
        )
        digest = registry.review("create_user", {})["digest"]
        first = registry.invoke("create_user", {}, approval=digest, idempotency_key="one")
        assert first.status == "succeeded"
        assert registry.invoke("create_user", {}, approval=digest, idempotency_key="one").cached
        assert calls == [1]


def test_a_deeply_nested_effect_result_keeps_a_known_receipt(tmp_path: Path) -> None:
    nested: dict[str, object] = {"leaf": 1}
    for _ in range(1_500):
        nested = {"next": nested}
    policy = WorkspacePolicy(tmp_path, grants=Grant(write=True))
    calls: list[int] = []
    with StateStore(policy) as store:
        registry = ToolRegistry(policy, store)
        registry.register(
            ToolSpec("effect", "Write", EMPTY, {"type": "object"}, effect="write"),
            lambda arguments, call: calls.append(1) or nested,
        )
        digest = registry.review("effect", {})["digest"]
        first = registry.invoke("effect", {}, approval=digest, idempotency_key="one")
        assert first.status == "succeeded" and first.truncated
        assert registry.invoke("effect", {}, approval=digest, idempotency_key="one").cached
        assert calls == [1]
