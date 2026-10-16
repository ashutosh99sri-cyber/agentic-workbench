# Changelog

## 0.1.1 — prepared 2026-10-17

Patch candidate; registry publication remains a separate authorized action.
See the [candidate record](docs/releases/0.1.1.md).

### Fixed

- Handle the macOS exited-process-group race: after `EPERM`, wait for the owned
  parent within five seconds, then retry group termination. Persistent denial or
  a live-parent timeout still fails. Runner and TypeScript use the same helper;
  stdio MCP cleanup now reuses it too. Retain unconditional final cleanup.
- Use a concise registry README with absolute links for Python package metadata,
  and align the Node package/lockfile and candidate instructions at 0.1.1.

### Security and compatibility

- No dependency, approval schema, grant, executable-ownership check, source-write
  policy, Docker isolation flag or credential-handling change. A denied group
  signal is no longer ignored solely because the parent has exited.
- Keep the immutable 0.1.0 tag and registry artifacts. The historical PDF and
  source-provenance ledger retain their original scope; this patch changes two
  runtime files and is verified against its own candidate source.

## 0.1.0 — 2026-10-17

First versioned developer-preview release. Registry publication is tracked separately
from the source tag; see [release notes](docs/releases/0.1.0.md).

### Added

- Installable Python CLI/SDK with eight specialist roles, ten packaged skills, source
  evidence, retrieval, bounded repair and persistent orchestration.
- Public-ready Node adapter metadata and explicit package file allowlists; both
  distributions carry Apache-2.0 license and applicable notices.
- Clean npm archive consumer acceptance against the installed Python CLI.

### Security

- Preserve offline defaults, host grants, exact source/change/command approvals,
  bounded tools, secret redaction and recoverable apply/rollback.
- Retain protected-main CI gates and read-only release verification. Release
  validation rejects mismatched Python/Node versions and private registry settings.

### Compatibility and limits

- Python 3.11–3.14; Node 24+. Guarded writes and Runner execution require POSIX;
  Windows support covers the documented read-only subset.
- Optional model requests require operator configuration and network grants. Live
  model effectiveness and heavy-task production suitability remain unmeasured.

## Pre-release development history (retained)

## Unreleased - context selection

- Restore complete changed-definition coverage when fresh body chunks and direct
  callers/checks fit six citations; preserve query-only ranking, source boundaries
  and final context byte limits. Add Python and native TypeScript regressions.

- Preserve modest definition/check bodies and prioritize actual calls and target
  behavior before import headers and lower-specificity lexical detail.

- Share compact, relationship-aware local retrieval between search and agent
  context; balance definitions, terminal behavior, callers and checks.
- Preserve selected declaration IDs before relation limits and avoid name-wide
  trace work on the retrieval path.
- Reserve early context capacity while retaining complete serialized byte bounds,
  current-source checks, redaction, indexed candidate validation and all approvals.
- Add explicit versioned evaluation-metadata isolation without changing the frozen
  task manifest or default dataset. Add independent selection and packing regressions.

## Unreleased

Reduced repeated local work without changing public SDK contracts: internal contract
validation uses private packaged schemas with fresh validators, immutable chunks reuse
their existing content digest, and model tool descriptors copy only their exposed input
schemas. Benchmark token totals now retain unknown/partial usage as `null`. No runtime
dependency was added. [AI Hero research and measured results](docs/aihero-review.md)
records the source review, rejected additions and bounded local measurements.


Integrated the developer-distribution branch into the canonical runtime: typed SDK
consumer checks, lazy optional-provider imports, the offline SDK walkthrough and
`--prompt-key` now ship together with repair, indexing and the engineering harness.
The hidden key prompt supports combined retrieval and the current provider commands;
it restores the prior environment after success, failure or interruption. CI verifies
installed typing and the walkthrough. Tool cancellation now stops before lazy loading,
and provider fallback requires a rejection receipt for the latest dispatch intent.


Fixed the Node adapter's package allowlist so stale or backup build files cannot
enter the npm archive. A regression stages extra output files and checks the
actual `npm pack` file list.

Added tested MCP/editor and trusted callback-provider integration recipes, including
explicit source disclosure, offline defaults, exact approval boundaries and a supplied
candidate Python repair control. CI now selects immutable source commits, runs pinned
Node/Python Docker acceptance automatically and verifies clean wheel/sdist consumers.
Release packaging depends on the complete acceptance workflow and records source,
test and artifact hashes. Added maintainer/support guidance, issue/PR intake and
inactive owner examples. Local receipts do not establish hosted CI or public release
approval; no remote or registry publication is configured.

