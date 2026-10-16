# WOOKhoop public-release readiness

## Public source-preview decision: 17 October 2026

The owner approved publication to
[ashutosh99sri-cyber/agentic-workbench](https://github.com/ashutosh99sri-cyber/agentic-workbench)
as a current-source snapshot under the existing Apache-2.0 terms, confirmed
original-code/documentation/example/WOOKhoop distribution rights and accepted
maintainer responsibility. Prior development history stays local. Runtime file
hashes are retained in [source provenance](SOURCE-PROVENANCE.json).

The real owner/CODEOWNERS and support records are configured. GitHub private
vulnerability reporting was enabled and verified through its API; the owner
separately authorized the private conduct contact in
[CODE_OF_CONDUCT.md](../../CODE_OF_CONDUCT.md). See the
[actual hosted checks](https://github.com/ashutosh99sri-cyber/agentic-workbench/actions/workflows/ci.yml)
for current remote acceptance. The local results below do not substitute for
hosted results. Registry publication, a tagged release, stable support and live
model heavy-task effectiveness remain separate, uncompleted gates.

The dated prepublication reviews below are historical records; their earlier
unresolved owner/history/contact statuses are superseded by this source-preview
decision, not by the local test counts.

## Prepublication check: 17 October 2026 (retained)

Runtime `4a1f8c56239bb3b63bbf82b6bec543f72dc82222` passed 23 local acceptance
gates, including 986 unique Python cases and 13 Node tests. All eight agent roles,
clean installed consumers, approved Docker checks, and the changed-path correction
were verified. The [public-preview assessment](PUBLIC-PREVIEW.md) records the new
retrieval results and remaining limits. These results supersede the older runtime
counts below; they do not establish live model effectiveness or hosted CI.

That runtime candidate and its 31 reachable commits were checked for recognizable
credential formats, tracked private state, and relative Markdown links. The
credential-shaped matches were synthetic redaction fixtures. One historical
local developer path remains a history/privacy decision for the owner. No history
was rewritten, no remote was created, and no source was made public by this check.

**Public-preview code preparation is sufficient for owner review. Publication
remains blocked on the existing owner rights/history decision, verified private
reporting channels, responsible maintainer configuration, and hosted acceptance.**
The critical gates below remain active; a local test pass does not close them.

## Retained earlier publication review

Publication gates reviewed 16 October 2026. **Decision: do not publish yet.** The implementation is a useful local alpha for supervised engineering work. Technical preparation does not establish ownership, operational support or approval to make it public.

## Integrated remediation candidate

The canonical `fix/integrated-public-readiness` branch combines the latest primary
runtime with `feat/developer-distribution`. The eleven audit issues are tracked in
[the remediation ledger](../audit-remediation.md), with regression identities and
consumer checks. This supersedes the earlier branch split; it does not supersede
the ownership, maintainer, hosted CI or publication gates below. Fresh local results
belong to the exact-commit integration receipt, not the older retained baseline.

## Prior review scope

The review covered the actual Python runtime, CLI and SDK, Node adapter, MCP server, skills, schemas, tests, examples, dependencies, documentation, CI/release workflows and reachable Git history. The implementation baseline is `1e21f8a532ba7167dad26e8875a54ce487d03542`; this documentation candidate adds branding, guides and release notices without claiming new agent behavior.

The working repository contained 268 canonical files and 30 numbered copies. The copies were preserved in the original checkout and excluded from the isolated release candidate. All 144 reachable commits were considered in history/privacy checks; the candidate branch and original checkout have different ancestry. A current-source export is an option for owner review; no history was rewritten.

## Critical release gates

These are publication blockers, rather than confirmed critical code vulnerabilities.

| Gate | Required evidence | Status |
| --- | --- | --- |
| Ownership and rights | Owner confirms rights to original code, skills, examples, documentation and WOOKhoop assets, including employment, client and contributor restrictions | Unresolved |
| Responsible operation | Named maintainers accept responsibility; a real private vulnerability-reporting channel is verified; support expectations are published | Unresolved |
| Exact release approval | Review the final source/artifacts and history choice; confirm destination and package ownership; explicitly approve making the named repository public | Not approved |

No GitHub destination, public package registration, maintainer email or guaranteed response time is invented in these documents. WOOKhoop.com is a verified brand website, not an established security-reporting endpoint.

## Security and privacy findings

No real embedded credential was established in the reviewed current-source or reachable-history pattern matches. The inspected matches were synthetic redaction tests and example fixtures. The history pattern pass examined 643 reachable blobs, approximately 6.14 MB; it did not cover ignored local state, unreachable Git objects or every possible secret format. No discovered credential was exercised against a service.

A separate static security review found **zero confirmed vulnerabilities in reviewed paths**. Its overall coverage is **partial**: 20 core modules were read in the baseline review and 13 additional modules in focused review, with related tests and documentation inspected as needed. Most tests, scripts, documentation, schemas and numbered copies were searched or used as context rather than read completely for security. This is not penetration testing, certification or proof that vulnerabilities are absent.

The reviewed design has root/path confinement, explicit host grants, operation-specific approval, source/digest checks, redaction, bounded command output, SQLite receipts and recoverable change journals. These controls still require a trusted local operator. Python callbacks and trusted-host execution are not OS isolation. Docker requires trust in the daemon, kernel and approved image. Private state, model inputs and tool results can contain sensitive information.

Historical documentation contains a local developer path; commit history also identifies its author. The owner must decide whether to expose that history or publish a reviewed current-source snapshot. Existing history and local files were preserved. Keep `.agentic/`, credentials, evaluation traces and unrelated output folders out of a public export.

Fresh local advisory checks reported no known vulnerabilities for 37 audited Python packages and 23 audited npm dependencies. Advisory results are time-dependent and do not establish application security.

## Important issues and preparation

| Issue | Preparation / remaining action |
| --- | --- |
| Third-party attribution | Add conservative MIT notices for the Ponytail-adapted engineering skill and the small more-itertools evaluation fixture. Include notices in Python distributions. See [licensing](LICENSING.md). |
| Dependency redistribution | Preserve component licenses. `pathspec` is MPL-2.0; distributing an environment, image or executable bundle needs its own notice/source review. Three conditional locked packages were unavailable locally for license verification. |
| Public history and duplicates | Review the historical path and author metadata. Use the isolated candidate or its clean source export; do not stage the entire dirty development checkout. |
| Hosted compatibility | CI workflows exist, but this local review does not establish successful GitHub-hosted runs, configured required checks, registry ownership or protected branches. |
| Product effectiveness | Live model repair quality, embedding retrieval quality, review-time savings and cost effectiveness remain unmeasured. |

## Retained implementation evidence

The following results belong to the implementation baseline above, before branding changes. They are retained evidence, not new runs on every documentation edit.

| Check | Observed result and scope |
| --- | --- |
| Offline Python suite | 869 passed, zero selected skips; nine Docker/distribution tests excluded from that selection |
| Actual Docker | Eight separate passing cases, including confinement/cleanup and unusable baseline handling |
| Installed consumers | Clean wheel on Python 3.11 and sdist on Python 3.12; approved repair and understanding smoke checks passed |
| Node adapter | Build, 12 protocol tests, one installed-CLI integration test and example type checks passed locally on Node 26.7 |
| Historical repair corpus | Known supplied patches verified 28 of 30 selected defects; two setup/policy blocks retained. This measures workflow/patch verification, not model patch discovery |
| Context evaluation | Lexical selection found 5/22 exact anchors and impact selection 8/22; both covered all anchors on 0/6 tasks. Impact received changed-path inputs, so this is not an equal-input comparison |
| Editor interoperability | Claude Code 2.1.300 connected and listed eight tools. Separate protocol tests exercised search and denied apply. No actual editor `tools/call` was established |

Final documentation/package acceptance is recorded separately in the local delivery receipt. Do not present these results as a benchmark against other coding tools.

## Optional follow-up

Run representative live repair evaluations with retained failures and independent behavior checks; test real embeddings; observe unfamiliar developers completing onboarding; and verify real editor calls on each supported host. These are useful next milestones, not conditions that justify inventing performance claims today.

See [publication checklist](PUBLICATION.md), [roadmap](ROADMAP.md), [support matrix](../support-matrix.md) and [security policy](../../SECURITY.md).
