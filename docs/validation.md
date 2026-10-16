# Validation evidence

This is an incremental evidence ledger; it does not represent a completed framework until the final acceptance record is added.

## BYOK developer distribution — 14 October 2026

The installable-toolkit refinement adds hidden temporary CLI credential entry, packaged inline SDK types, developer adoption guidance and a disposable installed-SDK walkthrough. It retains local owner-controlled permissions, offline defaults and separately approved source changes. It introduces no hosted service or shared credential.

At source commit `4b5acbf91`, Python 3.14.0 passed **329 tests** with warnings treated as errors, including all six actual Docker checks. Three installed-environment distribution checks were deselected for a separate clean-package gate. Coverage measured **2,731 of 3,134 statements (87.14%)**. Ruff lint/format passed 60 files; strict mypy passed all 21 source modules. Node passed nine protocol tests, and the TypeScript fixture compiled. Locked Python and Node audits reported zero known vulnerabilities; the Python audit covered 37 third-party packages. These are local macOS results, not remote CI acceptance.

The key-entry checks cover hidden-input failure, TTY/network/provider/model/endpoint and partial-extra preflight denial, exact redaction of an unrecognized credential format, semantic embedding-model selection, and restoration/removal of the temporary environment value after success, errors and interruption. The four walkthrough checks verify zero provider requests and unchanged source by default, real failure-before/pass-after/byte-identical rollback with `--execute`, rejection of an existing application root, and actual rollback when post-apply evidence fails.

The first Python 3.14 broad run exposed leaked test-owned SQLite connections. Factories now register immediate scoped finalizers, direct probes close their connections after transactional exit, and read-tool tests own their stores with context managers. No warning was suppressed and production state behavior was unchanged. Fresh-context review found no remaining blockers after the partial transport-extra preflight and resource cleanup fixes.

All eight agent roles and their coordination use the installed OpenAI SDK in bounded transport fixtures. These checks exercise real SDK serialization/tool/receipt paths against controlled responses; they do not establish live model reasoning, account access, billing or embedding relevance. The delivery's clean-install receipt records built wheel/sdist, consumer typing and installed-CLI adapter acceptance separately. Public registry/GitHub publication, remote branch protection, live paid requests and additional OS acceptance remain owner/environment work.

## Package foundation — 14 October 2026

- Isolated development interpreter: Python 3.12.14. Runtime dependencies and the optional OpenAI SDK were installed inside this repository's `.venv`; `uv.lock` records 38 resolved packages. No global Python configuration or package installation changed.
- RED: `uv run --locked pytest tests/test_packaging.py -q` failed 2 tests because the public version and installed CLI module were absent.
- GREEN: the same command passed both tests after implementation. Ruff and mypy passed the initial two source modules.
- `uv build` produced a wheel and source distribution. The wheel was installed with its real dependencies into a new isolated environment outside the repository; installed `agentic --version` worked from `/tmp`, and `uv pip check` passed.
- This initial package exposes version/help only. The six application commands are pending implementation. The initial source-distribution build warned that the final README is not yet written; the documentation task and final package acceptance must resolve that warning.
- Live API calls, model access, full agent workflows, source mutation, Docker isolation and cross-platform CI have not been validated at this checkpoint.

## Contracts, configuration and events

- Implemented typed result/evidence/usage/host-grant contracts, packaged closed JSON Schemas, duplicate-key/finite-UTF-8 JSON validation, validated TOML configuration and metadata-only redacted events.
- Two adversarial regression tests failed for invalid Unicode and shared schema mutation before fixes, then passed after the canonical JSON boundary and defensive schema copy were corrected.
- Packaging/configuration/contract/event tests: 23 passed. Ruff passed; mypy passed all six source modules. Invalid configuration, inline credential fields, configuration-based network grants, shell-interpreter commands and log body fields are denied.
- A macOS hidden flag repeatedly reappeared on the editable-package registration file under the Documents workspace. Development checks now use the task-private `/tmp/agentic-workbench-01a13202/dev-venv` through `UV_PROJECT_ENVIRONMENT`; the initial `.venv` is retained. The temporary environment remains isolated and locked. Clean wheel-install checks remain independent of editable/source-path workarounds.
- This is a local environment accommodation, not a global Python or security-setting change. Source guards, secret detection, persistent execution, providers and agent workflows are still pending their own verification tasks.

## Source boundary and context slice

The complete foundation suite passed: 45 tests. Repository and retrieval checks passed: 3 tests; skill registry checks passed: 2 tests. Initial context tests failed because modules/resources did not yet exist, then passed with real source implementation. Scanning detects manifest/import facts, extracts Python symbols/direct call expressions, prunes nested ignored directories, and omits protected credentials. Current source hashes filter stale retrieval. Original bundled skills cover eight roles plus Python/TypeScript guidance. Lexical retrieval and validated cosine-vector ranking are independently tested; these fixtures do not establish live embedding relevance. Windows reads reject resolved aliases before access; guarded writes remain POSIX-only.

