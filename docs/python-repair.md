# Python repair

`agentic repair` and `Workbench.repair` turn a failing check into a verified fix without giving the model any authority. The workflow reproduces the failure with a command you configured. A provider then proposes a change to files you named, and you approve the exact change. The same command must pass on the changed source before the repair counts. Every write and every command run waits for its own exact approval. Each step is recorded durably, so you can close the process between approvals and continue later. Nothing completes on a model's word.

It is built on the existing [harness](harness.md): the engineering agent, proposal reviews, the approved command runner and durable checkpoints. The shared contract is `docs/design/SPEC-python-repair-evaluation.md`.

## Requirements

- A named command in `.agentic/config.toml`, for example `[commands.unit]` with `argv = ["python", "-m", "unittest"]`. Docker runs need its pinned `image`; `--trusted-host` runs it on this host instead, with weaker isolation than Docker.
- A provider: `--provider openai --model MODEL --allow-network` on the CLI, or a trusted adapter passed to `Workbench(provider=...)`. Without one, repair stops with `INTEGRATION_UNAVAILABLE` before doing anything.
- The CLI grants write and execute for this command only; each write and run still needs its exact approval digest. Through the SDK, use `Grant(network=True, write=True, execute=True)`, plus `trusted_host=True` for the host backend.
- POSIX, as for every approved source write.

## Lifecycle

1. **Baseline.** The workflow reviews the command and its source snapshot, then pauses with `reviews.baseline`. Pass its digest as `--approve-baseline`; the command then runs once.
   - Exit 0 means `already_passing`. The repair completes with no provider request and no edit.
   - A complete nonzero exit is a reproduced failure. It shows that the command fails; it does not prove which defect causes it.
   - A timeout, an output-limit stop, or exit 125, 126 or 127 ends the repair with `BASELINE_UNUSABLE` and keeps the receipt. No provider request is made. Docker uses those three exits when the command itself could not start, so a test that exits with one on purpose is treated the same way.
2. **Candidate.** The engineering agent gets your instruction, the allowed files, and the tail of the latest command output. The output is bounded, redacted, and marked as untrusted data the model must not obey. Exactly one proposal must result. These use up the attempt:

   - no candidate (`NO_CANDIDATE`);
   - a candidate outside the allowed files (`INVALID_CANDIDATE`);
   - a known provider rejection, refusal or incomplete response.

   Any other provider error stops the repair with `OUTCOME_UNKNOWN` and is never retried, because earlier requests in the same analysis may already have been sent and paid for. That includes an uncertain outcome, and a missing API key or package discovered between requests. The attempt's `failure` keeps the provider's own code. Start a new repair after fixing the setup.
3. **Change.** The repair pauses with `reviews.change`, which holds the diff and its digest. Pass the digest as `--approve`; the change is applied once. If the source changed after the review, the apply is refused with `STALE` and your edit is kept.
4. **Check.** The command is reviewed again for the changed snapshot and pauses with `reviews.test`. Pass `--approve-test`; the command then runs once.
5. **Decision.** The repair is `repaired` only when all of these hold:
   - the baseline reproduced a failure;
   - the approved change was applied;
   - the check exited 0, with no timeout or output limit;
   - its snapshot still matches the current source.

   Otherwise the next attempt starts from the current source, with the failed check's output as evidence, until `--max-attempts` (1–4, default 2) is used up and the repair stops with `REPLAN_EXHAUSTED`.

The last failed candidate stays applied so you can inspect it. Undo it explicitly with `agentic apply --rollback CHANGE_ID` and its own approval. Repair never rolls back or overwrites your later edits.

```bash
agentic repair "Fix the percentage discount" --command-id unit --edit-path app.py \
  --provider openai --model MODEL --allow-network          # pauses: data.reviews.baseline
agentic repair "Fix the percentage discount" --command-id unit --edit-path app.py \
  --provider openai --model MODEL --allow-network \
  --task-id TASK_ID --approve-baseline DIGEST              # pauses: data.reviews.change
# ... --task-id TASK_ID --approve DIGEST                   # pauses: data.reviews.test
# ... --task-id TASK_ID --approve-test DIGEST              # repaired, or the next attempt
```

Repeat the same instruction and options on every call. A changed option, configuration, provider or skill is refused with `CONFLICT`. Calling without the approval the repair is waiting for only reports its status. Continue a repair with `agentic repair ... --task-id` or, in the SDK, `wb.repair(...)` or `wb.resume(task_id)`. Stop one with `agentic cancel TASK_ID`. The CLI exits 1 when a repair finishes `failed`, and still prints the full result.

```python
from agentic_workbench import Grant, Workbench

with Workbench("/path/to/app", grants=Grant(network=True, write=True, execute=True)) as wb:
    result = wb.repair("Fix the percentage discount", command_id="unit", edit_paths=["app.py"])
    # Show result["reviews"]["baseline"] to the person approving, then continue:
    result = wb.repair("Fix the percentage discount", command_id="unit", edit_paths=["app.py"],
                       task_id=result["task_id"], baseline_approval=APPROVED_DIGEST)
```

## Allowed files

`edit_paths` is your explicit list of 1–20 existing, indexed, writable Python source files. Model output cannot widen it. The following are refused before any task starts:

- tests and test machinery: `tests/` or `test/` directories, `test_*.py`, `*_test.py`, `conftest.py`, and any file named in the command;
- `setup.py` and `noxfile.py`;
- non-Python, missing, protected and secret-bearing files.

A candidate that edits any other file, creates a file or deletes one is never applied.

## Result

The result has the harness status fields (`task_id`, `state`, `phase`, `observations`, `verification`, `error`, …) plus:

- `outcome`: `already_passing`, `repaired`, `in_progress` (awaiting an approval, or resumable), or `failed`. When it is `failed`, `error.code` says why: `BASELINE_UNUSABLE`, `REPLAN_EXHAUSTED`, `OUTCOME_UNKNOWN` or `STALE`. A cancelled repair has `state: cancelled`.
- `reviews`: the latest `baseline`, `change` and `test` reviews. Their digests are what you approve; they never grant authority by themselves.
- `baseline`: `run_id`, `exit_code`, `timed_out`, `output_limited`, `snapshot_hash` and `classification`, or null before the baseline runs.
- `attempts`: one record per attempt with `number`, `analysis_task_id`, `proposal_id`, `change_id`, `verification` (run facts, or null) and `failure`. `failure` is null, or one of: `NO_CANDIDATE`, `INVALID_CANDIDATE`, the provider or validation error code, `OUTCOME_UNKNOWN` (the attempt's provider outcome is uncertain), or `CHECK_FAILED` (the check ran but did not pass cleanly).
- `edit_paths` and `max_attempts`.

Full run receipts are durable. `wb.store.load("repair-run", run_id)` returns the exit status, snapshot, approval digest, command fingerprint, and the last 32 KiB of each output stream. So completion never depends on presentation-compacted observations or on model text.

## Limits

- Python source repairs only.
- Each repair has the harness's one-hour deadline and 32-step budget. Four attempts need at most 22 steps, and status polling spends none.
- Reproduction shows that the command fails, not which defect caused it; a passing command shows that the command passes, not that the defect is gone.
- Offline tests use deterministic providers, so they verify the workflow's safety and bookkeeping, not model quality.
