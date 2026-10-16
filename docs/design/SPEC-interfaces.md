# Specification: interfaces

Depends on `agent-runtime`.

## Objective and contract

Expose a coherent CLI, Python SDK and small Node/TypeScript adapter. Install the `agentic` executable through `[project.scripts]`; use argparse rather than an additional CLI framework. `--root` identifies the workspace; `--json` emits exactly one v1 envelope on stdout, while sanitized structured logs use stderr. CLI exit codes: 0 success/dry-run, 1 execution/provider failure, 2 invalid input/configuration, 3 policy/approval/staleness/conflict, 4 missing backend or optional integration.

Required commands:

- `agentic init --root PATH`: create only application-owned configuration/state; preserve existing configuration and fail on conflicting/invalid files. No source rewrites.
- `agentic scan --root PATH --json`: bounded read-only inventory and cited static report; persist private index/task state.
- `agentic explain TARGET --root PATH --json`: static source explanation by default; `--provider openai --model NAME --allow-network` explicitly opts into LLM processing of that workspace's permitted context.
- `agentic plan INSTRUCTION --root PATH --json`: orchestrated static plan by default; configured LLM mode may produce validated reviewable proposals. Importing a reviewed structured proposal through `--proposal-file PATH` validates it without applying source changes.
- `agentic apply [PROPOSAL_ID | --rollback CHANGE_ID] --root PATH --dry-run --json`: review by default; source mutation requires the exact current `--approve DIGEST`.
- `agentic test --root PATH --command-id NAME --dry-run --json`: review the detected/configured command and snapshot; execution requires `--approve DIGEST` and explicit backend. `--trusted-host` is a separate opt-in; it never activates as a fallback.

Supporting `run`, `status`, `resume`, `search` and `state` subcommands expose independent agents, durable execution, lexical/semantic retrieval, and explicit application-state export/pruning. These exist to expose requested capabilities; there is no remote account, GUI, telemetry collector or deployment command.

Developer distribution refinement: OpenAI-capable commands accept optional `--prompt-key` for hidden interactive input. Require a TTY, explicit network grant, allowed endpoint, configured OpenAI provider/model and installed optional SDK before collecting a key. Semantic search requires its embedding model. Refuse echo fallback, empty/multiline credentials and lexical-only search. Keep the credential in this command's process environment only, redact its exact value and restore the prior value in all exit paths. Existing noninteractive environment injection remains supported. Stdout retains one v1 envelope and key entry never grants write/execute authority.

Python SDK: `Workbench(root, config=None, grants=None, provider=None)` exposes init, scan, explain, plan, run_agent, orchestrate, task_status, resume, search, propose, review/apply/rollback and test review/execution methods. Explicit host grants and approval callbacks remain outside model-visible tools.

The installed SDK publishes its inline types through a packaged PEP 561 `py.typed` marker. Consumer acceptance runs outside the checkout against a clean installed wheel, proving both a valid SDK use and rejection of an incorrect result annotation. The disposable SDK walkthrough demonstrates read-only review by default and explicit trusted-host testing/apply/rollback on an owned synthetic fixture with `--execute`.

The TypeScript adapter spawns the installed CLI with fixed command names and argument arrays, `shell:false`, an output limit and timeout. It validates v1 envelopes and throws a typed AgenticError. Credential environment names are forwarded only for an explicit provider invocation, never included in request JSON or logs. Its documented async API covers the six required commands and supporting operations without implementing a second policy engine.

## Structure and style

Own `cli.py`, `sdk.py`, `__init__.py`, `adapters/node/src/index.ts` and interface tests. Public SDK imports are documented; CLI parsing, business logic and process wrappers remain separate. Version and JSON contract tests protect consumers.

## Commands and verification

`uv run --locked pytest tests/test_cli.py tests/test_sdk.py`; in `adapters/node`: `npm ci --ignore-scripts`, `npm run build`, `npm test`. Clean-wheel tests call installed `agentic` from outside the repository; Node integration points to that executable.

## Success criteria

- All six commands work through the installed package against disposable examples, with accurate JSON/error/exit behavior.
- SDK calls use the same guards/results as CLI calls; TypeScript integration exercises actual subprocess results rather than mocked feature completion.
- Existing projects/configuration are preserved; invalid envelopes, command injection, process timeouts and excessive output are handled safely.

## Boundaries and open questions

Always preserve stable documented interfaces and explicit approval semantics. Ask before adding remote publication or changing JSON/exit contracts. Never forward arbitrary shell commands, auto-install repository dependencies or print credentials.