## Runtime, provider, recovery and sandbox acceptance

On 14 October 2026 the broad offline suite passed 214 tests with warnings treated as errors; 7 opt-in distribution/Docker tests were deselected in that command. The separate real Docker suite passed 6 tests with warnings treated as errors. Optional API transport fixtures used the installed official OpenAI 3.29.0 / httpx2 2.13.1 SDK; 67 provider checks passed, including actual function call IDs, shared child budgets, retained request/response/model provenance, source grant denial, partial-body unknown outcomes and restart refusal. No paid API calls were made.

The change/recovery checks cover exact approval, real apply/deletion/mode restoration, compensation, conflict-safe rollback, subprocess exits around journal/mkdir/stage/source-write boundaries, inode-bound owned cleanup and honest unresolved artifact states. Receipt gaps retain ambiguous artifacts for inspection. Testing actual examples observed a failing percentage regression before correction, a passing test after exact approved replacement and rollback to original source for Python and TypeScript. Trusted-host example execution is explicitly weaker than Docker.

The real Docker image was node@sha256:d6aa754f16b3197301076f047b5def2f02ea1dbbc2ca920407d46d7ec7f87b20 through the local Unix daemon. It demonstrated UID 65534, zero capabilities, no-new-privileges, source/root filesystem write denial, no credentials/state/socket/original repository exposure, loopback-only network, timeout/overflow/interruption handling and exact owned-container absence after cleanup. No image was pulled locally and no unrelated container was removed.

A measured synthetic inventory of 1,000 Python files extracted 1,000 symbols in 0.067 seconds on this macOS host; a 100-file configuration capped scope and reported the limit. This is one small local fixture, not a production benchmark or complexity guarantee. Native uv audit checked 37 locked third-party packages with zero reported vulnerabilities/adverse statuses. The Node lock audit also reported zero vulnerabilities.

CI YAML parsed with the system Psych parser. GitHub action tag commits were verified against their primary GitHub repositories and pinned: checkout v5, setup-node v5, setup-uv v7 and upload-artifact v4. Authored Python/macOS/Linux, Windows read-only, Node, clean distribution, audit and manual Docker/release jobs were not remotely executed; branch protection awaits an owner-created remote.

The source-selected agent/provider integration was reviewed separately. Verified fixes include target hash checks after staging, exact inner rollback approval, role/skill pins before completed-node reuse, periodic live worker leases, source network grant enforcement for injected providers, partial-body unknown receipts, bounded retrieval context, durable API IDs/intent hashes, vector response/count batching and validation before caching. Dependency upgrades must rerun the genuine SDK transport fixtures.

## Clean installation and final acceptance

The complete local Python suite passed **223 tests**, with no skips or deselections and warnings treated as errors, including real Docker and clean-installed-wheel acceptance. Coverage measured 2,628 of 3,046 statements (86.28%); it is line coverage, not proof of every branch or production environment. Ruff check and format check passed for 58 Python files, strict mypy passed all 21 source modules, the TypeScript example compiled, and Git whitespace checks passed.

A clean wheel environment and a separate clean sdist-built environment each ran all six installed commands outside the checkout, loaded ten packaged skills, coordinated a real plan, dry-ran and applied an exact approved change, executed a real approved unittest command and rolled back. The core wheel uses only eight installed packages including the project; the optional SDK is not required for offline operation. Sdist version metadata survived rebuilding outside Git.

The Node adapter passed **9 protocol tests** and **1 actual installed-CLI integration test**. Its compiled local npm archive installed into a separate consumer and performed a real scan through the installed Python CLI. The actual CLI integration initially caught macOS parent-alias import rejection and an untrusted PATH-selected Python executable; the import guard now pins an explicit canonical parent and no-follow leaf, while the fixture selects its isolated Python executable without weakening executable policy. Both corrected checks passed.

Runtime validation used macOS, Python 3.12.14, Node 26.7.0 and the local Docker engine. Additional OS/Python versions are authored CI targets, not remotely confirmed runs. No paid live API, public registry/GitHub publication, deployment, visual UI acceptance or security certification was performed. Windows guarded source mutation and runner execution are intentionally unsupported. Conservative secret recognition cannot detect every sensitive value, OS owners can alter local state, and unrelated writers must cooperate with the advisory write lock. Crash receipt gaps retain ambiguous artifacts and report recovery_required. These are explicit boundaries, not silently waived checks.

