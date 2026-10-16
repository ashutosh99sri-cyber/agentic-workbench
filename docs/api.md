# CLI and Python SDK

Normal output is one object: `{ "schema_version": 1, "ok": true, "data": {} }`. Errors use `{ "schema_version": 1, "ok": false, "error": { "code": "...", "message": "...", "retryable": false } }`. Help/version are ordinary argparse text. Exit codes: 0 success/review, 1 execution/provider/internal boundary failure, 2 input/configuration error, 3 policy/approval/staleness/conflict, 4 unavailable optional integration/backend. Test failure details are preserved in local execution records; `state export` exposes them. A `repair` that finishes with outcome `failed` still prints its full `ok` envelope, and exits 1.

| Command | Behavior |
| --- | --- |
| `init --root PATH` | Preserve/create application-owned config and private state |
| `scan --root PATH` | Offline inventory plus persisted discovery result |
| `explain TARGET --root PATH` | Cited intelligence result; TARGET is a file path or query |
| `plan INSTRUCTION --root PATH` | Persisted coordinated analysis and saved proposal IDs |
| `plan ... --proposal-file FILE` | Import a closed version 1 exact-edit proposal |
| `apply PROPOSAL_ID --root PATH` | Default review; exact `--approve DIGEST` writes |
| `apply --rollback CHANGE_ID --root PATH` | Default rollback review; exact approval restores eligible targets |
| `test --command-id NAME --root PATH` | Default Docker review; exact approval executes |
| `test ... --trusted-host` | Explicit weaker host review/execution backend |
| `run ROLE INSTRUCTION --root PATH` | Independently invoke any of the eight roles |
| `repair INSTRUCTION --command-id NAME --edit-path FILE.py --root PATH` | Bounded [Python repair](python-repair.md): approved baseline, provider candidate, exact `--approve-baseline`/`--approve`/`--approve-test` digests, `--max-attempts 1-4`, `--task-id` to continue |
| `status TASK_ID --root PATH` | Read historical task state and real results |
| `resume TASK_ID --root PATH` | Explicit resume with current pins and receipt checks |
| `search QUERY --root PATH` | Lexical cited source chunks |
| `search ... --semantic` | Configured embedding search; explicit network grant required |
| `search ... --combined` | Stable lexical/vector rank fusion over the same bounded embedding candidate pool; explicit network grant required |
| `impact PATH [PATH ...] --limit 20` | Source-cited affected definitions, callers, imports, references and tests for 1-20 indexed paths |
| `context QUERY --changed-path PATH` | Bounded context prioritizing target definitions and affected source/check spans |
| `state export --root PATH` | Export redacted local state; may include source backup content |
| `state prune --root PATH --days 30` | Review exact eligible records; exact approval prunes owned state |
| `mcp --root PATH` | Long-running MCP stdio server with scan/explain/search/plan/run/status/review tools; no envelope, no approvals |

`--dry-run` always prevents execution even when approval is supplied. Without `--approve`, apply/test/prune are reviews. Provider options are `--provider openai --model MODEL --allow-network`; semantic search also needs `--embedding-model MODEL`. Configuration cannot enable network authority on its own. A cached semantic index is bound to source/model/dimensions; source changes invalidate it.

Import `Workbench`, `Config`, `CommandConfig`, `Grant`, `Node`, `Evidence`, `AgentResult` and `WorkbenchError` from `agentic_workbench`. Use Workbench as a context manager, or call `close()`. `scan`, `explain`, `plan`, `run_agent`, `orchestrate`, `search`, `task_status`, `resume`, `propose`, `review`, `apply`, `review_rollback`, `rollback`, `test_review`, `test` and `cleanup_tests` are host APIs. `wb.store` exposes explicit local memory/state methods for trusted SDK code.

```python
from agentic_workbench import Grant, Node, Workbench

with Workbench("/absolute/path/to/application", grants=Grant(write=True)) as wb:
    workflow = wb.orchestrate("Review public API", [
        Node("discover", "discovery"),
        Node("review", "architecture", ("discover",)),
    ])
    # A real imported/provider proposal is needed before apply.
    for proposal_id in workflow["proposal_ids"]:
        print(wb.review(proposal_id)["diff"])
```

