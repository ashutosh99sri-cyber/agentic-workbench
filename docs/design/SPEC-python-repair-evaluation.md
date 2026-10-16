# Python repair workflow and real-task evaluation
Status: implementation contract for user-authorized recommendations 5 and 6, 2026-10-15.
Baseline: 1c273977699c004a287f20bfcfe2ecab2de9573b. Preserve primary HEAD/index and every pre-existing change. No change to frozen prior release branch.

## Capability map and implementation order
| Module | Responsibility | Depends on |
|---|---|---|
| python-repair | Bounded, approved reproduction -> provider proposal -> application -> actual verification, persisted through existing Harness | Existing policy, AgentRuntime, ChangeWorkflow, Runner, Harness |
| python-repair-evaluation | Pinned historical upstream bugs, independent grading, reproducible attempts and measured reports | python-repair public API |
Implement repair contract and corpus preparation independently; integrate evaluator against that contract, then verify exact combined source. Existing tasks/plan.md and tasks/todo.md have user-staged deletions: keep plan/tasks here instead of restoring those files.

## Scope and assumptions
Python source-only repairs in owner-controlled repositories. Reuse existing execution/state/provider/approval contracts; no new agent controller, distributed scheduling, automatic production approvals, browser frontend, or additional language analysis. No new runtime dependency is expected.
Live evaluation uses only public task source, an existing supported configured provider, and at most US$5 initial estimated budget. No provider credentials were present in the current process; do not create accounts or change global credential/configuration settings. Offline historical-task checks remain useful and must be labelled separately from live-model effectiveness.

## python-repair public boundary
Workbench.repair(instruction, *, command_id, edit_paths, baseline_approval=None, approval=None, test_approval=None, backend="docker", task_id=None, max_attempts=2) -> dict.
CLI: agentic repair INSTRUCTION --command-id NAME --edit-path EXISTING_SOURCE.py [repeat] [--max-attempts N] [--task-id ID] [--approve-baseline DIGEST] [--approve DIGEST] [--approve-test DIGEST] [--trusted-host].
max_attempts counts candidate generations (default2, bounded1..4); baseline-only plan round0 followed by at most max_attempts candidate rounds. Preserve existing execute behavior.

edit_paths is a nonempty explicit allowlist of existing, indexed, source-relative Python files. Validate through shared policy. Reject tests/test machinery (tests dirs, test_*.py, *_test.py, conftest.py), configuration, non-Python files, deletion, new files and proposals writing outside the allowlist. Model instructions cannot broaden it.
The configured provider produces candidates through existing engineering AgentRuntime; saved proposals bind current source/config/skill hashes. Require exactly one proposal per attempt; no-candidate/invalid candidate is a known failed attempt, not unknown paid execution.
Raw receipts are not AgentResult dependencies. Feed a bounded, sanitized, clearly untrusted reproduction/failure excerpt into the engineering request, within existing instruction/context bounds.

## Required lifecycle and durable result
1. Validate options, provider availability and configured named command before privileged work.
2. Baseline review -> awaiting exact baseline approval -> real Runner command. A baseline nonzero exit with complete, non-timeout output reproduces command failure. It is not proof of semantic bug identity.
3. Baseline exit0 returns already_passing with no proposal/provider request/source edit; timeout/output truncation/infrastructure failure stops as baseline_unusable with known evidence.
4. For reproduced failure: diagnose/propose -> save concrete change review -> await exact approval -> apply once -> save current command/snapshot review -> await exact test approval -> actual check.
5. Test failure can consume a bounded next candidate generation using latest source and failed check evidence. Success requires prior reproduced failure, allowed approved change, clean exit0 and receipt matching current snapshot. Model claims never complete repairs.
6. Completed operations survive close/reopen approval pauses without new baseline, provider call or edit. Persist options/reviews/attempt facts; never approval digests as authority. Changed options/config/provider/skills, source drift, cancellation and uncertain effects keep existing refusal semantics.
7. Last unsuccessful candidate may remain applied for inspection and explicit existing rollback; never silently overwrite subsequent user edits or auto-approve rollback.

Return existing Harness fields plus reviews with stable keys baseline/change/test, and repair facts:
- outcome: already_passing / repaired / in_progress / failed (detailed errors stay existing typed error/state)
- baseline: durable bounded receipt/reference or null
- attempts: list of attempt records with number, analysis_task_id, proposal_id, change_id and verification receipt/reference when available
- edit_paths and max_attempts.
Review digests are host-readable review data, never model authority. Record source/command/snapshot identity and task/change/run IDs so evaluators need not infer completion from text.

## python-repair-evaluation corpus boundary
Curate approximately30 distinct historical bugs from3 explicitly licensed official upstream Python projects, quality over artificial variants. Every accepted task has exact repository URL, buggy and fixed full Git SHA, source/archive hashes, license/provenance, a public reproduction check, independent holdout checks and exact editable source paths.
Sources: official more-itertools, click and packaging repositories are initial candidates. Existing research/cache: /var/folders/jw/g8cwrhnn6rn3vzd1qhxy8z180000gn/T/agentic-rec5-6-upstream-research-xgcg60cf .
Every task must reproduce failure on buggy source and pass on fixed source before being called qualified. Keep blocked/invalid tasks in explicit reports, not silently removed. Count distinct defects, not parameter variants.