Authored architecture, original skills, documentation and contribution/security/release guidance are present. All T01–T29 acceptance slices have source/check evidence; the local final version/tag/distribution equality is verified in the delivered release receipt and checksums. Remote owner policy and live acceptance remain separate adoption work. Token Saver snapshots were kept outside the repository; no matched baseline or all-agent comparison exists, so no percentage savings is claimed.

Final installation review added mandatory exclusion of `.venv-*` environments, including the tutorial's `.venv-agentic`. The old wheel failed the new installed scan assertion; the corrected unpublished local release candidate was rebuilt and its local tag/checksums updated transparently. The complete suite passed 223 tests after this correction.

## Static tracing, symbol tools, MCP server and benchmark — 14 October 2026 (unreleased)

- `RepositoryIndex.trace` joins one Python symbol's definitions, call sites, callees and test-file lines. The static intelligence, engineering and testing paths and the new `list_symbols`/`trace_symbol` read tools use it. Every read tool now carries its own description. Bundled engineering, intelligence, testing and python-engineering skills are 1.1.0; the engineering skill carries a minimal-change decision ladder and worked examples. Existing persisted tasks will report skill drift on resume, by design.
- `agentic mcp` serves scan, explain, search, plan, run, status and review over newline-delimited JSON-RPC with the standard library. A live stdio smoke test against a copy of the Python example completed initialize, tools/list and an explain call; stdout carried only JSON-RPC responses and the structured logger wrote to stderr.
- `scripts/benchmark.py` static baseline on the two examples: 6 of 6 tasks cite the expected files, name the expected symbols and reference the expected tests, each under 30 ms with zero provider requests. `tests/test_benchmark.py` pins that baseline. The benchmark scores targeting and retrieval, not proposal correctness.
- Checks: ruff check, ruff format --check and mypy strict passed; `uv build` succeeded; the full non-Docker suite passed 300 tests (`-W error`). The provider contract test now derives each role's expected tool set from the selected skills instead of a fixed three-tool list.
- Environment note: in this synced Documents checkout the editable `.pth` files carried the macOS hidden flag, so the suite was run with an absolute `PYTHONPATH` to `src`. No global configuration changed and CI is unaffected. Docker, distribution and live-provider checks were not rerun.

## Execution harness acceptance — 14 October 2026 (unreleased)

The pre-implementation audit is [harness-gap-analysis.md](harness-gap-analysis.md); [SPEC-harness.md](design/SPEC-harness.md) records the extension contracts and [harness.md](harness.md) documents the resulting architecture and APIs. The 26 staged files present at task start were preserved. Harness changes remain reviewable in the working tree.

- **Baseline:** 300 offline Python tests passed, 87% statement coverage, 9 Node protocol tests, Ruff lint/format and strict mypy. The existing workspace editable environment failed imports; a fresh locked environment `/tmp/agentic-harness-dev` established the baseline without source-path overrides. Python 3.14 exposed existing SQLite cleanup warnings. Store finalization and explicit closure of fixture database connections corrected them; warnings remain errors in final verification.
- **Final Python:** the complete suite passed **396 tests** with `-W error`, including Docker and installed-distribution acceptance, with no skips or deselections. Of these, 388 are ordinary offline cases. Coverage was **4,234 / 4,888 statements (86.62%)**. The 88 added offline cases exercise routing and atomic resource admission, real SDK transport contracts, context freshness/compression/memory, tool schemas/grants/approvals/idempotency, MCP handshake/deadlines, API transport termination, durable loop verification/replanning/cancellation/reopen and actual approved fixture repair. Coverage is a statement metric, not a claim of exhaustive behavior or live intelligence.
- **Real Docker:** Docker Desktop was installed but its daemon was stopped. Starting the existing application made the already-present digest-pinned Node image available; no image was pulled. Six existing sandbox acceptance cases passed, then the new registry-through-Docker case passed: uid 65534, bounded output, exact owned-container cleanup, durable receipt reuse. This gives **7 Docker tests** with warnings treated as errors.
- **Clean distribution:** wheel and source distribution built successfully. Separate environments `/tmp/agentic-harness-wheel` and `/tmp/agentic-harness-sdist` installed the artifacts and ran `scripts/verify_distribution.py` from `/tmp`, outside the checkout. Both loaded ten packaged skills, ran the six existing commands and new execute/context/discovery/trace operations, applied an exact change, ran a real approved command and rolled back. The distribution-marked pytest case passed. These runs use the core dependency set without the optional OpenAI SDK.
- **Python total:** **396 passing cases** in the final combined run, after prerequisite-specific checks also passed. No missing prerequisite was silently skipped.
- **TypeScript:** adapter build and all 9 protocol tests passed. The actual installed-wheel CLI integration passed, including source-verified execution, traces, tool/skill discovery and context. Python still owns policy; Node only forwards bounded argv and validates envelopes.
- **Quality:** Ruff lint passed, all 76 Python files passed formatting, strict mypy passed 29 source modules, and Git whitespace checks passed. `uv audit --locked --output-format json` reported **37 audited packages, 0 known vulnerabilities and 0 adverse statuses**. This database result is not security certification.
- **Evaluation:** [harness-evaluation.json](harness-evaluation.json) records three deterministic host-fixture workflows with actual approved commands: two verified successes, one intentional unrepaired failure, and one repaired/resumed case with exactly one mutation. The recorded aggregate latency was **296.354 ms**. Model requests, input/output tokens and estimated provider cost were zero. These numbers measure offline controller behavior; they do not estimate live autonomous repair success, provider latency or paid cost.
- **Review:** three scoped audits preceded implementation. Cross-module and fresh final reviews found and corrected full API endpoint approval binding, uncertain MCP errors, stdio process classification/source pins, blocking MCP input deadlines, bounded inbound MCP framing, exact remote-tool binding, stale symbol/context exposure, distinct-instruction resume, provider/skill pins, cancelled checkpoint retention, valid command discovery aliases and terminal cancellation. Regression checks cover the corrections.

