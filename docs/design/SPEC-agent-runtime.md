# Specification: agent-runtime

Depends on `repository-index`, `execution-state`, `skill-registry`, `provider-runtime` and `change-workflow`.

## Objective and contract

Provide eight independently callable agents and an orchestrator. Public roles: discovery, intelligence, engineering, architecture, ux, testing, documentation and orchestrator. Each receives the shared TaskRequest, bounded cited context, selected immutable skills and a permission-scoped tool executor. It returns the same validated AgentResult contract.

Static mode produces real source-derived analysis: inventory/manifests, Python symbols/direct call relationships, framework evidence, documented uncertainty, UI-source checks and detected test-command recommendations. It is identified as static analysis. LLM mode augments that evidence through a configured provider and explicit network grant; neither mode fabricates runtime traces, test runs, security validation or applied changes.

Read tools include repository_summary, read_source, search_code and lookup_memory. Validate arguments, recheck source hashes and redact before returning context. Proposal output routes through change-workflow and is not application. The model has no approve, apply, rollback, shell, network-fetch, credential-read or command-execution tool.

The orchestrator executes an explicit acyclic task graph of at most 32 nodes with dependency outputs. Default planning flow: discovery → intelligence/architecture/UX as applicable → engineering plan → testing/documentation recommendations. Relevant analysis nodes can run concurrently with a configurable maximum of 2 and share one atomic root-task provider budget; mutation and approved test execution remain serialized per workspace. Persist real step states/results and bounded evidence references; do not rerun completed or unknown-effect steps after restart.

The testing agent uses a host-approved runner separate from the LLM tool loop. Default execution backend is Docker with a pre-existing digest-pinned approved image, `--pull=never`, network disabled, non-root identity, read-only root filesystem, dropped capabilities, no-new-privileges, resource/PID limits, bounded tmpfs and only a sanitized disposable source snapshot mounted read-only. Never mount the original repository, state, credentials or Docker socket. Snapshot preparation obeys source policy.

Resolve and validate a local Docker daemon endpoint and trusted executable before review; bind both to the approval fingerprint and recheck before execution. Remote Docker endpoints are unsupported by default. Assign a unique owned container identifier/label, record it durably, and clean up that exact container after timeout, output overflow or interruption; never remove unrelated containers. Shell strings and shell-interpreter command forms are rejected. Snapshot/configuration changes invalidate execution approval.

Trusted-host execution is an explicit weaker mode, requires the exact command/snapshot/backend approval and uses a sanitized temporary copy/environment, argument arrays, process-group timeout and bounded output. It is not an OS sandbox. Backend unavailability never causes automatic fallback. Test outcomes include the actual command fingerprint, snapshot hash, backend, exit code, timeout/output-limit flags and sanitized output.

## Structure and style

Own `agents.py`, `orchestrator.py`, `tools.py`, `runner.py` and focused tests. Keep orchestration policy deterministic; the provider proposes content but cannot modify the task graph's authority. Agents share core mechanics rather than eight duplicate tool loops.

## Commands and verification

`uv run --locked pytest tests/test_agents.py tests/test_orchestrator.py tests/test_tools.py tests/test_runner.py`; real Docker integration: `uv run --locked pytest -m docker tests/integration/test_sandbox.py` with an explicitly supplied pinned image. Test dependency ordering, parallel read coordination, restart, role skills, malicious source/tool requests and real example command outcomes.

## Success criteria

- All eight roles operate independently and in a persisted coordinated workflow; static/LLM/execution evidence is accurately separated.
- Tool policy survives hostile retrieval/model output, limits and task interruption; evidence remains source-bound.
- Approved example tests execute in the chosen backend; denied/unavailable execution stays denied; Docker integration demonstrates restricted network/filesystem access and bounded failures.

## Boundaries and open questions

Always distinguish recommendation, proposal, approval, application and verification. Ask before running repository code or changing isolation grants. Never claim static UX checks replace visual/browser QA, source analysis proves exploitability, or Docker isolation removes host/kernel risk.