`apply` defaults `dry_run=True`. To supply host approval use its explicit `approval` digest or a host callback `approve(review)` and `dry_run=False`. The callback is trusted application code and must make a real approval decision; never expose it to a model. Test execution needs `Grant(execute=True)` plus `Grant(trusted_host=True)` for the host backend. No method commits/pushes target Git changes.

Custom providers implement `Provider.analyze` and optional `EmbeddingProvider.embed`, with injected executor/budget/intent protocols in `providers.py`. They are explicit trusted SDK extensions. They own transport security and must preserve usage, intent, structured-output and tool boundaries. No repository-controlled plugin autodiscovery exists.
# Harness APIs

`Workbench.execute(instruction, proposal_id=None, command_id=None, approval=None, test_approval=None, backend="docker", task_id=None)` runs the built-in workflow. A selected proposal requires a verification command; missing exact approvals return `awaiting_approval` with reviews. `Workbench.repair(instruction, *, command_id, edit_paths, baseline_approval=None, approval=None, test_approval=None, backend="docker", task_id=None, max_attempts=2)` reproduces a failing configured command, then tries bounded provider candidates, each applied and checked only with its exact approval; see [Python repair](python-repair.md) for its lifecycle and result. `harness(planner, executor, verifier, pins, limits, replay_safe_actions)` accepts typed host callbacks for dynamic engineering workflows. `cancel`, `trace`, `tools`, `context`, `remember_decision` and `decisions` expose control and context. See the [harness guide](harness.md) for permission, resume and verification semantics. `ProviderRegistry` and `ModelRegistry` accept explicit trusted adapter registrations; `configure_tools` receives a host registry, and project configuration cannot register executable modules.

## Source indexing and structural adapters

`Workbench(..., index_cache=IncrementalIndexCache(), typescript_analyzer=TypeScriptAnalyzer(node_path, package_path))` accepts explicit trusted host objects. Import the classes from `agentic_workbench.index_cache` and `agentic_workbench.typescript`. Each Workbench owns a cache by default; MCP shares one across its short-lived SDK instances. `scan()["cache_stats"]` reports fresh reads and reused/rebuilt/deleted derivations. Persistence keeps at most one bounded derived-fact record and never treats it as authority to skip reads. Unchanged index/current projections are not rewritten.

`wb.impact(["src/app.ts"], limit=20)` returns fingerprint, changed_paths, affected_paths, definitions, callers, imports, references, tests, truncated and limitations. Python call relationships match source names; the configured native TypeScript adapter follows declaration IDs through local aliases/re-exports. External libraries, dynamic dispatch, compiler path aliases and ignored workspace compiler options remain explicit limits. All facts retain raw-source hash Evidence. A fresh inventory detects changed, removed and newly added resolution files before a trace is accepted.

`wb.context(query, changed_paths=[...])` changes selection priority without granting execution or write authority. `ContextManager.build(..., retrieval_mode="semantic" | "combined", candidates=[...])` accepts host-ranked chunks only when they match current indexed identities; it preserves the normal byte budget, source freshness and critical decisions.

`wb.search(query, mode="lexical" | "semantic" | "combined", dimensions=256, limit=5)` retains legacy `semantic=True`. A conflicting explicit mode is rejected. Semantic and combined modes require a trusted embedding provider, network grant and existing request/token/cost budgets. The candidate pool is bounded by existing lexical relevance and file diversity; neither mode claims full-corpus vector coverage. Real embeddings remain optional, and unavailable model evaluation is reported as unavailable rather than a zero-cost quality result.

CLI structural selection uses both `--node-executable ABSOLUTE_PATH` and `--typescript-package ABSOLUTE_DIRECTORY`; the latter must be a trusted TypeScript 7.0.2 installation. These options also apply to MCP. No target package/config/plugin discovery or automatic install occurs. The bundled bridge is shipped in the Python wheel/sdist. See [indexing](indexing.md), [parser boundaries](typescript-analysis.md), and the [fixed-target evaluator](../evaluations/understanding/README.md).
