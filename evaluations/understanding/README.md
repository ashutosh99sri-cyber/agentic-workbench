# Fixed source-understanding controls

`manifest.json` freezes six targeting tasks and their exact source anchors before
the first evaluation run. Four tasks inspect this repository's real Python code
and native Node adapter, including cross-file TypeScript/JavaScript consumers and
checks. Two reuse immutable historical Python defects, archive locks and independent
behavior checks from `evaluations/python`. These are a small local control set,
not a representative benchmark or evidence of general model effectiveness.

The script copies policy-approved local sources into a disposable root and records
source hashes, config/parser pins and the frozen manifest hash. Historical inputs
come only from verified existing archive-cache entries. The public reproduction
is available to retrieval; hidden grading files never enter a retrieval workspace.
Missing sources, bad anchors, failed retrieval and unavailable vector modes stay
in the denominator. Do not change anchors or limits after inspecting scores.

The default corpus protocol is `policy-bounded-v1`, preserving the original local
source inventory, including this evaluation's manifest and other eligible metadata.
Opt in with `--isolate-evaluation-metadata` to use the separately versioned
`policy-bounded-without-evaluation-metadata-v2` dataset. This excludes the exact
workspace-relative `evaluations/understanding/` subtree from the disposable
retrieval copy and every repeated scan copy. Its task queries and answer anchors
therefore cannot become retrieval candidates through that metadata directory.
Selection is fixed by path, independent of task queries, targets and scores.
The frozen manifest, six tasks, anchors, `k=6` and 16,000-byte budget stay unchanged.

This is an evaluation dataset choice; runtime source policy and security exclusions
do not change. Historical Python sources and public reproduction checks retain
their existing selection. `evaluations/python/`, `evaluations/understanding-extra/`
and nested paths such as `src/evaluations/understanding/` remain eligible under
the usual source policy. Renamed metadata elsewhere is not automatically removed.
The narrow scope isolates the known understanding metadata without silently
removing the historical fixtures or unrelated source by similar names.

Reports declare `corpus_protocol` at the top level and in workspace snapshot pins.
Each snapshot's `evaluation_metadata_exclusions` receipt lists the declared
subtree, exact omitted policy-approved paths with their original source hashes,
and the policy-approved and copied file counts. `coverage` describes collection
before this evaluation-only filter; `source_fingerprint` and
`original_raw_source_hashes` describe the included files. `scan_source_pins`
records the corresponding receipt for every repeated scan copy.

All modes share `k=6` and a 16,000-byte canonical JSON chunk-list budget. A target
hits only if a selected citation covers its exact anchor line, rather than merely
mentioning its file. Structural impact receives the same predeclared changed paths
that a host could supply during a change review; lexical retrieval receives the
natural-language query. This difference is part of the measured workload. Vector
and combined rows remain unavailable without a real, explicitly configured
embedding run. Deterministic vector unit tests test plumbing only.

Run without network or executable repair controls:

```sh
rtk proxy env PYTHONPATH=src /tmp/agentic-rec5-6-dev/bin/python -B scripts/evaluate_understanding.py \
  --cache /absolute/archive-cache --output /absolute/new-output \
  --typescript-package adapters/node/node_modules/typescript
```

Add `--isolate-evaluation-metadata` for v2. For a paired baseline/candidate
comparison, use the same updated evaluator and frozen manifest for both runs,
set each run's `--workspace` and `PYTHONPATH` to its respective checkout, and use
the same flag, archive cache, parser package, repetitions and budgets. Compare
the declared protocol and source receipts before comparing scores; v1 and v2
scores describe different datasets and must not be mixed into one comparison.

`--repair-controls` also runs the existing repair Harness in no-patch and known-patch
replay modes for the two historical tasks, with separate public/hidden grading.
Use `--trusted-host` only for reviewed fixtures; the default is the existing pinned
Docker image. Replay supplies known edits and measures executable workflow controls,
not whether retrieval or a model discovers a repair. No paid provider is called.

Cold, warm, one-file edit, cold-edit comparison and reopen scans report actual reuse
counts and timings. Latency uses nearest-rank p50/p95 over the requested bounded
repetitions; unit tests assert counts and identities, never wall-clock thresholds.
The edit is a single appended source comment in the disposable copy and is restored.
Reports preserve every row and state live semantic/model effectiveness as unknown.