Manifest version1: top-level schema_version=1,tasks=[...]. Each task:
id,repo,buggy_commit,fixed_commit,summary,license,editable_paths(list),source_subdir(package import root within the prepared archive project root),reproduction_file(relative evaluations/python/checks/*.py),holdout_file(relative checks),optional notes. Editable paths are archive-project-root relative; the complete archive project root is retained, with no rebasing beneath source_subdir.
Archive checksums may be in task fields buggy_archive_sha256/fixed_archive_sha256 or a separate checked-in artifact lock; evaluator verifies them. Do not vendor upstream source unnecessarily. Keep upstream licenses in fetched evidence and provenance references in corpus docs.
Checks are independent stdlib unittest or assert scripts, executed from a prepared repo with PYTHONPATH set by host; upstream runtime dependencies must be identified. Reproduction is visible in workspace as test_reproduction.py; holdouts remain outside model-visible source. Model must never receive fixed source/patch/holdouts; replay-only host may read golden fixed files.

## Evaluation behavior and reporting
Use disposable workspaces and existing approved Runner boundary; Docker default and explicit trusted-host opt-in only for reviewed evaluation fixtures. Fetching is a distinct explicit network step from execution, with no credentials/proxies forwarded into task commands. Bound downloads/archive entries/file sizes, reject traversal/symlink/hardlink extraction.
Modes: no-patch baseline; known-patch-replay control; provider. Never present replay or fixture-provider success as model quality. Host may issue exact approvals only inside its owned evaluation workspace and must log this evaluation approval mode.
Always independently grade original vs repaired source; holdouts plus unchanged reproduction/check machinery determine success, not equality to upstream patch or model summary. Include no-op, invalid/test-tampering and wrong-patch negative controls and close/reopen, interrupted/cancelled and exhausted-attempt recovery tests.
Report every selected task/trial: qualification, final state/outcome, baseline/check/holdout exit codes, attempts, approvals, task/change/run IDs, actual latency, provider requests/tokens and estimated cost with provenance. Missing usage/prices/review time are null/unknown, never zero. Offline mode has actual zero live requests/cost but does not measure intelligence. Aggregate numerator/denominator, failures/blocked separately, first-pass and within-budget success, median/p95 latency, recovery, cost per verified result when known; do not invent human review savings.
Default no paid live calls. Live needs credentials and explicit host budget/config; capture price provenance and enforce conservative pre-dispatch admission, stop on unknown usage/outcome rather than spending past the local budget.

## Ownership
Claude: new repair.py, sdk.py, cli.py, __init__.py as required, test_repair.py, integration/test_python_repair.py and docs/python-repair.md. New separate worktree/branch from1c27397. Leave prior release branch frozen.
Codex: evaluation runtime/scripts/tests, evaluations/python corpus, docs/python-repair-evaluation.md, this spec, final integration and report. Root owns shared README/CI changes if required; request handoff before overlapping files.
Changes to Harness/Runner/provider/state contracts require a concrete reproduced need and coordinator agreement.

## Incremental plan and verification
- [ ] Freeze boundary above and acknowledge ownership in shared coordination file.
- [ ] Repair RED tests: approvals before commands/writes, real failed->passed check, source allowlist/test protection, no-op/unusable baseline, failed-candidate revision, exhaustion, provider unknown, stale source/config, cancellation, reopen exactly-once.
- [ ] Implement minimum repair slice and pass focused unit/integration gates before expanding.
- [ ] Qualify historical tasks RED/GREEN with independent checks and provenance.
- [ ] Evaluation RED tests for validation/grading/modes/missing metrics/negative controls.
- [ ] Integrate full historical corpus run and recovery/negative-control evidence.
- [ ] Fresh bounded review; full offline regression, Ruff/format, strict mypy; real Docker and clean installed CLI/SDK repair acceptance.
- [ ] Compare primary against captured baseline, apply only verified baseline-to-final delta without index mutation, verify final tree and original staged patch, save acceptance/report.

Commands (task environment, substitute relevant files during slices):
rtk proxy env PYTHONPATH=src /tmp/agentic-rec5-6-dev/bin/python -B -m pytest -m "not docker and not distribution" -q -W error
rtk proxy /tmp/agentic-rec5-6-dev/bin/ruff check src tests scripts
rtk proxy /tmp/agentic-rec5-6-dev/bin/ruff format --check src tests scripts
rtk proxy /tmp/agentic-rec5-6-dev/bin/mypy src/agentic_workbench
Keep modules, typed dict results and WorkbenchError style consistent with surrounding source. Regression proofs and exact commands/logs live under the task output directory.
