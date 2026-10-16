# Public-preview assessment

Reviewed 17 October 2026. Runtime candidate:
`4a1f8c56239bb3b63bbf82b6bec543f72dc82222`.

The project is an **experimental, supervised developer toolkit**. It is not
certified for reliable autonomous heavy engineering tasks. The owner approved
the Apache-2.0 current-source preview, WOOKhoop brand rights, public destination,
maintainer responsibility and private conduct contact on 17 October 2026.
[Readiness](READINESS.md), [licensing](LICENSING.md) and
[maintainer setup](../../MAINTAINERS.md) distinguish this source preview from
future tagged or registry releases. Follow the actual
[hosted CI results](https://github.com/ashutosh99sri-cyber/agentic-workbench/actions/workflows/ci.yml).

## Verified local acceptance

- All 23 acceptance gates passed: 975 offline Python cases, eight Docker cases,
  three unique distribution cases repeated against clean Python 3.11 wheel and
  Python 3.12 source consumers, SDK walkthroughs, Node integration, lint, format,
  strict typing, harness controls, and example targeting.
- The resulting total was 986 unique Python cases, 989 executions, zero skipped
  cases and 88.83% executable-line coverage. The Node adapter's 13 tests passed.
- Discovery, intelligence, engineering, architecture, UX, testing, documentation
  and orchestrator passed static installed-package checks and official OpenAI
  SDK tests using mocked HTTP transport. An eight-role graph, persisted results,
  reopen/resume and application-source preservation passed.
- Dependency advisory checks reported zero known vulnerabilities for the
  audited 37 Python packages and 23 npm dependencies. Advisory results are
  time-dependent and do not establish absence of unknown vulnerabilities.
- All 59 tracked runtime files matched the tested wheel byte for byte. The
  source/context change preserved the other 58 package source/data files and
  existing policy, secret filtering, permissions, exact approvals, guarded
  writes, command isolation, recovery and rollback controls.

## Retrieval correction and measured limits

The before/after runtime pair was `12d4b3b` and `4a1f8c5`. Each pair used the same
frozen source/manifest/anchors, five repetitions, six citations and 16,000
selected-source JSON bytes. Evaluation metadata isolation was explicit and
identical for both versions. Selection measures source-anchor coverage rather
than generated answer or repair quality.

| Changed-path dataset | Complete tasks before / after | Anchor hits before / after |
|---|---:|---:|
| Original six | 2/6 / 2/6 | 10/22 / 11/22 |
| Earlier diagnostic eight | 7/8 / 7/8 | 26/28 / 27/28 |
| Regression eight | 5/8 / 8/8 | 22/25 / 25/25 |
| New independent holdout eight | 0/8 / 8/8 | 24/32 / 32/32 |

Query-only citations were identical in all 30 comparisons. That preserves the
previous query improvements and their existing gaps: complete query coverage was
1/6, 7/8, 4/8 and 0/8 respectively. The new holdout was frozen before scoring;
the candidate was not tuned on its results. Embedding modes remained unavailable
without real embeddings. Complete prompt packing can still clip selected text;
large or partly available changed definitions retain compact fallback.

Seven alternating process-order pairs measured 21 six-example static workflow
runs per runtime. The median was 239.23 ms before and 239.61 ms after. The
changed-path selector's 8,000-call control measured 4.845 and 4.859 ms. These local
observations establish no general speedup or live inference latency claim.
Synthetic 100/1,000/5,000-file workloads measured scan, search, edit and reopen
operations. The bulk 1,000-file reopen run had a slower candidate median; a focused
alternating follow-up did not reproduce the larger delay. Its cause is unresolved.
The scan implementation was unchanged; all cache reuse/rebuild results were
retained rather than excluded.

## Publication status

The reviewed source has no tracked local state, environment directory or
dependency installation. No actual credential was established in the recognizable
credential-pattern matches; they were synthetic redaction test material.
This is a limited pattern review, not a guarantee against unknown secret formats.
The review of runtime candidate `4a1f8c5` covered 31 reachable commits. The owner
chose a current-source snapshot. Prior commits, the historical local developer
path and old author metadata were not imported. Original development history is
preserved locally; [runtime provenance](SOURCE-PROVENANCE.json) binds the inherited
source files to the tested development runtime.

The distribution remains Apache-2.0 for original contributions with retained
third-party notices. The owner confirmed distribution and WOOKhoop brand rights;
tests do not independently establish legal ownership. The repository is
[ashutosh99sri-cyber/agentic-workbench](https://github.com/ashutosh99sri-cyber/agentic-workbench).
The owner is its maintainer, GitHub private vulnerability reporting is enabled,
and the separately authorized conduct contact is in
[CODE_OF_CONDUCT.md](../../CODE_OF_CONDUCT.md). Actual hosted results remain
visible in Actions. No registry release or stable support promise is established.

Live model answer/repair quality, inference latency, token costs, cross-project
adoption and autonomous heavy-task effectiveness remain unmeasured. Use bounded
tasks, inspect citations/truncation and retain behavioral tests and human review.
