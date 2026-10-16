# Specification: core-contracts

Depends on no other module. Traces to the capability map.

## Objective and contract

Provide the shared, typed boundary for tasks, evidence, results, errors, configuration and events. Python 3.11+ is the minimum. Public SDK exports use dataclasses and Protocols; untrusted JSON uses closed JSON Schemas validated with `jsonschema`. UTC timestamps use RFC 3339. IDs are opaque UUIDs; hashes are lowercase SHA-256. Public JSON names are snake_case and have `schema_version: 1`.

`TaskRequest` carries kind, instruction, declared workspace and explicit host permissions. `AgentResult` carries task_id, agent, mode (`static` or `llm`), summary, evidence, findings, recommendations, proposal_ids, limitations and usage. An evidence reference contains a workspace-relative path, line bounds and source hash. Findings distinguish observed facts, inferences and unknowns; static heuristics are never represented as validated vulnerabilities.

`WorkbenchError` has code, safe message and retryability; the CLI serializes the same error envelope. Stable codes include CONFIG_ERROR, VALIDATION_ERROR, POLICY_DENIED, APPROVAL_REQUIRED, STALE_APPROVAL, CONFLICT, LIMIT_EXCEEDED, PROVIDER_REFUSED, PROVIDER_ERROR, OUTCOME_UNKNOWN and SANDBOX_UNAVAILABLE. Unknown JSON fields and non-finite numeric values fail validation.

Configuration is TOML with a schema version, scan limits, provider/model selection, permission reductions, named test commands, skill directories and retention settings. Credentials are environment-variable names, never values. Defaults deny provider network, source mutation and command execution. Project configuration may reduce permissions; only explicit CLI/SDK host grants can enable privileged operations.

## Structure and style

Own `src/agentic_workbench/models.py`, `errors.py`, `config.py`, `observability.py` and `schemas/`. Consumer modules import these contracts without importing their consumers. Example style:

```python
@dataclass(frozen=True)
class Evidence:
    path: str
    start_line: int
    end_line: int
    source_hash: str
```

Structured stderr events contain task/agent/tool identifiers, event type, elapsed time, status, source hashes and known usage. Prompts, source bodies, credential values, raw provider errors and approval authority are excluded. Redaction is applied before any event serialization; logging failure must not authorize work.

## Commands and verification

After implementation: `uv run --locked pytest tests/test_contracts.py tests/test_config.py tests/test_observability.py`; `uv run --locked ruff check src tests`; `uv run --locked mypy src`.

## Success criteria

- SDK objects and CLI envelopes validate against packaged schemas, including error paths and future-version rejection.
- Invalid configuration, inline secrets, arbitrary credential destinations and privileged configuration without host grants are rejected.
- Known secret values and secret-bearing exceptions never appear in captured logs or JSON outputs; budgets and schema bounds reject invalid values.

## Boundaries and open questions

Always validate configuration and external results. Ask before changing public schema behavior, provider scope or privilege grants. Never store credential values in configuration or events. Approval of this specification establishes the initial v1 contract; later breaking changes require a new compatibility decision.
