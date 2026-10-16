"""Private, workspace-scoped execution state with explicit recovery boundaries."""

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import stat
import weakref
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import Any
from uuid import uuid4

from .errors import WorkbenchError
from .models import canonical_hash, canonical_json
from .policy import WorkspacePolicy

_MAX_PAYLOAD = 1_048_576
_ACTIVE = {"pending", "running", "awaiting_approval"}
_TRANSITIONS = {
    "pending": {"running", "failed", "cancelled"},
    "running": {"awaiting_approval", "succeeded", "failed", "cancelled", "interrupted"},
    "awaiting_approval": {"running", "failed", "cancelled", "interrupted"},
    "succeeded": set(),
    "failed": {"cancelled"},
    "cancelled": set(),
    "interrupted": {"cancelled"},
}
_EVENT_FIELDS = {
    "agent",
    "tool",
    "status",
    "elapsed_ms",
    "input_tokens",
    "output_tokens",
    "requests",
    "unknown_receipts",
    "source_hash",
    "error_code",
    "root_id",
    "parent_id",
    "owner",
    "intent_id",
    "cost_microusd",
    "from",
    "to",
}
_MIGRATIONS = (
    (
        "CREATE TABLE tasks (id TEXT PRIMARY KEY, workspace TEXT NOT NULL, "
        "root_id TEXT NOT NULL, parent_id TEXT REFERENCES tasks(id), agent TEXT NOT NULL, "
        "instruction TEXT NOT NULL, pins TEXT NOT NULL, state TEXT NOT NULL, owner TEXT, "
        "heartbeat_at TEXT, result TEXT, error TEXT, created_at TEXT NOT NULL, "
        "updated_at TEXT NOT NULL)",
        "CREATE INDEX tasks_workspace_root ON tasks(workspace, root_id)",
        "CREATE TABLE events (sequence INTEGER PRIMARY KEY AUTOINCREMENT, "
        "task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE, name TEXT NOT NULL, "
        "metadata TEXT NOT NULL, created_at TEXT NOT NULL)",
        "CREATE TABLE memory (workspace TEXT NOT NULL, namespace TEXT NOT NULL, key TEXT NOT NULL, "
        "value TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY(workspace, namespace, key))",
        "CREATE TABLE records (workspace TEXT NOT NULL, kind TEXT NOT NULL, id TEXT NOT NULL, "
        "value TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, "
        "PRIMARY KEY(workspace, kind, id))",
        "CREATE TABLE budgets (root_id TEXT PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE, "
        "maximum INTEGER NOT NULL, reserved INTEGER NOT NULL)",
    ),
    (
        "CREATE TABLE intents (id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id) "
        "ON DELETE CASCADE, state TEXT NOT NULL, usage TEXT, created_at TEXT NOT NULL, "
        "updated_at TEXT NOT NULL)",
        "CREATE INDEX intents_task ON intents(task_id)",
    ),
    (
        "ALTER TABLE intents ADD COLUMN kind TEXT NOT NULL DEFAULT 'external'",
        "ALTER TABLE intents ADD COLUMN metadata TEXT",
    ),
)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def _cutoff(*, days: int = 0, seconds: int = 0) -> str:
    return (datetime.now(UTC) - timedelta(days=days, seconds=seconds)).isoformat(
        timespec="microseconds"
    )


