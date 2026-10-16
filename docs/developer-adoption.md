# Developer adoption guide

Agentic Workbench is Alpha local developer tooling. Consumers own their installation, application root, state, execution permissions and optional API credentials. Start offline, then accept provider or execution behavior in a disposable copy before integrating it into development. This package supplies no hosted service, centralized key, support SLA or security certification.

## Choose an integration surface

Use the installed CLI for terminal/subprocess workflows. Parse the version 1 envelope and exit code; help/version are ordinary text. Use the public Python SDK in a context manager to release state handles. The TypeScript adapter calls the same installed CLI using bounded subprocesses and `shell: false`; supply its absolute installed executable. It is not a second policy implementation.

Static results cite source facts and report coverage without executing the inspected application. Model output is labeled separately and may propose interpretations or edits. A source citation establishes the cited bytes/lines at a recorded hash; it does not prove an interpretation or application security. Review recommendations and actual diffs.

## Permissions and data flow

| Operation | Authority and data |
| --- | --- |
| Offline inspection/lexical search | Permitted bounded source reads and private local state; application source stays unchanged |
| OpenAI analysis/semantic search | Explicit network grant plus developer credential; selected context/instructions/tool output may reach OpenAI |
| Apply | Separate host write grant and exact current proposal digest; records original content for eligible rollback |
| Docker test | Separate execute grant and exact command/snapshot/backend digest; reviewed local daemon/image and disposable sanitized snapshot |
| Trusted-host test | Additional explicit trusted-host grant; repository code runs in a temporary copy without OS isolation |
| Rollback/state pruning | Exact reviewed digest; preserves conflicts and protected active/ambiguous records |

Config can narrow access and name commands/providers. Source, skills, model responses and config cannot mint host grants or approvals. Models receive read tools. SDK approval callbacks are trusted host code: use them for a real review decision, never connect them directly to model instructions or arbitrary returned digests.

`.agentic/` may contain explanations, source chunks, diffs, test receipts and original source backups. Ignore it in Git, protect backups/exports and manage retention deliberately. SQLite history is mutable by its OS owner. Recognized patterns and known credential values are filtered before model/state/log sinks, but filtering is not proof that every secret or confidential fact was found. Narrow exclusions, inspect coverage and keep data-transmission decisions with the project owner. See [security](security.md) and [providers](providers.md).

`--prompt-key` keeps an interactive credential in the invocation's process environment and restores/removes it afterward. Configure only `credential_env`, never a credential value. Automation uses secure environment injection. Grant network separately; provider names do not authorize transmission. Request bounds are not a hard dollar budget.

## A small acceptance path

1. Verify the installed version and run the offline SDK walkthrough outside the package checkout. Confirm static results, zero provider requests and unchanged source.
2. On POSIX, opt into the walkthrough's exact synthetic fix/trusted-host test. Confirm failure before, success afterward, byte-identical rollback and cleanup.
3. Try read-only analysis on a disposable application copy. Check exclusions, coverage and evidence against source you know.
4. Configure a real command and, preferably, an approved present Docker image. Review argv, executable/image and snapshot before execution. Install target dependencies separately.
5. If AI is needed, approve source transmission and use your own account/model. Check response quality, actual usage receipts, cost behavior and semantic relevance. Live paid checks are excluded from normal CI and remain pending environment acceptance.
6. Review one narrow proposal, apply its digest, run an approved regression check and verify conflict-safe rollback before broader integration.

The authored tutorial automatically approves only its exact predefined synthetic fix. Your application host must make its own review decision. Automated prototype checks are not production application acceptance.

## Troubleshooting and support

| Symptom | Next step |
| --- | --- |
| Missing CLI/import failure | Use the environment's absolute interpreter/entry point; check version outside the checkout. For macOS synchronized-folder editable issues, use a wheel or an environment outside that folder. |
| OpenAI integration unavailable | Install the local checkout or real wheel with `[openai]` in the same environment. Check account-available model and configured credential name; never report its value. |
| Prompt rejected | Use an interactive TTY, `--allow-network` and effective OpenAI provider/model. Automation injects the configured variable and omits the prompt. |
| Denied/missing source | Inspect coverage, root, exclusions, alias/hard-link/special-file checks and caps. Narrow the task; do not bypass guards. |
| Stale approval/conflict | Re-review the current operation/diff and stop other writers. Do not reuse an old digest or force rollback over later edits. |
| Test backend unavailable | Check executable and, for Docker, the approved present pinned image/local daemon. Host execution needs deliberate `--trusted-host`; no fallback is selected. |
| Snapshot-only test failure | Inspect actual execution output, separately installed dependencies, filtered files and read-only paths. Put cache/build output in `/tmp`. |
| Unknown receipt/interrupted write | Inspect task/state and follow [recovery](recovery.md). Unknown external outcomes block replay; keep ambiguous artifacts for review. |

Use the maintainer's verified issue/security channel once configured. This repository does not invent owner identities, URLs, response times or support commitments. Prepare a minimal disposable reproduction, installed version, OS/Python version, redacted command, error code, coverage and relevant hashes. Do not attach keys, private source, `.agentic/` or unreviewed state exports. Send vulnerabilities through the actual private maintainer channel rather than an assumed public tracker.

## Maintainer gates and versioning

Use `uv.lock`; run the offline Python suite, lint/format, strict SDK types, builds and clean installed-wheel/sdist checks outside the checkout. Include the consumer walkthrough. Node changes need locked script-blocked installs, build/protocol tests, installed-CLI integration and fixture types. Runner changes need actual Docker acceptance with an explicitly approved present image. Provider upgrades need the genuine pinned SDK transport fixtures, including the inspected internal bridge. Audits/local tests are evidence, not proof of security or remote CI success.

Review the final diff, changelog, provenance, licenses and package contents before release. Exclude credentials, state, environments and private course artifacts. Git/setuptools-scm supplies version; tag/version/distribution metadata must agree. Existing release tags stay immutable. Semver governs public interfaces; v1 CLI/result/skill contract changes need explicit compatibility and migration guidance. Alpha consumers should pin versions and re-run acceptance when upgrading.

Registry publication, remote branch protections, maintainer identity/contact setup and live provider acceptance are separate owner actions. A local wheel or authored workflow is not a published package or remotely verified release. The [contribution guide](../CONTRIBUTING.md), [release process](releasing.md), [API reference](api.md) and [validation ledger](validation.md) carry the detailed gates/evidence.
