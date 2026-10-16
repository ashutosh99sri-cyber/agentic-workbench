# Evaluate Python repair workflows

The repository contains 30 historical defects from more-itertools, Click and packaging. Each
task pins the official buggy and fixed commits, source ZIP SHA-256 values, an editable Python
source allowlist, a public reproduction and an independent holdout. The corpus manifest and
license/provenance notes live in `evaluations/python/`.

This evaluates two different things. `known-patch-replay` checks that the repair infrastructure
can propose, approve, apply, reopen and independently verify a known repair. `provider` measures
the configured model or explicitly supplied trusted adapter. Replay success is never evidence
that a model can diagnose these defects. `no-patch-control` verifies that leaving the buggy source
alone cannot produce a verified repair. Scorecards remain separate by mode.

## Run a control evaluation

Use a source checkout with the development dependencies installed. Docker is the default
execution boundary; task commands have no network access. Fetching public archives requires
the separate `--download` option. Cached archives are always checked against their pinned hashes.

```sh
uv sync --locked --all-extras
docker pull python@sha256:e88e9763f943ec1834f992a4b51e0f24500486803e8bc534e5767af9ea65f6ce
uv run python scripts/evaluate_repairs.py \
  --manifest evaluations/python/manifest.json \
  --cache /tmp/agentic-python-archive-cache \
  --output /tmp/agentic-replay-first-run \
  --download --mode known-patch-replay
```

The output directory must be new. It contains fetched source copies, separate grading projects,
repair state and per-trial `result.json` files. `report.json` is updated after every completed
trial. Keep this evidence outside the repository being repaired. Source ZIPs stay in the chosen
cache; upstream projects are not vendored into Agentic Workbench.

For a short run, repeat `--task TASK_ID` to select tasks from the manifest. `--trials 3` repeats
each selected task with fresh state. `--max-attempts` accepts 1–4 candidate generations. To run
the no-patch control, choose another new output directory and `--mode no-patch-control`.

Reviewed, owner-controlled fixtures can opt into `--trusted-host --python /absolute/python3.11`.
This runs commands from temporary source copies and **does not provide an OS sandbox**. Prefer
Docker when evaluating public code. The pinned Docker image supplies Python 3.11.17; changing
Python versions or the image requires qualifying the tasks again.

## What counts as a verified repair

For every selected trial the evaluator first runs four commands through the real approved Runner:
the public and holdout checks against both buggy and fixed source. Buggy behavior must fail and
fixed behavior must pass. Missing dependencies, missing files, syntax/setup errors, timeouts and
truncated output cannot qualify a defect. A task that cannot qualify stays in the selected-task
denominator with its setup error and receipts.

A syntax error in a real check/imported source file is a setup failure. A valid module can also
raise `SyntaxError` while parsing malformed input through an API such as `ast.literal_eval`;
virtual filenames such as `<unknown>` or an absent filename classify that as a behavior failure.
The fixed-source checks must still pass before the task qualifies.

The repair workspace receives only buggy source and `test_reproduction.py`. Reference source and
holdouts remain in separate host-owned roots; neither is included in model context. The trusted
replay adapter can read the reference source directly. The live adapter cannot.

The evaluation host supplies exact approval digests only within these disposable projects and
records the authority as `evaluation-host`. These are automated benchmark approvals; they do not
measure human review time and are not suitable approval defaults for a developer's repository.
The Workbench closes and reopens after each approval pause. Completed baseline runs, proposals
and applications must survive those boundaries without being repeated.

After repair, the evaluator copies the resulting source into two new grading projects and runs
the original public check and hidden holdout. A verified result requires the repair API to report
`repaired`, both independent commands to pass, and a nonempty diff confined to the exact allowed
source files. Test changes, extra files, deleted files and a no-op cannot pass this criterion.
A partial patch that satisfies only the public reproduction remains a failed repair.

The trusted outer Python process reserves its stdout for the Runner receipt and streams both
child output channels to stderr. A private, bounded completion pipe records that the child
returned from the check; an early process exit, a missing/malformed record or an inconsistent
exit code is unusable. This is completion bookkeeping for reviewed candidates. Arbitrary Python
inside the child can introspect frames and file descriptors or monkeypatch its runtime. The
completion pipe does not prove correctness against hostile Python. Fully adversarial grading
requires task-specific data/API separation, which this corpus runner does not provide.