Current built artifacts are under `/tmp/agentic-harness-dist`, version `0.1.1.dev5+g10b18faf5.d20261013`. They are development artifacts from this working tree, not a new immutable release or publication. The current host was macOS, Python 3.14.0 and local Docker; additional CI matrix environments remain authored targets. Live provider accounts, live external MCP/API interoperability and live agent repair quality were not exercised. Source mutation remains POSIX-only. Trusted host callbacks are cooperative and supplied adapter bounds/prices remain host contracts. Token Saver root-log snapshots were recorded outside the repository; no matched baseline or complete descendant accounting supports a percentage savings claim.

## Codebase regression verification — 15 October 2026

The initial run reported 890 passes and 23 failures. Numbered local copies were
being collected as tests, type-checked as separate modules and included in build
archives. The other failures came from subprocess imports: Python's verbose
startup reported `Skipping hidden .pth file` for the editable installation.
Clearing the macOS hidden flags worked within one command, but the flags returned
between commands. A fresh locked environment outside the checkout resolved the
imports without source-path overrides. The local `.venv` links to
`~/.codex/venvs/agentic-workbench-20261015`; the previous environment and 30
untracked numbered project copies are preserved under
`~/.codex/backups/agentic-workbench/20261015T122525Z`. All 30 file hashes match its
`manifest.json`. Existing tracked and staged work was preserved.

The Node archive also included stale `dist/index 2.js` and declaration files
because its package allowlist admitted the entire output directory. A regression
using actual `npm pack` output failed before the fix. Restricting the allowlist
to the two exported files fixed it without deleting stale build output.

- **Python:** 870 cases passed with warnings treated as errors, including the
  clean-installed distribution case and required native TypeScript analysis;
  eight Docker cases were deselected from that run. Coverage was 5,688 of 6,442
  statements (88.30%). JUnit and coverage JSON are at
  `/tmp/agentic-codebase-python-20261015.xml` and
  `/tmp/agentic-codebase-coverage-20261015.json`.
- **Docker:** all eight remaining cases passed in separate runs: seven Node
  sandbox checks and one Python unusable-baseline check. Both exact CI image
  digests were already local. The total is **878 passing Python cases** across
  the three disjoint runs. Docker Desktop was started; no image was pulled.
- **Node:** build, 13 tests, the actual installed-CLI integration and TypeScript
  example compilation passed. A real npm archive contained exactly five files;
  an isolated consumer loaded its exports and declarations and scanned a Python
  fixture through the installed CLI, with zero provider requests. The intentional
  percentage bugs in the repair examples remain available to acceptance tests.
- **Distribution:** fresh wheel and source distribution contained zero numbered
  copies. Separate clean consumers passed resource, ten-skill, six-command and
  approved apply/test/rollback checks outside the checkout. Artifacts are under
  `/tmp/agentic-dist-final.ILnmHr/artifacts`; the npm archive is under
  `/tmp/agentic-node-consumer-final.wlpaR0`. These checks preceded this log update.
- **Quality:** Ruff lint, formatting for 104 Python files, strict mypy across 35
  source modules and Git whitespace checks passed. The locked Python audit
  covered 37 packages with zero known vulnerabilities/adverse statuses; the full
  npm audit also reported zero vulnerabilities. A focused independent review of
  the packaging change found no actionable issues.

Validation used macOS, Python 3.14.0, Node 26.7.0, npm 11.19.0 and Docker Engine
29.8.2. This run made no live paid provider calls, performed no remote publication
and did not execute hosted CI or other OS/runtime matrix targets. Coverage and
dependency audit results do not establish exhaustive correctness or production
certification. Docker Desktop remains running. Token savings are unmeasured
against a comparable baseline.
