# Historical Python repair corpus

This corpus contains **30 distinct upstream defects** from three explicitly licensed
Python projects. Each task uses the fixing commit and its exact buggy parent, with
independently authored public reproduction and holdout scripts. The checks are derived
from the documented behavior and inspected source changes; upstream test code was not
copied.

| Official upstream | Accepted defects | License | Import root |
| --- | ---: | --- | --- |
| [more-itertools](https://github.com/more-itertools/more-itertools) | 6 | MIT | `.` |
| [Click](https://github.com/pallets/click) | 6 | BSD-3-Clause | `src` |
| [packaging](https://github.com/pypa/packaging) | 18 | Apache-2.0 OR BSD-2-Clause | `src` |

Every accepted defect was checked on the real buggy and reference-fixed source using
CPython **3.11.16 on macOS arm64/POSIX**, without installing the upstream projects or
running their installation hooks. All 60 buggy checks failed and all 60 corresponding
fixed checks passed. These are offline behavior qualification results. They measure
neither autonomous model repair ability nor production readiness. No live provider
requests were made.

## Files and provenance

- `manifest.json` is the version 1 task contract.
- `archives.lock.json` pins all **58 unique source snapshots** to their official
  GitHub codeload ZIP URL, full commit SHA, compressed byte count and SHA256 digest.
- `checks/*_reproduction.py` are public checks that may be copied into a disposable
  repair workspace as `test_reproduction.py`.
- `checks/*_holdout.py` are independent grader checks. Keep them outside the
  model-visible workspace and context.
- `qualification.json` records every check's source pin, check SHA256, exit code,
  measured latency and final error line. Its hashes bind qualification to these
  exact checked-in scripts.
- `provenance.json` links each defect to the official fixing commit and each source
  snapshot to its original license file URLs and content hashes. The complete
  downloaded archives retain those upstream license files.
- `curation-notes.json` records rejected probe drafts separately from accepted tasks;
  there are zero blocked or excluded tasks in the final 30-task selection.
- `negative-controls.json` contains a deliberately incomplete source patch that
  passed the public reproduction and failed the independent holdout during curation.

The source archives and full qualification tracebacks are external evaluation evidence,
not vendored source. Fetch official archives explicitly, verify the lock digest, and
extract them with the evaluator's bounded regular-file checks. A digest mismatch is a
setup failure; do not silently update the lock or count it as a bug result.

## Manifest contract

`schema_version` is `1`; `tasks` is a list. Every task includes:

| Field | Meaning |
| --- | --- |
| `id` | Stable defect identifier; never a parameterized test variant. |
| `repo` | Exact official `https://github.com/owner/repo` URL. |
| `buggy_commit`, `fixed_commit` | Immutable full 40-character Git SHAs. |
| `summary` | Upstream defect description. |
| `license` | SPDX expression for the source snapshot. |
| `editable_paths` | Existing Python source files, relative to the **archive project root**. |
| `source_subdir` | Package **import root**, relative to the archive project root. It does not change the meaning of `editable_paths`. |
| `reproduction_file`, `holdout_file` | Script paths relative to `evaluations/python/`. |
| `notes` | Optional runtime or provenance detail. |

The evaluator removes exactly the archive's single top-level directory and prepares
that entire project root. For Click, for example, `source_subdir` is `src` and an
editable path is `src/click/core.py`. It sets `PYTHONPATH` to
`<prepared project root>/<source_subdir>` and executes the check with the project root
as its working directory. All scripts are standalone stdlib/assert checks; no pytest
dependency is needed in the task runtime. Their upstream imports must resolve to the
prepared snapshot, not to an installed package with the same name. Use Python without
`-O`, which would disable assertions.

The qualified package paths have no third-party runtime dependencies on POSIX. The
Click tasks exercise output formatting and `CliRunner`, not interactive terminal or
Windows behavior. Python versions other than 3.11 require a separate qualification run.

## Grading and controls

Only the public reproduction and allowed buggy source belong in repair context. The
reference-fixed archive, upstream patch, holdout scripts and this corpus's grading
metadata stay host-side. Grade changed source against both unchanged scripts. Require
the public reproduction and the holdout to pass, and preserve the source/test allowlist.
Equality with the upstream patch is not the success criterion.

For `more-itertools-batch-limits`, `negative-controls.json` adds only a `max_count == 0`
guard to `more_itertools/more.py`. That patch repairs the visible zero-count example,
but the holdout rejects negative counts too. This is an observed public-pass/holdout-fail
control, suitable for checking that public-only overfitting is not reported as success.
Require exactly one match of its `needle` before applying the replacement.

Known-patch replay can copy only the task's allowed source files from the fixed
snapshot to demonstrate evaluation plumbing. Some files are large, and the current
provider's full-file replacement format may exceed a live run's output limit. Replay
qualification alone does not establish that a task fits the configured live model
budget or that any model solved it.

With the project's development environment active, corpus metadata and script syntax
can be checked without network or upstream execution:

```sh
rtk proxy python -B -m pytest tests/test_python_corpus.py -q
rtk proxy ruff check tests/test_python_corpus.py evaluations/python/checks
rtk proxy ruff format --check tests/test_python_corpus.py evaluations/python/checks
```