class StateStore:
    """Host API, not a model tool. Windows privacy relies on the owner's directory ACL."""

    def __init__(self, policy: WorkspacePolicy) -> None:
        self.policy = policy
        self._lock = RLock()
        self._closed = False
        self.path = policy.prepare_state_dir() / "state.sqlite3"
        self._directory_identity = self.path.parent.stat().st_dev, self.path.parent.stat().st_ino
        self._connection: sqlite3.Connection
        try:
            if os.name == "posix":
                with policy.directory((".agentic",)) as directory:
                    fd = os.open(
                        "state.sqlite3",
                        os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                        0o600,
                        dir_fd=directory,
                    )
            else:
                # Windows is owner-controlled local state; guarded source writes remain POSIX-only.
                if self.path.parent.resolve() != self.path.parent or self.path.is_symlink():
                    raise WorkbenchError("POLICY_DENIED", "State aliases are prohibited")
                if self.path.exists():
                    self._private_file(self.path.lstat())
                fd = os.open(
                    self.path,
                    os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0),
                    0o600,
                )
            try:
                info = os.fstat(fd)
                self._file_identity = info.st_dev, info.st_ino
                self._private_file(info)
            finally:
                os.close(fd)
            self._check_storage()
            self._connection = sqlite3.connect(
                self.path, timeout=5, isolation_level=None, check_same_thread=False
            )
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA busy_timeout = 5000")
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute("PRAGMA journal_mode = WAL")
            self._connection.execute("PRAGMA synchronous = FULL")
            self._migrate()
            self._finalizer = weakref.finalize(self, self._connection.close)
        except (OSError, sqlite3.Error) as error:
            if hasattr(self, "_connection"):
                self._connection.close()
            raise WorkbenchError("STATE_ERROR", "Cannot open private execution state") from error
        except WorkbenchError:
            if hasattr(self, "_connection"):
                self._connection.close()
            raise

    @staticmethod
    def _private_file(info: os.stat_result) -> None:
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or os.name == "posix"
            and (info.st_uid != os.geteuid() or info.st_mode & 0o077)
        ):
            raise WorkbenchError("POLICY_DENIED", "State files must be private and unaliased")

    def _check_storage(self) -> None:
        self.policy._check_root()
        try:
            directory = self.path.parent.lstat()
            if (
                not stat.S_ISDIR(directory.st_mode)
                or (directory.st_dev, directory.st_ino) != self._directory_identity
                or self.path.parent.resolve() != self.path.parent
                or os.name == "posix"
                and (directory.st_uid != os.geteuid() or directory.st_mode & 0o077)
            ):
                raise WorkbenchError("POLICY_DENIED", "State directory identity changed")
            info = self.path.lstat()
            self._private_file(info)
            if self.path.resolve() != self.path:
                raise WorkbenchError("POLICY_DENIED", "State file alias detected")
            if (info.st_dev, info.st_ino) != self._file_identity:
                raise WorkbenchError("CONFLICT", "State file identity changed")
            for suffix in ("-wal", "-shm", "-journal"):
                try:
                    self._private_file(self.path.with_name(self.path.name + suffix).lstat())
                except FileNotFoundError:
                    pass
        except OSError as error:
            raise WorkbenchError(
                "POLICY_DENIED", "Unsafe or unavailable execution state"
            ) from error

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            if self._closed:
                raise WorkbenchError("STATE_ERROR", "Execution state is closed")
            self._check_storage()
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                yield self._connection
                self._check_storage()
                self._connection.commit()
            except Exception as error:
                self._connection.rollback()
                if isinstance(error, sqlite3.Error):
                    raise WorkbenchError(
                        "STATE_ERROR", "Execution state operation failed"
                    ) from error
                raise

    def _migrate(self) -> None:
        with self._transaction() as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version > len(_MIGRATIONS):
                raise WorkbenchError("CONFIG_ERROR", "Unsupported execution state schema version")
            if (
                version == 0
                and connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' "
                    "AND name NOT LIKE 'sqlite_%'"
                ).fetchone()
            ):
                raise WorkbenchError(
                    "CONFIG_ERROR", "Unversioned state requires explicit migration"
                )
            for number, statements in enumerate(_MIGRATIONS, 1):
                if number > version:
                    for statement in statements:
                        connection.execute(statement)
                    # Migration numbers are application-owned constants, never external SQL.
                    connection.execute(f"PRAGMA user_version = {number}")

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._connection.close()
                self._closed = True
                self._finalizer.detach()

    def __enter__(self) -> StateStore:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _label(self, value: str) -> str:
        if (
            not isinstance(value, str)
            or not 1 <= len(value) <= 256
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
        ):
            raise WorkbenchError("VALIDATION_ERROR", "Invalid state identifier")
        if self.policy.redactor.contains_secret(value):
            raise WorkbenchError("POLICY_DENIED", "State identifiers cannot contain credentials")
        return value

    def _payload(self, value: Any, maximum: int = _MAX_PAYLOAD) -> str:
        raw = canonical_json(value)
        if len(raw.encode()) > maximum:
            raise WorkbenchError("LIMIT_EXCEEDED", "State payload exceeds byte limit")
        cleaned = canonical_json(self.policy.redactor.clean(value))
        if len(cleaned.encode()) > maximum:
            raise WorkbenchError("LIMIT_EXCEEDED", "Sanitized state payload exceeds byte limit")
        return cleaned

    def _read(self, value: str | None) -> Any:
        return None if value is None else self.policy.redactor.clean(json.loads(value))

    def _pins(self, pins: dict[str, Any]) -> str:
        if not isinstance(pins, dict):
            raise WorkbenchError("VALIDATION_ERROR", "Task pins require an object")
        required = {
            "workspace_id": self.policy.workspace_id,
            "policy_fingerprint": self.policy.fingerprint,
        }
        if any(key in pins and pins[key] != value for key, value in required.items()):
            raise WorkbenchError("CONFLICT", "Task workspace or policy pins changed")
        return self._payload({**pins, **required})

    def _task(self, connection: sqlite3.Connection, task_id: str) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM tasks WHERE id = ? AND workspace = ?",
            (self._label(task_id), self.policy.workspace_id),
        ).fetchone()
        if row is None:
            raise WorkbenchError("VALIDATION_ERROR", "Task is unavailable in this workspace")
        assert isinstance(row, sqlite3.Row)
        return row

    def _task_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        for key in ("pins", "result", "error", "instruction"):
            data[key] = self._read(data[key])
        return self.policy.redactor.clean(data)  # type: ignore[no-any-return]

    def _event(
        self, connection: sqlite3.Connection, task_id: str, name: str, metadata: dict[str, Any]
    ) -> int:
        if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_.-]{0,63}", name):
            raise WorkbenchError("VALIDATION_ERROR", "Invalid state event name")
        if not isinstance(metadata, dict) or set(metadata) - _EVENT_FIELDS:
            raise WorkbenchError("VALIDATION_ERROR", "State events accept known metadata only")
        if any(
            value is not None
            and (
                type(value) not in (str, int, float) or isinstance(value, str) and len(value) > 256
            )
            for value in metadata.values()
        ):
            raise WorkbenchError("VALIDATION_ERROR", "State event metadata must be bounded scalars")
        cursor = connection.execute(
            "INSERT INTO events(task_id, name, metadata, created_at) VALUES (?, ?, ?, ?)",
            (task_id, name, self._payload(metadata, 16_384), _now()),
        )
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    def event(self, task_id: str, name: str, metadata: dict[str, Any]) -> int:
        with self._transaction() as connection:
            self._task(connection, task_id)
            return self._event(connection, task_id, name, metadata)

    def create_task(
        self,
        agent: str,
        instruction: str,
        pins: dict[str, Any],
        root_id: str | None = None,
        parent_id: str | None = None,
    ) -> str:
        agent = self._label(agent)
        if not isinstance(instruction, str) or not instruction.strip():
            raise WorkbenchError("VALIDATION_ERROR", "Task instruction requires text")
        instruction_json, pinned = self._payload(instruction), self._pins(pins)
        task_id, timestamp = str(uuid4()), _now()
        with self._transaction() as connection:
            anchor: sqlite3.Row | None = None
            if parent_id is not None:
                anchor = self._task(connection, parent_id)
                if root_id is not None and root_id != anchor["root_id"]:
                    raise WorkbenchError("CONFLICT", "Child task root does not match its parent")
                root_id = anchor["root_id"]
            if root_id is not None:
                root = self._task(connection, root_id)
                if root["root_id"] != root_id or root["parent_id"] is not None:
                    raise WorkbenchError("VALIDATION_ERROR", "Root task must identify a root")
                anchor = anchor or root
            if anchor is not None and self._cancelled(connection, anchor):
                raise WorkbenchError("CANCELLED", "A cancelled task tree accepts no new tasks")
            root_id = root_id or task_id
            connection.execute(
                "INSERT INTO tasks(id, workspace, root_id, parent_id, agent, instruction, pins, "
                "state, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)",
                (
                    task_id,
                    self.policy.workspace_id,
                    root_id,
                    parent_id,
                    agent,
                    instruction_json,
                    pinned,
                    timestamp,
                    timestamp,
                ),
            )
            self._event(connection, task_id, "task.created", {"agent": agent, "root_id": root_id})
        return task_id

    def get_task(self, task_id: str) -> dict[str, Any]:
        with self._transaction() as connection:
            return self._task_dict(self._task(connection, task_id))

    def _cancelled(self, connection: sqlite3.Connection, task: sqlite3.Row) -> bool:
        # The task, any ancestor, or its root (linked tasks may reach it without a parent).
        workspace = self.policy.workspace_id
        row = connection.execute(
            "WITH RECURSIVE ancestry(id, parent_id, state) AS (SELECT id, parent_id, state "
            "FROM tasks WHERE id = ? AND workspace = ? UNION ALL SELECT tasks.id, "
            "tasks.parent_id, tasks.state FROM tasks "
            "JOIN ancestry ON tasks.id = ancestry.parent_id "
            "WHERE tasks.workspace = ?) SELECT 1 FROM ancestry WHERE state = 'cancelled' "
            "UNION ALL SELECT 1 FROM tasks WHERE id = ? AND workspace = ? AND state = 'cancelled' "
            "LIMIT 1",
            (task["id"], workspace, workspace, task["root_id"], workspace),
        ).fetchone()
        return row is not None

    def cancelled(self, task_id: str) -> bool:
        """Dispatch gate: a task is cancelled when it or its root is."""
        with self._transaction() as connection:
            return self._cancelled(connection, self._task(connection, task_id))

    def claim(self, task_id: str, owner: str) -> bool:
        owner, timestamp = self._label(owner), _now()
        with self._transaction() as connection:
            self._task(connection, task_id)
            changed = connection.execute(
                "UPDATE tasks SET state = 'running', owner = ?, heartbeat_at = ?, updated_at = ? "
                "WHERE id = ? AND workspace = ? AND state = 'pending' AND owner IS NULL",
                (owner, timestamp, timestamp, task_id, self.policy.workspace_id),
            ).rowcount
            if changed:
                self._event(connection, task_id, "task.claimed", {"owner": owner})
            return bool(changed)

    def transition(
        self, task_id: str, expected: str, new: str, result: Any = None, error: Any = None
    ) -> None:
        if (
            not isinstance(expected, str)
            or not isinstance(new, str)
            or expected not in _TRANSITIONS
            or new not in _TRANSITIONS[expected]
        ):
            raise WorkbenchError("VALIDATION_ERROR", "Invalid task transition")
        result_json = None if result is None else self._payload(result)
        error_json = None if error is None else self._payload(error)
        with self._transaction() as connection:
            task = self._task(connection, task_id)
            if (
                new == "succeeded"
                and connection.execute(
                    "SELECT 1 FROM intents JOIN tasks ON tasks.id = intents.task_id "
                    "WHERE tasks.workspace = ? AND intents.state != 'received' "
                    "AND (tasks.id = ? OR (? = ? AND tasks.root_id = ?))",
                    (
                        self.policy.workspace_id,
                        task_id,
                        task_id,
                        task["root_id"],
                        task_id,
                    ),
                ).fetchone()
            ):
                raise WorkbenchError("OUTCOME_UNKNOWN", "External intent has no known receipt")
            changed = connection.execute(
                "UPDATE tasks SET state = ?, result = COALESCE(?, result), "
                "error = COALESCE(?, error), owner = NULL, heartbeat_at = NULL, updated_at = ? "
                "WHERE id = ? AND workspace = ? AND state = ?",
                (new, result_json, error_json, _now(), task_id, self.policy.workspace_id, expected),
            ).rowcount
            if not changed:
                raise WorkbenchError("CONFLICT", "Task state changed before transition")
            self._event(connection, task_id, "task.transitioned", {"from": expected, "to": new})

    def cancel_tree(self, task_id: str) -> list[str]:
        """Cooperative cancellation: active descendants stop dispatch at their next boundary."""
        with self._transaction() as connection:
            self._task(connection, task_id)
            # A root's tree includes tasks linked by root_id without a parent.
            rows = connection.execute(
                "WITH RECURSIVE subtree(id) AS (SELECT id FROM tasks "
                "WHERE (id = ? OR root_id = ?) AND workspace = ? "
                "UNION SELECT tasks.id FROM tasks JOIN subtree ON tasks.parent_id = subtree.id "
                "WHERE tasks.workspace = ?) SELECT tasks.id, tasks.state FROM tasks "
                "JOIN subtree ON tasks.id = subtree.id ORDER BY tasks.id",
                (task_id, task_id, self.policy.workspace_id, self.policy.workspace_id),
            ).fetchall()
            cancelled = []
            for task in rows:
                if task["state"] not in _ACTIVE | {"failed", "interrupted"}:
                    continue
                connection.execute(
                    "UPDATE tasks SET state = 'cancelled', owner = NULL, heartbeat_at = NULL, "
                    "updated_at = ? WHERE id = ?",
                    (_now(), task["id"]),
                )
                self._event(
                    connection,
                    task["id"],
                    "task.transitioned",
                    {"from": task["state"], "to": "cancelled"},
                )
                cancelled.append(task["id"])
            return cancelled

    def task_events(self, task_id: str, limit: int = 10_000) -> list[dict[str, Any]]:
        if type(limit) is not int or not 1 <= limit <= 10_000:
            raise WorkbenchError("VALIDATION_ERROR", "Invalid task trace limit")
        with self._transaction() as connection:
            self._task(connection, task_id)
            # Same tree as cancel_tree and resume: a root also owns tasks linked by root_id.
            rows = connection.execute(
                "WITH RECURSIVE subtree(id) AS (SELECT id FROM tasks "
                "WHERE (id = ? OR root_id = ?) AND workspace = ? "
                "UNION SELECT tasks.id FROM tasks JOIN subtree ON tasks.parent_id = subtree.id "
                "WHERE tasks.workspace = ?) SELECT events.* FROM events "
                "JOIN subtree ON events.task_id = subtree.id ORDER BY sequence DESC LIMIT ?",
                (task_id, task_id, self.policy.workspace_id, self.policy.workspace_id, limit),
            ).fetchall()
            return [
                {**dict(row), "metadata": self._read(row["metadata"])} for row in reversed(rows)
            ]

    def resume(self, task_id: str, pins: dict[str, Any]) -> dict[str, Any]:
        """Explicit host request; it never reclaims a running worker automatically."""
        pinned = self._pins(pins)
        with self._transaction() as connection:
            task = self._task(connection, task_id)
            if task["pins"] != pinned:
                raise WorkbenchError("CONFLICT", "Task configuration, contracts or skills changed")
            if task["state"] not in {"failed", "interrupted", "awaiting_approval"}:
                raise WorkbenchError("CONFLICT", "Only suspended tasks may resume")
            if connection.execute(
                "SELECT 1 FROM intents JOIN tasks ON tasks.id = intents.task_id "
                "WHERE tasks.root_id = ? AND tasks.workspace = ? AND intents.state != 'received'",
                (task["root_id"], self.policy.workspace_id),
            ).fetchone():
                raise WorkbenchError(
                    "OUTCOME_UNKNOWN", "Root task has an unresolved external intent"
                )
            connection.execute(
                "UPDATE tasks SET state = 'pending', owner = NULL, heartbeat_at = NULL, "
                "updated_at = ? WHERE id = ?",
                (_now(), task_id),
            )
            self._event(
                connection, task_id, "task.resumed", {"from": task["state"], "to": "pending"}
            )
            return self._task_dict(self._task(connection, task_id))

    def heartbeat(self, task_id: str, owner: str) -> None:
        with self._transaction() as connection:
            self._task(connection, task_id)
            if not connection.execute(
                "UPDATE tasks SET heartbeat_at = ? WHERE id = ? "
                "AND state = 'running' AND owner = ?",
                (_now(), task_id, self._label(owner)),
            ).rowcount:
                raise WorkbenchError("CONFLICT", "Worker no longer owns the running task")

    def interrupt_expired(self, max_age_seconds: int) -> list[str]:
        if type(max_age_seconds) is not int or not 1 <= max_age_seconds <= 86_400:
            raise WorkbenchError("VALIDATION_ERROR", "Invalid worker expiry interval")
        with self._transaction() as connection:
            rows = connection.execute(
                "SELECT id FROM tasks WHERE workspace = ? AND state = 'running' "
                "AND heartbeat_at < ?",
                (self.policy.workspace_id, _cutoff(seconds=max_age_seconds)),
            ).fetchall()
            for row in rows:
                connection.execute(
                    "UPDATE tasks SET state = 'interrupted', owner = NULL, heartbeat_at = NULL, "
                    "updated_at = ? WHERE id = ?",
                    (_now(), row["id"]),
                )
                self._event(
                    connection, row["id"], "task.interrupted", {"error_code": "WORKER_EXPIRED"}
                )
            return [row["id"] for row in rows]

    def reserve(self, root_id: str, maximum: int) -> None:
        if (
            type(maximum) is not int
            or not 1 <= maximum <= self.policy.config.limits.provider_requests
        ):
            raise WorkbenchError("VALIDATION_ERROR", "Invalid root provider request maximum")
        with self._transaction() as connection:
            task = self._task(connection, root_id)
            if task["state"] == "cancelled":
                raise WorkbenchError("CANCELLED", "Root task was cancelled")
            if task["root_id"] != root_id:
                raise WorkbenchError("VALIDATION_ERROR", "Budget belongs to the root task")
            connection.execute(
                "INSERT INTO budgets(root_id, maximum, reserved) VALUES (?, ?, 0) "
                "ON CONFLICT(root_id) DO NOTHING",
                (root_id, maximum),
            )
            ledger = connection.execute(
                "SELECT maximum FROM budgets WHERE root_id = ?", (root_id,)
            ).fetchone()
            if ledger["maximum"] != maximum:
                raise WorkbenchError("CONFLICT", "Root provider budget maximum changed")
            if not connection.execute(
                "UPDATE budgets SET reserved = reserved + 1 "
                "WHERE root_id = ? AND reserved < maximum",
                (root_id,),
            ).rowcount:
                raise WorkbenchError("LIMIT_EXCEEDED", "Root provider request budget is exhausted")
            self._event(connection, root_id, "provider.reserved", {"requests": 1})

    def _record(
        self, connection: sqlite3.Connection, kind: str, record_id: str
    ) -> dict[str, Any] | None:
        row = connection.execute(
            "SELECT value FROM records WHERE workspace = ? AND kind = ? AND id = ?",
            (self.policy.workspace_id, kind, record_id),
        ).fetchone()
        return None if row is None else self._read(row["value"])

    def _write_record(
        self, connection: sqlite3.Connection, kind: str, record_id: str, value: dict[str, Any]
    ) -> None:
        timestamp = _now()
        connection.execute(
            "INSERT INTO records(workspace, kind, id, value, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(workspace, kind, id) DO UPDATE SET "
            "value = excluded.value, updated_at = excluded.updated_at",
            (
                self.policy.workspace_id,
                kind,
                record_id,
                self._payload(value),
                timestamp,
                timestamp,
            ),
        )

    def reserve_resources(
        self,
        root_id: str,
        tokens: int,
        cost_microusd: int,
        maximum_tokens: int,
        maximum_cost_microusd: int,
        *,
        pricing_known: bool = True,
    ) -> str:
        """Atomic root admission; unresolved reservations remain charged across restart."""
        values = (tokens, cost_microusd, maximum_tokens, maximum_cost_microusd)
        if any(type(value) is not int or not 0 <= value <= 2**63 - 1 for value in values):
            raise WorkbenchError("VALIDATION_ERROR", "Invalid model resource budget")
        if type(pricing_known) is not bool:
            raise WorkbenchError("VALIDATION_ERROR", "Invalid model pricing status")
        reservation = str(uuid4())
        with self._transaction() as connection:
            task = self._task(connection, root_id)
            if task["state"] == "cancelled":
                raise WorkbenchError("CANCELLED", "Root task was cancelled")
            if task["root_id"] != root_id:
                raise WorkbenchError("VALIDATION_ERROR", "Resources belong to the root task")
            ledger = self._record(connection, "resource-budget", root_id) or {
                "task_id": root_id,
                "maximum_tokens": maximum_tokens,
                "maximum_cost_microusd": maximum_cost_microusd,
                "tokens": 0,
                "cost_microusd": 0,
                "cost_known": True,
                "state": "known",
            }
            if ledger["state"] == "unknown":
                raise WorkbenchError("OUTCOME_UNKNOWN", "Uncertain model outcome blocks dispatch")
            if (ledger["maximum_tokens"], ledger["maximum_cost_microusd"]) != (
                maximum_tokens,
                maximum_cost_microusd,
            ):
                raise WorkbenchError("CONFLICT", "Root model resource limits changed")
            if (
                ledger["tokens"] + tokens > maximum_tokens
                or ledger["cost_microusd"] + cost_microusd > maximum_cost_microusd
            ):
                raise WorkbenchError("LIMIT_EXCEEDED", "Root model token or cost budget exhausted")
            ledger["tokens"] += tokens
            ledger["cost_microusd"] += cost_microusd
            ledger["cost_known"] = ledger.get("cost_known", True) and pricing_known
            self._write_record(connection, "resource-budget", root_id, ledger)
            self._write_record(
                connection,
                "resource-reservation",
                reservation,
                {
                    "task_id": root_id,
                    "state": "pending",
                    "tokens": tokens,
                    "cost_microusd": cost_microusd,
                },
            )
            self._event(
                connection,
                root_id,
                "model.reserved",
                {"input_tokens": tokens, "cost_microusd": cost_microusd},
            )
        return reservation

    def settle_resources(self, reservation_id: str, tokens: int, cost_microusd: int) -> None:
        if any(
            type(value) is not int or not 0 <= value <= 2**63 - 1
            for value in (tokens, cost_microusd)
        ):
            raise WorkbenchError("VALIDATION_ERROR", "Invalid model resource receipt")
        with self._transaction() as connection:
            reservation = self._record(
                connection, "resource-reservation", self._label(reservation_id)
            )
            if reservation is None or reservation["state"] != "pending":
                raise WorkbenchError("CONFLICT", "Model resource reservation cannot be settled")
            if tokens > reservation["tokens"] or cost_microusd > reservation["cost_microusd"]:
                raise WorkbenchError(
                    "LIMIT_EXCEEDED", "Adapter exceeded its registered resource bounds"
                )
            ledger = self._record(connection, "resource-budget", reservation["task_id"])
            assert ledger is not None
            ledger["tokens"] -= reservation["tokens"] - tokens
            ledger["cost_microusd"] -= reservation["cost_microusd"] - cost_microusd
            reservation.update(state="settled", tokens=tokens, cost_microusd=cost_microusd)
            self._write_record(connection, "resource-budget", reservation["task_id"], ledger)
            self._write_record(connection, "resource-reservation", reservation_id, reservation)

    def unknown_resources(self, reservation_id: str) -> None:
        with self._transaction() as connection:
            reservation = self._record(
                connection, "resource-reservation", self._label(reservation_id)
            )
            if reservation is None or reservation["state"] != "pending":
                raise WorkbenchError("CONFLICT", "Model resource reservation is unavailable")
            ledger = self._record(connection, "resource-budget", reservation["task_id"])
            assert ledger is not None
            reservation["state"] = ledger["state"] = "unknown"
            self._write_record(connection, "resource-budget", reservation["task_id"], ledger)
            self._write_record(connection, "resource-reservation", reservation_id, reservation)

    def resource_usage(self, root_id: str) -> dict[str, Any] | None:
        with self._transaction() as connection:
            self._task(connection, root_id)
            return self._record(connection, "resource-budget", root_id)

    def reserve_tool_call(self, root_id: str, maximum: int = 128) -> None:
        if type(maximum) is not int or not 1 <= maximum <= 100_000:
            raise WorkbenchError("VALIDATION_ERROR", "Invalid tool call budget")
        with self._transaction() as connection:
            task = self._task(connection, root_id)
            if task["state"] == "cancelled":
                raise WorkbenchError("CANCELLED", "Root task was cancelled")
            if task["root_id"] != root_id:
                raise WorkbenchError("VALIDATION_ERROR", "Tool budget belongs to the root task")
            ledger = self._record(connection, "tool-budget", root_id) or {
                "task_id": root_id,
                "maximum": maximum,
                "reserved": 0,
            }
            if ledger["maximum"] != maximum:
                raise WorkbenchError("CONFLICT", "Root tool call maximum changed")
            if ledger["reserved"] >= maximum:
                raise WorkbenchError("LIMIT_EXCEEDED", "Root tool call budget exhausted")
            ledger["reserved"] += 1
            self._write_record(connection, "tool-budget", root_id, ledger)

    def begin_operation(self, kind: str, key: str, fingerprint: str) -> dict[str, Any] | None:
        """Claim a durable operation exactly once; existing unresolved work is never replayed."""
        kind, key = self._label(kind), self._label(key)
        if not isinstance(fingerprint, str) or not re.fullmatch(r"[a-f0-9]{64}", fingerprint):
            raise WorkbenchError("VALIDATION_ERROR", "Invalid operation fingerprint")
        with self._transaction() as connection:
            previous = self._record(connection, kind, key)
            if previous is not None:
                if previous.get("fingerprint") != fingerprint:
                    raise WorkbenchError("CONFLICT", "Idempotency key identifies different work")
                return previous
            self._write_record(
                connection, kind, key, {"fingerprint": fingerprint, "state": "pending"}
            )
        return None

    def finish_operation(
        self, kind: str, key: str, fingerprint: str, result: dict[str, Any]
    ) -> None:
        self._finish_operation(kind, key, fingerprint, "received", result)

    @staticmethod
    def _fingerprint(fingerprint: str) -> None:
        if not isinstance(fingerprint, str) or not re.fullmatch(r"[a-f0-9]{64}", fingerprint):
            raise WorkbenchError("VALIDATION_ERROR", "Invalid operation fingerprint")

    def operation(self, kind: str, key: str) -> dict[str, Any] | None:
        kind, key = self._label(kind), self._label(key)
        with self._transaction() as connection:
            return self._record(connection, kind, key)

    def release_operation(self, kind: str, key: str, fingerprint: str) -> None:
        """Drop a pending claim when nothing was dispatched, so its key can run later."""
        self._fingerprint(fingerprint)
        kind, key = self._label(kind), self._label(key)
        with self._transaction() as connection:
            previous = self._record(connection, kind, key)
            if (
                previous is None
                or previous.get("fingerprint") != fingerprint
                or previous["state"] != "pending"
            ):
                raise WorkbenchError("CONFLICT", "Operation claim is unavailable or changed")
            connection.execute(
                "DELETE FROM records WHERE workspace = ? AND kind = ? AND id = ?",
                (self.policy.workspace_id, kind, key),
            )

    def mark_operation_unknown(self, kind: str, key: str, fingerprint: str) -> None:
        self._finish_operation(kind, key, fingerprint, "unknown", None)

    def _finish_operation(
        self,
        kind: str,
        key: str,
        fingerprint: str,
        state: str,
        result: dict[str, Any] | None,
    ) -> None:
        self._fingerprint(fingerprint)
        kind, key = self._label(kind), self._label(key)
        with self._transaction() as connection:
            previous = self._record(connection, kind, key)
            if previous is None or previous.get("fingerprint") != fingerprint:
                raise WorkbenchError("CONFLICT", "Operation claim is unavailable or changed")
            if previous["state"] != "pending":
                raise WorkbenchError("CONFLICT", "Operation outcome is already recorded")
            previous.update(state=state, result=result)
            self._write_record(connection, kind, key, previous)

    def intent(
        self, task_id: str, kind: str = "external", metadata: dict[str, Any] | None = None
    ) -> str:
        kind = self._label(kind)
        metadata = metadata or {}
        if set(metadata) - {"model", "payload_hash", "bytes"}:
            raise WorkbenchError("VALIDATION_ERROR", "Invalid external intent metadata")
        if "model" in metadata:
            self._label(metadata["model"])
        if "payload_hash" in metadata and (
            not isinstance(metadata["payload_hash"], str)
            or not re.fullmatch(r"[a-f0-9]{64}", metadata["payload_hash"])
        ):
            raise WorkbenchError("VALIDATION_ERROR", "Invalid external payload hash")
        if "bytes" in metadata and (
            type(metadata["bytes"]) is not int
            or not 0 <= metadata["bytes"] <= self.policy.config.limits.context_bytes
        ):
            raise WorkbenchError("VALIDATION_ERROR", "Invalid external payload byte count")
        payload = self._payload(metadata, 16_384)
        intent_id, timestamp = str(uuid4()), _now()
        with self._transaction() as connection:
            # Every external dispatch records an intent first, so this denies all of them.
            if self._cancelled(connection, self._task(connection, task_id)):
                raise WorkbenchError("CANCELLED", "Task was cancelled before dispatch")
            connection.execute(
                "INSERT INTO intents(id, task_id, state, created_at, updated_at, kind, metadata) "
                "VALUES (?, ?, 'pending', ?, ?, ?, ?)",
                (intent_id, task_id, timestamp, timestamp, kind, payload),
            )
            self._event(connection, task_id, "external.intent", {"intent_id": intent_id})
        return intent_id

    def _intent(self, connection: sqlite3.Connection, intent_id: str) -> sqlite3.Row:
        row = connection.execute(
            "SELECT intents.* FROM intents JOIN tasks ON tasks.id = intents.task_id "
            "WHERE intents.id = ? AND tasks.workspace = ?",
            (self._label(intent_id), self.policy.workspace_id),
        ).fetchone()
        if row is None:
            raise WorkbenchError("VALIDATION_ERROR", "External intent is unavailable")
        assert isinstance(row, sqlite3.Row)
        return row

    def _receipt_payload(self, usage: dict[str, Any]) -> str:
        allowed = {
            "requests",
            "input_tokens",
            "output_tokens",
            "unknown_receipts",
            "estimated_cost_usd",
        }
        identifiers = {"status", "request_id", "response_id", "provider_model"}
        if not isinstance(usage, dict) or set(usage) - (allowed | identifiers | {"http_status"}):
            raise WorkbenchError("VALIDATION_ERROR", "Invalid external usage receipt")
        for key, value in usage.items():
            if value is None:
                continue
            if key in identifiers:
                if not isinstance(value, str) or len(value) > 512:
                    raise WorkbenchError("VALIDATION_ERROR", "Invalid external receipt identifier")
            elif key == "http_status":
                if type(value) is not int or not 100 <= value <= 599:
                    raise WorkbenchError("VALIDATION_ERROR", "Invalid HTTP receipt status")
            elif key == "estimated_cost_usd":
                if (
                    type(value) not in (int, float)
                    or not 0 <= value <= 1_000_000_000_000
                    or not math.isfinite(value)
                ):
                    raise WorkbenchError("VALIDATION_ERROR", "Invalid external usage value")
            elif type(value) is not int or not 0 <= value <= 2**63 - 1:
                raise WorkbenchError("VALIDATION_ERROR", "Invalid external usage count")
        if usage.get("unknown_receipts", 0) not in (0, None):
            raise WorkbenchError(
                "VALIDATION_ERROR", "Known receipts cannot report unknown outcomes"
            )
        return self._payload(usage)

    def _record_receipt(self, connection: sqlite3.Connection, intent_id: str, payload: str) -> None:
        row = self._intent(connection, intent_id)
        if row["state"] == "received":
            raise WorkbenchError("CONFLICT", "External receipt is already recorded")
        connection.execute(
            "UPDATE intents SET state = 'received', usage = ?, updated_at = ? WHERE id = ?",
            (payload, _now(), intent_id),
        )
        self._event(connection, row["task_id"], "external.received", {"intent_id": intent_id})

    def receipt(self, intent_id: str, usage: dict[str, Any]) -> None:
        payload = self._receipt_payload(usage)
        with self._transaction() as connection:
            self._record_receipt(connection, intent_id, payload)

    def execution_checkpoint(
        self,
        task_id: str,
        owner: str,
        value: dict[str, Any],
        intent_id: str | None = None,
        receipt: dict[str, Any] | None = None,
    ) -> None:
        """Commit a step observation and its receipt together while the worker owns the task."""
        if not isinstance(value, dict) or value.get("task_id") != task_id:
            raise WorkbenchError("VALIDATION_ERROR", "Execution checkpoint task mismatch")
        if (intent_id is None) != (receipt is None):
            raise WorkbenchError("VALIDATION_ERROR", "Checkpoint receipt requires an intent")
        payload = None if receipt is None else self._receipt_payload(receipt)
        with self._transaction() as connection:
            task = self._task(connection, task_id)
            if task["state"] != "running" or task["owner"] != self._label(owner):
                raise WorkbenchError("CONFLICT", "Worker does not own the running task")
            if intent_id is not None:
                if self._intent(connection, intent_id)["task_id"] != task_id:
                    raise WorkbenchError("CONFLICT", "Checkpoint intent belongs to another task")
                assert payload is not None
                self._record_receipt(connection, intent_id, payload)
            self._write_record(connection, "execution", task_id, value)

    def unknown(self, intent_id: str) -> None:
        with self._transaction() as connection:
            row = self._intent(connection, intent_id)
            if row["state"] == "received":
                raise WorkbenchError("CONFLICT", "Known receipt cannot become unknown")
            connection.execute(
                "UPDATE intents SET state = 'unknown', updated_at = ? WHERE id = ?",
                (_now(), intent_id),
            )
            self._event(connection, row["task_id"], "external.unknown", {"intent_id": intent_id})

    def _namespace(self, namespace: str) -> str:
        if not isinstance(namespace, str) or namespace not in {"source", "episodic", "workflow"}:
            raise WorkbenchError("VALIDATION_ERROR", "Unknown memory purpose")
        return namespace

    def put_memory(self, namespace: str, key: str, value: Any) -> None:
        namespace, key, payload = self._namespace(namespace), self._label(key), self._payload(value)
        with self._transaction() as connection:
            connection.execute(
                "INSERT INTO memory(workspace, namespace, key, value, updated_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(workspace, namespace, key) DO UPDATE SET value = excluded.value, "
                "updated_at = excluded.updated_at",
                (self.policy.workspace_id, namespace, key, payload, _now()),
            )

    def get_memory(self, namespace: str, key: str) -> Any:
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT value FROM memory WHERE workspace = ? AND namespace = ? AND key = ?",
                (self.policy.workspace_id, self._namespace(namespace), self._label(key)),
            ).fetchone()
            return None if row is None else self._read(row["value"])

    def save(self, kind: str, record_id: str, value: Any) -> None:
        kind, record_id, payload = self._label(kind), self._label(record_id), self._payload(value)
        with self._transaction() as connection:
            if connection.execute(
                "SELECT 1 FROM records WHERE workspace = ? AND kind = ? AND id = ?",
                (self.policy.workspace_id, kind, record_id),
            ).fetchone():
                raise WorkbenchError("CONFLICT", "Saved state record is immutable")
            connection.execute(
                "INSERT INTO records(workspace, kind, id, value, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (self.policy.workspace_id, kind, record_id, payload, _now(), _now()),
            )

    def update(self, kind: str, record_id: str, value: Any) -> None:
        if not isinstance(kind, str) or kind not in {
            "journal",
            "container",
            "index",
            "execution",
            "execution-review",
        }:
            raise WorkbenchError("POLICY_DENIED", "This saved state kind is immutable")
        with self._transaction() as connection:
            if not connection.execute(
                "UPDATE records SET value = ?, updated_at = ? "
                "WHERE workspace = ? AND kind = ? AND id = ?",
                (
                    self._payload(value),
                    _now(),
                    self.policy.workspace_id,
                    kind,
                    self._label(record_id),
                ),
            ).rowcount:
                raise WorkbenchError("VALIDATION_ERROR", "Saved state record is unavailable")

    def load(self, kind: str, record_id: str) -> Any:
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT value FROM records WHERE workspace = ? AND kind = ? AND id = ?",
                (self.policy.workspace_id, self._label(kind), self._label(record_id)),
            ).fetchone()
            return None if row is None else self._read(row["value"])

    def list_records(self, kind: str) -> list[dict[str, Any]]:
        with self._transaction() as connection:
            rows = connection.execute(
                "SELECT id, kind, value, created_at, updated_at FROM records "
                "WHERE workspace = ? AND kind = ? ORDER BY created_at, id",
                (self.policy.workspace_id, self._label(kind)),
            ).fetchall()
            return [{**dict(row), "value": self._read(row["value"])} for row in rows]

    def export(self) -> dict[str, Any]:
        with self._transaction() as connection:
            workspace = (self.policy.workspace_id,)
            result: dict[str, Any] = {"schema_version": 1, "workspace_id": self.policy.workspace_id}
            result["tasks"] = [
                self._task_dict(row)
                for row in connection.execute(
                    "SELECT * FROM tasks WHERE workspace = ? ORDER BY created_at, id", workspace
                )
            ]
            queries = {
                "events": "SELECT events.* FROM events JOIN tasks ON tasks.id = events.task_id "
                "WHERE tasks.workspace = ? ORDER BY events.sequence",
                "intents": "SELECT intents.* FROM intents JOIN tasks ON tasks.id = intents.task_id "
                "WHERE tasks.workspace = ? ORDER BY intents.created_at, intents.id",
                "budgets": "SELECT budgets.* FROM budgets JOIN tasks ON tasks.id = budgets.root_id "
                "WHERE tasks.workspace = ? ORDER BY budgets.root_id",
            }
            for table, query in queries.items():
                rows = connection.execute(
                    query,
                    workspace,
                ).fetchall()
                result[table] = [dict(row) for row in rows]
                for row in result[table]:
                    for key in ("metadata", "usage"):
                        if key in row:
                            row[key] = self._read(row[key])
            queries = {
                "memory": "SELECT * FROM memory WHERE workspace = ? ORDER BY namespace, key",
                "records": "SELECT * FROM records WHERE workspace = ? ORDER BY kind, id",
            }
            for table, query in queries.items():
                result[table] = [dict(row) for row in connection.execute(query, workspace)]
                for row in result[table]:
                    row["value"] = self._read(row["value"])
            self._payload(result, self.policy.config.scan.max_total_bytes)
            return self.policy.redactor.clean(result)  # type: ignore[no-any-return]

    def _review_prune(self, connection: sqlite3.Connection, days: int) -> dict[str, Any]:
        if type(days) is not int or not 1 <= days <= 3650:
            raise WorkbenchError("VALIDATION_ERROR", "Invalid state retention interval")
        cutoff, backup_cutoff = (
            _cutoff(days=days),
            _cutoff(days=self.policy.config.state.backup_retention_days),
        )
        tasks = connection.execute(
            "SELECT id, root_id, state, updated_at FROM tasks WHERE workspace = ?",
            (self.policy.workspace_id,),
        ).fetchall()
        protected_roots = {row["root_id"] for row in tasks if row["state"] in _ACTIVE}
        protected_roots.update(
            row[0]
            for row in connection.execute(
                "SELECT tasks.root_id FROM intents JOIN tasks ON tasks.id = intents.task_id "
                "WHERE tasks.workspace = ? AND intents.state != 'received'",
                (self.policy.workspace_id,),
            )
        )
        records: list[dict[str, Any]] = []
        task_roots = {task["id"]: task["root_id"] for task in tasks}
        task_states = {task["id"]: task["state"] for task in tasks}
        record_roots: dict[tuple[str, str], str | None] = {}
        for row in connection.execute(
            "SELECT kind, id, value, updated_at FROM records WHERE workspace = ?",
            (self.policy.workspace_id,),
        ):
            value = self._read(row["value"])
            state = value.get("state") if isinstance(value, dict) else None
            if row["kind"] in {
                "execution",
                "execution-review",
                "resource-budget",
                "resource-reservation",
                "tool-budget",
            } and isinstance(value, dict):
                record_roots[row["kind"], row["id"]] = task_roots.get(value.get("task_id"))
            protected = (
                row["kind"] == "journal"
                and (
                    state not in {"applied", "rolled_back"}
                    or state == "applied"
                    and row["updated_at"] >= backup_cutoff
                )
                or row["kind"] == "container"
                and state != "cleaned"
                or row["kind"] == "tool-operation"
                and state != "received"
                or row["kind"] == "execution"
                and isinstance(value, dict)
                and task_states.get(value.get("task_id")) in _ACTIVE
                or row["kind"] == "resource-reservation"
                and state != "settled"
                or row["kind"] == "resource-budget"
                and state == "unknown"
                or row["kind"] in {"resource-budget", "resource-reservation", "tool-budget"}
                and isinstance(value, dict)
                and task_roots.get(value.get("task_id")) in protected_roots
            )
            if protected:
                if isinstance(value, dict) and value.get("task_id"):
                    protected_roots.update(
                        task["root_id"] for task in tasks if task["id"] == value["task_id"]
                    )
            elif row["updated_at"] < cutoff:
                records.append(
                    {"kind": row["kind"], "id": row["id"], "updated_at": row["updated_at"]}
                )
        # Keep an entire task tree while any descendant needs execution or recovery.
        recent_roots = {row["root_id"] for row in tasks if row["updated_at"] >= cutoff}
        task_ids = sorted(
            row["id"] for row in tasks if row["root_id"] not in protected_roots | recent_roots
        )
        retained_roots = protected_roots | recent_roots
        records = [
            row
            for row in records
            if record_roots.get((row["kind"], row["id"])) not in retained_roots
        ]
        memory = [
            dict(row)
            for row in connection.execute(
                "SELECT namespace, key, updated_at FROM memory "
                "WHERE workspace = ? AND updated_at < ? "
                "ORDER BY namespace, key",
                (self.policy.workspace_id, cutoff),
            )
        ]
        review = {
            "workspace_id": self.policy.workspace_id,
            "days": days,
            "tasks": task_ids,
            "records": sorted(records, key=lambda row: (row["kind"], row["id"])),
            "memory": memory,
        }
        pruned_ids = set(task_ids)
        review["events"] = [
            row["sequence"]
            for row in connection.execute(
                "SELECT events.sequence, events.task_id FROM events JOIN tasks "
                "ON tasks.id = events.task_id WHERE tasks.workspace = ? ORDER BY events.sequence",
                (self.policy.workspace_id,),
            )
            if row["task_id"] in pruned_ids
        ]
        review["intents"] = [
            {"id": row["id"], "updated_at": row["updated_at"]}
            for row in connection.execute(
                "SELECT intents.id, intents.task_id, intents.updated_at FROM intents JOIN tasks "
                "ON tasks.id = intents.task_id WHERE tasks.workspace = ? ORDER BY intents.id",
                (self.policy.workspace_id,),
            )
            if row["task_id"] in pruned_ids
        ]
        review["budgets"] = [
            dict(row)
            for row in connection.execute(
                "SELECT budgets.* FROM budgets JOIN tasks ON tasks.id = budgets.root_id "
                "WHERE tasks.workspace = ? ORDER BY budgets.root_id",
                (self.policy.workspace_id,),
            )
            if row["root_id"] in pruned_ids
        ]
        return {**review, "digest": canonical_hash(review)}

    def review_prune(self, days: int) -> dict[str, Any]:
        with self._transaction() as connection:
            return self._review_prune(connection, days)

    def prune(self, digest: str, days: int) -> dict[str, Any]:
        with self._transaction() as connection:
            review = self._review_prune(connection, days)
            if digest != review["digest"]:
                raise WorkbenchError("STALE_APPROVAL", "State cleanup review changed")
            for task_id in review["tasks"]:
                # Detach only reviewed links before deleting the entire inactive task tree.
                connection.execute("UPDATE tasks SET parent_id = NULL WHERE id = ?", (task_id,))
            for task_id in review["tasks"]:
                connection.execute(
                    "DELETE FROM tasks WHERE id = ? AND workspace = ?",
                    (task_id, self.policy.workspace_id),
                )
            for record in review["records"]:
                connection.execute(
                    "DELETE FROM records WHERE workspace = ? AND kind = ? AND id = ?",
                    (self.policy.workspace_id, record["kind"], record["id"]),
                )
            for memory in review["memory"]:
                connection.execute(
                    "DELETE FROM memory WHERE workspace = ? AND namespace = ? AND key = ?",
                    (self.policy.workspace_id, memory["namespace"], memory["key"]),
                )
            return review
