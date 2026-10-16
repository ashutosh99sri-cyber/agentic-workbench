# Recommendations 7 and 8: source-bound indexing and measured structural retrieval

Implementation contract for the user-authorized work, 2026-10-15. Baseline d8436762eb21f5690cf86239feb672c8069365c0.
Preserve the primary HEAD, index and every existing change. Keep the previous repair/release branches frozen.

## Capability map and order

| Module | Responsibility | Dependency |
|---|---|---|
| source-derivation | Separate existing safe inventory from per-file derived facts, preserving cold behavior | Existing repository/policy |
| incremental-index | Reuse bounded derived facts after fresh policy reads; share cache in MCP | source-derivation |
| typescript-structure | Optional trusted TypeScript/JavaScript AST and declaration relationships from approved snapshots | source-derivation |
| impact-context | Changed/explicit files, target definitions, callers and checks before lexical fallback | incremental-index, optional typescript-structure |
| combined-retrieval | Explicit rank fusion of current lexical/vector candidates; optional embeddings | Existing semantic search |
| understanding-evaluation | Fixed held-out targeting/repair tasks and cold/warm/change benchmarks | All above |

Implement repository seams first. Claude owns incremental-index and impact-context; Codex owns the parser, retrieval, integration and evaluations. No new agent controller or model-driven authority.

## Source derivation contract (Codex)

`collect_workspace(policy) -> RepositoryIndex` performs exactly the current bounded traversal, inherited ignore rules and safe source reads, returning current files and traversal coverage without derived parsing/chunks.
`index_source(source: SourceFile) -> RepositoryIndex` derives one file's existing manifest/Python facts, language and 60-line chunks, with parse-error contribution; it has no filesystem reads or subprocesses.
`merge_source(index, derived) -> None` appends derived lists and adds parse_errors; it never replaces fresh files or traversal coverage. `scan_workspace(policy)` composes these functions and deduplicates frameworks/languages, preserving the existing cold baseline.
Expose a constant `INDEX_ANALYSIS_VERSION`; all cached derivations bind it. Codex will add additive RepositoryIndex imports/references fields and structural metadata without changing Chunk identity or existing Python fact shapes.

## Incremental index contract (Claude)

`IncrementalIndexCache.refresh(policy, store) -> RepositoryIndex` always calls collect_workspace. Reuse per-file derivations only when path, raw source hash, redacted text hash, secret flag, configuration and analysis version agree. Changed files rebuild; deleted/ignored/unavailable files cannot contribute old facts. Metadata timestamps are never freshness authority.
Retain only current entries in memory. Durable cache is optional bounded acceleration in existing mutable `index` records; it must not grow one record per historical content hash. A single bounded snapshot/prefix is acceptable with explicit persisted/truncated counts. Never duplicate the security walker. Cache corruption/version mismatch causes a rebuild, not a trusted result. Reconstruct chunks from freshly read source, rather than trusting persisted source text.
Expose `cache_stats` on RepositoryIndex (additive presentation field) containing integer counts at least files_read, reused, rebuilt, deleted; timings may be separate metadata. Existing fingerprint continues to hash current raw source identities only. Do not add cache stats to source/config/approval authority.
Codex wires Workbench._scan to an optional host-supplied `index_cache: IncrementalIndexCache | None` (default fresh cache per Workbench), avoids rewriting index/current if unchanged, and retains existing projection bounds. Claude wires one shared cache per MCP Server and passes it into each short-lived Workbench. MCP still closes every Workbench and rechecks source policy on every call.

## Impact/context contract (Claude)

`impact(index, changed_paths: list[str], limit: int = 20) -> dict` is a pure bounded selector. Require nonempty existing indexed relative paths, no duplicates, at most 20 paths and limit 1..50. Return fingerprint, changed_paths, affected_paths, definitions, callers, tests, imports, references, truncated and honest static-analysis limitations. Every fact carries existing source-hash Evidence; tests remain identified textual references unless structural data proves a declaration link.
`select_impact_chunks(index, instruction, fresh_chunks, changed_paths=None) -> list[Chunk]` prioritizes target definitions in explicit/changed files, matching callers/references and selected checks, then lexical fallback. Keep relevant spans ahead of unrelated file prefixes and deduplicate. Never claim dynamic call-graph completeness.
ContextManager.build accepts optional `changed_paths: list[str] | None`; it uses the selector only when no host candidates are supplied. Preserve current critical decisions, dependency validation, actual indexed candidate identity, fresh evidence revalidation and complete serialized byte budgeting. Accept retrieval_mode="combined" only with supplied candidates, as with semantic mode.
Codex exposes Workbench.impact(paths, limit=20), context(..., changed_paths=None), CLI impact and context --changed-path. Host-supplied paths guide context, never grants or write authority. Source-bound decisions keep their existing lifecycle; no automatic promotion of retrieved text to instructions.

## TypeScript/JavaScript structure contract (Codex)