Added bounded Python repair (`agentic repair`, `Workbench.repair`; see [Python repair](docs/python-repair.md)). It reproduces a failing configured command, then tries up to four provider candidates. Each candidate is limited to the source files you list, and is applied and checked only with its exact approval. The workflow completes only when the same command passes on the current source; model text never completes it. Unusable baselines, including exits 125–127, stop before any provider request. Durable receipts and write-once facts let a repair pause for approval, close, and continue without repeating work.

Final review fixes: secret recognition is linear, idempotent and merged across configured values, assignments and token patterns, recognises SECRET_KEY, JWT, Bearer, Go `:=`, typed and subscript forms, passphrases under prefixed names and truncated private key copies in any line format, and no longer flags type hints, variable copies, `${VAR}` references, pagination cursors, model special tokens or sentences under message names such as `no_token`; tool receipts keep integrity fields, validate before redaction or bounding, replay after cancellation, and stay known for large, escaped, deeply nested, typed API, MCP and command results; cancellation reaches every ancestor and linked task and releases undispatched claims; the execution harness (contract 4) binds dependencies by identity and an immutable result digest rather than step ID or compacted evidence, reuses effects only from the current or previous plan round (including steps a replan preserves), bounds oversized observations and checkpoints, and returns completed results under any contract; scans survive parser stack overflow and deep call chains; read tools fit after redaction; the MCP server survives undecodable frames; Wrangler `.dev.vars.<env>` files are protected.

Fixed release-blocking safety and reliability defects: `.envrc`/`.env-*` files are protected and prefixed secret names (`STRIPE_WEBHOOK_SECRET=`) are redacted; tool error messages are redacted and bounded; cancelled tasks and roots cannot record new external intents and tool retries stop after a cancel; large effect results keep their durable receipt; replans recompute steps whose dependencies changed; routing never falls back on a rejection its receipt contradicts; malformed MCP tool names return invalid params; deeply nested Python calls and the file limit no longer cut scans short; `repository_summary` returns a bounded whole-entry prefix; the CLI closes its store on an invalid override; and the wheel ships `py.typed`.

Added the experimental engineering harness: typed trusted-host tool registrations with lazy loading, input/output validation, exact effect approvals and durable idempotency; approved Python/CLI Runner bindings, bounded MCP stdio and fixed HTTPS API transports; capability-aware model routing with known-rejection-only fallback, shared durable token/cost admission and latency traces; measured context compression, source-bound decision lifecycle and per-chunk vector reuse; persisted verification-gated loops with replanning, cancellation and crash recovery. Readiness-based specialists support distinct node instructions. CLI/SDK/Node expose execution, cancellation, traces and discovery. Added offline real-command repair/recovery evaluation and adversarial harness tests. Existing staged work and v1 contracts are preserved.

Static intelligence, engineering and testing results trace named Python symbols through definitions, call sites, callees and test references. New `list_symbols` and `trace_symbol` read tools with per-tool descriptions; bundled engineering, intelligence, testing and python-engineering skills 1.1.0 request them, and the engineering skill carries a minimal-change decision ladder with worked examples. `agentic mcp` serves read-only and review tools over MCP stdio with the standard library. `scripts/benchmark.py` and `tests/test_benchmark.py` score static or provider output on the example projects.


### Security

- Detect and redact unquoted named credential assignments before source reaches agents or backups. Ambiguous bare identifiers are conservatively masked.
- Enforce each selected skill's requested read-tool scope, including an explicitly empty scope.
- Reject factual findings without source citations before recording successful agent results.

### Fixed

- Preserve bounded citations, findings, limitations and task identities between coordinated agents, with explicit truncation indicators.
- Honor nested Git ignore reinclusions while retaining mandatory protected-path exclusions.
- Distinguish actual image alt attributes from data-alt and respect HTML/JSX attribute casing in static UX checks.
- Bind manual release verification to the exact version-tag commit, include the tested Node archive, and add Python 3.13 to the authored CI matrix.

### Validation

- Add installed OpenAI SDK transport checks for all eight roles and an eight-role workflow. Transport fixtures do not establish live account/model access.

## Local candidate baseline — 2026-10-14

Initial local release candidate: Python CLI/SDK, eight independently callable agents, persisted bounded orchestration, ten original skills, source inventory/Python AST facts, cited lexical and validated embedding retrieval, scoped SQLite memory/state, optional official OpenAI Responses/tool/embedding adapter, exact proposals and POSIX guarded apply/recovery/rollback, approved Docker/explicit host tests, TypeScript CLI adapter, disposable regression examples, CI and maintainer documentation.

Contract version 1. Authored source uses Apache-2.0. No public registry/GitHub publication, hosted deployment or live paid model acceptance was performed. Guarded source mutation and test execution require POSIX; Windows read-only portability is represented separately. Validation evidence is in docs/validation.md.
