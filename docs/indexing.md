# Incremental indexing and change impact

Every scan reads the workspace fresh. Within that, the workbench avoids redoing per-file analysis that cannot have changed, and it can tell you what a change to some files reaches: the definitions in them, the code that calls or imports them, and the tests that mention them.

## Incremental indexing

`Workbench` keeps an `IncrementalIndexCache` (`wb.index_cache`) and refreshes it on every scan.

- **Every refresh reads every file.** Each refresh walks the workspace under the full policy and reads every file again: exclusions, ignore rules, size and count bounds, raw-byte hashing, and secret redaction. Nothing is skipped because it looks unchanged, and timestamps are never consulted.
- **What gets reused.** Only per-file analysis is reused: Python symbols and calls, manifests, frameworks and languages. A file's analysis is reused only when its raw source hash, its redacted text and its secret flag all match. The workspace, configuration and analysis version must match too.
- **What forces a rebuild.** An edit forces a rebuild, even one that keeps the same size and timestamp. So does a change in what redaction hides, or any configuration change. A deleted, newly ignored or unreadable file contributes nothing.
- **Chunks are never reused.** Retrieval chunks are always rebuilt from the freshly read text, so no stored text is ever shown as source.
- **What the durable copy holds.** A bounded copy of the analysis is kept in one mutable `index/derived` state record, at most 900 KB, so a reopened workbench also starts warm. It holds facts and citations but no source text, and it records how many files it kept (`persisted`) and dropped (`truncated`).
- **Bad records are rebuilt.** A persisted entry is reused only if every fact is well formed and cites that file's current hash and real line numbers. Anything corrupt, tampered or from another analysis version is rebuilt, never trusted.
- **Cache counters.** `cache_stats` on the scanned index reports `files_read`, `reused`, `rebuilt`, `deleted`, `persisted` and `truncated`. These counters describe the cache only; they are not part of the index fingerprint or of any approval.

The MCP server (`agentic mcp`) keeps one cache for its lifetime. Each tool call still opens its own workbench, rereads the source under policy and closes it. Repeated calls on an unchanged workspace skip re-analysis, and an edited file is analysed again on the next call.

## Change impact

`wb.impact(paths, limit=20)`, `agentic impact PATH... [--limit N]`, and the read-only MCP `impact` tool take 1–20 distinct indexed files and a limit of 1–50 per list. They return:

- `definitions`: the symbols defined in those files.
- `callers`, `imports`, `references`: uses in other files, each with a citation.
- `tests`: checks that mention the changed definitions. `link` is `declaration` when a resolved import or reference proves the link, including an alias such as `import { total as sum }`, and `textual` for a whole-word match in a file whose path names a test.
- `affected_paths` (the other files reached), `fingerprint`, `truncated` and `limitations`.

Where the index has declaration IDs (TypeScript and JavaScript through the [TypeScript analysis](typescript-analysis.md)), uses are linked by ID, so aliased imports and shadowed names resolve correctly. Python calls without such a link are matched by name, so a same-name function elsewhere can appear. Dynamic dispatch, reflection, computed names and unresolved calls are not followed. Impact is a static guide to what to read and check, not proof of runtime behavior.

Changed paths only guide analysis. They grant no permission and authorize no write.

## Impact-guided context

`wb.context(query, changed_paths=[...])` and `agentic context QUERY --changed-path PATH` rank retrieved source in this order:

1. the definitions in the changed files, or in files the query names (those the query mentions come first);
2. relevant lines in those files;
3. callers, imports and references;
4. tests;
5. ordinary lexical matches;
6. the rest of the changed files.

Without changed or named files, ranking is the ordinary lexical search. Host-supplied candidates (semantic or `combined` retrieval) are used as given, with their identity and freshness still checked. Every retrieved span is re-checked against the current source and fits the context byte limit.