Use the already pinned TypeScript 7.0.2 native API through a fixed trusted bundled bridge, with an explicitly host-supplied trusted Node executable/module path. No ambient workspace module discovery, auto-install, workspace tsconfig/plugins, application import or application execution. Python-only installs keep lexical coverage with an explicit parser gap; selecting an unavailable/mismatched parser fails clearly.
The bridge receives only policy-approved bounded snapshots over stdin. Use a closed synthetic virtual filesystem: absent reads return null and absent directories empty entries, with no real-filesystem fallback. A fixed synthetic config loads only supplied paths and conservative compiler options. Bound process lifetime, memory, stdin/stdout/stderr bytes, source count/bytes, traversal and fact rows. Sanitize the process environment and disable inherited Node options/module paths.
Symbols retain name/kind/evidence and gain stable definition IDs and language. Calls retain callee/resolution/evidence and may gain target_id. New imports/references include module/imported/local or name, target_id, resolution and Evidence. Stable IDs derive from path/span/source hash, never native snapshot symbol IDs. A declaration link is not a runtime dispatch guarantee. Unresolved external packages, computed/dynamic references and ignored compiler options remain explicit limitations.
Validated structural facts enrich the freshly derived base index in the host SDK, outside repository.py. Cache a whole structural snapshot only against all relevant current raw/redacted hashes plus parser fingerprint; any source change invalidates cross-file resolution. Source bytes are never reopened by the parser. Update tools/agents to consume and freshness-check every new relationship; include ordinary `$` identifiers and preserve same-name ambiguity.

## Combined retrieval contract (Codex)

Preserve search(semantic=False/True). Add explicit mode="lexical"|"semantic"|"combined" without silently granting network. Contradictory legacy/new flags fail validation. Rank fusion combines deterministic current lexical/vector lists by Chunk identity, with stable ties, no fabricated vectors and no change to Chunk format. Disclose the bounded embedding candidate pool; vector mode is not full-corpus retrieval when source admission was bounded.
CLI --semantic and --combined are mutually exclusive. Embedding provider/model, grant, response validation, source revalidation, usage/unknown accounting and cache identity remain enforced. Additive context support accepts combined candidates. Embeddings remain opt-in; no paid calls/global credentials or accounts in this implementation.

## Evaluation and acceptance

Capture cold/warm/one-file-change/reopen/MCP scan counts and p50/p95 latency on the Workbench and pinned public Python/TypeScript source. Verify actual parse reuse and compare results to a cold scan; no timing-only flaky unit assertions. Test equal-size/equal-mtime edits, new/deleted/ignored files, exclusions, symlinks, bounds, redaction changes, cache corruption and stale citations/decisions/proposals.
Freeze held-out tasks before tuning. Include aliased imports, re-exports, namespace imports, shadowed names, JSX, JS/MJS, malformed source and unresolved/dynamic cases. Compare lexical, structural-impact, vector and combined targeting under equal k/byte bounds; record expected edited/caller/check paths and executable repair outcomes. Deterministic fixture-vector runs are controls, never measured semantic/model quality. Retain failures and missing coverage in denominators. If no credentialed embedding/model run occurs, live effectiveness remains unknown.
Reuse the actual repair Harness and independent checks for bounded supplied-candidate controls; source allowlists and exact approvals stay unchanged. Record source/config/parser/model pins, selected/context bytes, latency, attempts, reopens, usage and estimated costs; missing values are null. No claims of overall framework superiority from local controls.

## Ownership, commands and completion

Claude: index_cache.py, impact.py, context.py, mcp.py, focused new tests (test_index_cache.py/test_impact.py), necessary existing context/MCP tests, docs/indexing.md. New t/agentic-workbench-indexing worktree on claude/incremental-indexing from d843. Request before changes to StateStore; no shared module edits.
Codex: repository.py, sdk.py, cli.py, agents.py, tools.py, retrieval.py, optional parser/bridge/package-data, structural/retrieval/evaluation tests/scripts/fixtures, shared docs and final preservation integration. Native parser worker owns only its assigned bridge/module/tests/docs, not integration modules.
Use existing WorkbenchError/typed dataclass/dict conventions, Ruff and strict mypy. No new runtime dependency is currently required. Do not restore user-staged tasks/plan.md or tasks/todo.md deletions; this document records the plan.
Each behavior needs RED/GREEN regression evidence before commit, followed by integration and fresh focused review. Final gates: full offline tests (-W error), relevant real Docker/repair evaluations, Ruff/format, strict mypy, clean installed consumers, Node compatibility and original source/index preservation.
Commands: rtk proxy env PYTHONPATH=src /tmp/agentic-rec5-6-dev/bin/python -B -m pytest -m "not docker and not distribution" -q -W error; rtk proxy /tmp/agentic-rec5-6-dev/bin/ruff check src tests scripts; rtk proxy /tmp/agentic-rec5-6-dev/bin/ruff format --check src tests scripts; rtk proxy /tmp/agentic-rec5-6-dev/bin/mypy src/agentic_workbench.
