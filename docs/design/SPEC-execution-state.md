# Specification: execution-state

Depends on `core-contracts` and `workspace-policy`.

## Objective and contract

Persist resumable execution, scoped memory, index snapshots, proposal metadata and audit events in local SQLite. The application-owned `.agentic/` directory is private where OS permissions support it and excluded from source indexing. Connections use parameterized SQL, explicit transactions compatible with Python 3.11, WAL, busy timeouts and bounded payloads. SQLite is appropriate for a local owner-controlled tool, not a distributed multi-tenant service.

`StateStore` owns task creation/claiming, transition validation, append-only event sequence numbers, bounded result storage, memory namespaces and projection persistence. Task states: pending, running, awaiting_approval, succeeded, failed, cancelled and interrupted. A failed or interrupted task resumes only by explicit host action, preserving completed steps and refusing to replay unknown external effects.

Each task pins the workspace identity, configuration/policy fingerprint, agent contracts and exact selected skill hashes. Memory is namespaced by workspace and purpose (`source`, `episodic`, `workflow`); results from one workspace are unavailable to another. Memory is retained context, not model training. No automatic promotion of inferred preferences or modification of active skills.

Record external intent before dispatch and record actual receipt/usage after success. A crash/timeout between those points produces OUTCOME_UNKNOWN and blocks automatic replay. Claims/transitions and root-task budget reservations use compare-and-set semantics in a database transaction, including concurrent child agents. Expired worker ownership is marked interrupted, not taken as evidence that an external action failed.

Configurable retention defaults to 30 days for task content and derived memory/index caches. Active tasks and pending recovery journals are protected from pruning. Backup expiry is separately documented; rollback availability is reported accurately. Explicit cleanup/export APIs operate only on application-owned state and never delete repository source.

## Structure and style

Own `state.py` and `tests/test_state.py`. Store schema migrations as ordered application-owned SQL statements with a schema version. Example: `store.transition(task_id, expected="running", new="awaiting_approval")`. State consumers must not concatenate SQL or read raw state as source context.

## Commands and verification

`uv run --locked pytest tests/test_state.py`. Exercise process restart, duplicate task claims, concurrent events, stale transitions, namespace isolation, retention, old schema handling and unknown external receipts.

## Success criteria

- Task history survives restart and concurrent claims never duplicate one step.
- Workspace/skill/configuration drift blocks unsafe resume; completed and unknown external steps are not silently replayed.
- Secret filtering, scoped retrieval, migration and retention tests pass without deleting active recovery evidence.

## Boundaries and open questions

Always record real transitions and evidence. Ask before breaking schema migrations or automatic retention changes. Never claim that a local SQLite audit log is tamper-proof against its OS owner or provides multi-user authentication.
