# Agent harness audit — 14 October 2026

This audit precedes the harness implementation. It covers the working tree, including the 26 staged files present at task start; those changes are preserved. Existing specifications remain compatibility and security constraints. The current request authorizes the additions below, with host-controlled authority retained.

## Verified baseline

The locked dependency set has two core dependencies (JSON Schema and pathspec), an optional official OpenAI SDK, and development tools. Python owns execution and policy; TypeScript is a bounded subprocess adapter. All source modules, tests, specifications, bundled skills, examples, packaging scripts and CI were inspected directly or in three independent scoped audits.

In a fresh locked environment at `/tmp/agentic-harness-dev`, Python 3.14 ran **300 tests successfully**, with 7 environment-specific tests deselected and 87% statement coverage. Ruff lint, format, and strict mypy passed. Node protocol tests passed (9). The pre-existing `.venv` failed package imports even after editable reinstall; the fresh environment avoids that local installation fault. Python 3.14 reported existing unclosed SQLite connections in tests; this is recorded rather than suppressed. Baseline Docker/live provider/clean distribution checks have not yet run.

## Findings and implementation direction

| System | Existing infrastructure | Gap and resulting change |
|---|---|---|
| Tools | Six closed read tools, schema validation, source policy, redaction, separate approved Docker/host runner; read/review MCP server | Add typed host registry, lazy trusted loading, output contracts, structured receipts, bounded replay-safe retries, durable idempotency and effect approvals. Provide repository, Python, named CLI, MCP and API bindings without importing repository code automatically. |
| Models | Provider/embedding Protocols, actual OpenAI Responses SDK transport, durable request reservations/intents/receipts, bounded explicit 429 retries and unknown-outcome stop | Add capability routing over host-registered adapters, safe fallback only after known rejection, configured pricing, token/cost admission and latency records. Preserve fixed OpenAI endpoint and explicit destination grants for alternatives. |
| Context | Bounded index, Python AST traces, lexical/vector retrieval, source-hash citations, workspace memory | Replace fixed top-two excerpts with budget-aware selection and deterministic compression; retain decisions with provenance, retrieve relevant memory, reject stale decisions. Validate symbol tool freshness; avoid repeatedly reading a file for every chunk. |
| Guardrails | No-follow path confinement, secret filtering, exact-content apply/test/rollback approvals, sanitized isolated snapshots, journals, root request limits | Preserve these controls and apply them to extensions, resource accounting and loop actions. Repository/skill/model text remains data and cannot supply tool registrations, approval or grants. |
| Loops | Durable task state, leases, DAG validation, at most two specialists, dependency context, resume and unknown-effect recovery | Add a persisted Plan → Execute → Observe → Verify → Reflect controller with bounded replanning, repeated-failure detection, cancellation, checkpoints and verifier-controlled completion. Reuse role tasks and existing change/runner boundaries. |
| Developer experience | CLI, SDK, Node bridge, original configurable skills, schemas, packages, traces | Expose new controls through the SDK and compatible CLI/Node operations; document host extension examples and operating limits. |
| Validation | Extensive unit/security/recovery/integration tests and source-targeting benchmark | Add harness boundary tests and end-to-end verification/recovery evaluation; report actual tokens, configured costs, latency and task outcomes separately from source-targeting scores. |

## Architecture and dependency direction

The existing contracts → policy → index/state/skills/provider → agents → interfaces layering remains. Tool registrations and routed providers are supplied by trusted SDK code. The context manager consumes index/state/policy. The execution controller consumes the existing agent, proposal and runner services and persists its checkpoint in the same scoped store. It does not receive permission to approve actions. Public v1 AgentResult and CLI envelopes remain compatible.

The intended outcome is a local execution framework with bounded autonomous analysis and explicit privileged-operation checkpoints. Distributed multi-tenant scheduling, automatic credential setup, hosted deployment, remote publishing and paid acceptance are outside this task. These deployment limits do not justify skipping implementation or offline verification.