Some reviewed public source/check text may match the Workbench secret detector. The Runner
intentionally omits secret-flagged files. These tasks remain blocked setup cases rather than
weakening the security policy or hiding benchmark literals to improve the score. Host-only corpus
qualification and actual Runner qualification are separate evidence.

## Configure a live provider explicitly

Live calls are opt-in. The current supported adapter is OpenAI; `OPENAI_API_KEY` must already be
available in the host process. Credentials are never passed into task commands. The evaluator
does not read keychains, create accounts or modify global configuration.

Create a local JSON file with an actual supported model, the current input/output prices and the
official price page used to obtain them. Values below describe the required fields, not prices
or a model recommendation:

```json
{
  "model": "YOUR_SUPPORTED_MODEL",
  "input_price_per_million_usd": 1.0,
  "output_price_per_million_usd": 1.0,
  "price_source": "https://YOUR_PROVIDER_OFFICIAL_PRICE_PAGE",
  "maximum_cost_usd": 5.0,
  "maximum_tokens": 1000000,
  "max_output_tokens": 8000,
  "context_bytes": 32000
}
```

Replace the example model, prices and provenance before running:

```sh
uv run python scripts/evaluate_repairs.py \
  --cache /tmp/agentic-python-archive-cache \
  --output /tmp/agentic-provider-first-run \
  --mode provider --live-config /absolute/path/live-evaluation.json \
  --task TASK_ID --max-attempts 2
```

The initial total estimated budget is capped at USD 5. Existing model routing reserves a
conservative maximum before each dispatch. Each later task receives only the remaining budget;
unknown usage or an uncertain dispatched outcome stops further live tasks. Known setup failures
before dispatch do not spend that budget or prevent the next selected task from qualifying.
This enforces local estimates using supplied prices, not a provider-side billing cap. Retained
reservations can be more conservative than the final billed amount.

Candidate attempts and HTTP requests have different bounds. One candidate can use the configured
six tool rounds plus its final analysis, so its adapter permits at most seven HTTP requests.
A two-attempt repair therefore permits at most fourteen HTTP requests. Routing reserves the
maximum input and output tokens across all seven requests before starting a candidate. The
default per-trial token budget is 1,000,000; lowering it, raising context/output bounds or choosing
four attempts may stop a later candidate at the budget gate. Completed receipts settle that
reservation to observed usage. The USD 5 total estimated cost limit still spans all selected trials.

The current candidate API generates complete file contents. Large source files can exceed the
configured context or output limits, and the model may produce no valid candidate. Record these
as failures rather than attributing replay performance to live models. No automatic retries are
performed after an unknown provider outcome.

## Read the results

Every selected trial records qualification receipts, repair task and attempt/change references,
approval boundaries, reopen counts, public/holdout results, changed paths, actual elapsed latency,
known provider usage and estimated cost. Missing usage or pricing is `null`, never zero.
Offline controls record exactly zero live requests, tokens and cost; local candidate generations
are represented by the repair attempt records. `human_review_seconds` remains `null`.

Each mode's scorecard reports selected and qualified denominators, verified repairs, first-attempt
repairs, blocked setup cases, failed qualified cases, median/p95 elapsed time and known cost per
verified repair. Latency includes qualification, Runner setup, approval pauses/reopens and final
grading; it is not model-only latency. Inspect per-trial traces for narrower timings. A completed
evaluation command exits zero even when controls deliberately fail to repair tasks; inspect
`verified`, `qualified`, errors and the denominators to judge the result.

The Python host API is `agentic_workbench.evaluation.evaluate_corpus(...)`. It also accepts an
explicit `provider_factory(policy)` in provider mode for trusted adapter experiments; such an
adapter owns its external-call budget and is labelled `trusted-host-adapter` in the report.
The CLI uses the bounded configured OpenAI path. No adapter factory is loaded from project text
or a string import path.
