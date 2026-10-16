# Integrated audit remediation

The canonical integration branch is `fix/integrated-public-readiness`. It preserves
the latest primary development and merges `feat/developer-distribution`, so the
typed SDK, hidden credential prompt and consumer examples share the current runtime.
The original development checkout and its local tools were preserved. No public
remote, package release or paid provider call is part of this integration.

This ledger maps the eleven reported findings to the shared guard and regression
that must pass. Some guards were already implemented in the intervening primary
development; integration added missing boundary fixes and stronger regression proof.
Exact test counts, source commit and artifact hashes belong in the retained local
integration receipt. They must not be inferred from this table alone.

| # | Reported issue | Implemented behavior and regression |
| --- | --- | --- |
| 1 | `.envrc` reached indexed/provider context | Mandatory `.env*` exclusions precede reads. `test_envrc_never_enters_index_provider_context_or_persisted_state` checks the actual SDK payload and exported state. |
| 2 | Cancellation allowed the next tool/provider dispatch | `StateStore.intent` checks the task ancestry transactionally; registered tools check before lazy loading and each attempt; default read tools check their task before execution. `test_cancelled_task_tree_blocks_actual_next_provider_dispatch` covers root/child cancellation after a 429 and tool response; `test_cancellation_stops_lazy_loading_and_dispatch` covers the lazy factory boundary. |
| 3 | Replanning reused stale dependent results | Execution contract 4 binds the whole dependency operation chain and immutable result identities. `test_replan_recomputes_steps_whose_dependencies_changed`, transitive/renamed-chain and reopened checkpoint tests distinguish a new operation from replaying an unchanged or unknown effect. |
| 4 | Invalid MCP tool names killed serving | Names must be strings before lookup. `test_malformed_tool_names_return_invalid_params_and_serving_continues` checks invalid parameters followed by a successful ping. |
| 5 | Valid deep Python syntax crashed scanning | Bounded formatting and recursion handling record a coverage gap and retain other facts/files. `test_valid_deeply_chained_call_records_a_gap_and_scanning_continues` proves valid input, both indexed files and explicit parse coverage. |
| 6 | File cap skipped the collected prefix | Scanning processes the full collected prefix before reporting the cap. `test_file_limit_indexes_a_full_prefix_of_collected_entries` and the scale test assert exact counts. |
| 7 | Repository summary exceeded its fixed tool budget | Whole trailing entries are trimmed after redaction, retaining fingerprint, coverage and truncation status. `test_repository_summary_returns_a_bounded_prefix_of_whole_paths` and `test_read_tools_fit_after_redaction` check the 12,000-byte bound. |
| 8 | Large successful command output became unknown | Effect receipts validate the complete result then retain a bounded known projection. `test_command_output_over_context_limit_keeps_a_known_receipt` checks actual 13,001-byte stdout, exit status and durable replay after reopening SQLite. |
| 9 | Contradictory rejection triggered fallback | Fallback requires the latest dispatch's matching rejection receipt. `test_rejection_contradicting_its_receipt_never_falls_back` and `test_rejection_of_an_earlier_request_cannot_override_the_latest_received_request` reject contradictory/out-of-order receipts. |
| 10 | Invalid CLI override leaked the store | `_workbench` closes its newly opened SDK on override validation failure. `test_invalid_model_override_closes_the_opened_store` verifies closure. |
| 11 | Developer distribution and current runtime diverged | One merge preserves both histories. The wheel includes `py.typed`; installed mypy consumers accept valid SDK use and reject an invalid assignment. Hidden key entry fails closed, redacts output and restores the prior environment on every exit. CI/release run these consumers and the offline SDK walkthrough. |

## Agent acceptance

All eight roles have independently parameterized offline acceptance in
`tests/test_agents.py::test_independent_roles_persist_real_results` and installed
OpenAI SDK transport acceptance in
`tests/test_providers.py::test_each_role_uses_installed_sdk_and_persists_result_and_receipt`:
`discovery`, `intelligence`, `engineering`, `architecture`, `ux`, `testing`,
`documentation`, and `orchestrator`.

`test_explicit_eight_role_graph_uses_sdk_and_carries_cited_dependencies` checks the
coordinated dependency graph. The genuine SDK uses a mock HTTP transport, so these
tests establish adapter contracts, source evidence, state and usage receipts without
establishing live account access or expert reasoning quality. Independent actual
commands verify apply, test and rollback on disposable Python and TypeScript projects.

The installed `examples/sdk_walkthrough.py --execute` demonstrates source analysis,
an imported proposal, exact approvals, a failing then passing synthetic unittest and
byte-identical rollback. It does not run an LLM or independently exercise every role.

## Remaining boundaries

Cancellation is cooperative between callbacks; it cannot abort a handler/request
already executing. Deep static call facts may be omitted with a reported coverage
gap. Secret filtering cannot identify all confidential content. Trusted-host command
execution has no OS sandbox; Docker retains daemon/kernel/image trust. Guarded
mutation and command execution require POSIX; Windows support is read-only.

Passing local acceptance supports a supervised developer alpha. Public release still
requires the [owner and operational gates](public/READINESS.md), exact-commit hosted
CI and explicit approval of the destination and artifacts. Live model quality,
embedding relevance, cost savings and production application acceptance remain
separate measurements.
