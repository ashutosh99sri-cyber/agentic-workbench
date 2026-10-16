# Source context selection

Default lexical search and agent context use the same deterministic selector.
This is lexical retrieval augmented by static source relationships; it is not
model inference, semantic embeddings or proof that every needed source was found.

## Selection contract

1. Start from policy-approved indexed chunks whose source hashes are current.
2. Prefer explicitly supplied changed paths, paths mentioned in the question, or
   exact named symbols. Otherwise infer a small set of code files from lexical
   matches with indexed declarations.
3. Rank declarations by named identity, query overlap and lexical position.
   Select across files instead of draining every chunk of one large definition.
4. Retain complete definitions of up to 60 lines; build compact declaration
   windows and terminal-body windows for long
   definitions. Follow selected declaration IDs for resolved callers, references
   and imports **before** applying relation limits. Python's unlinked calls retain
   their documented name ambiguity.
5. Balance declarations, non-test users and checks in the early selection.
   Prefer actual calls over references/imports and retain short check bodies;
   long checks prioritize actual-use windows.
   Query-matched test source remains available where structural facts are absent.
   Target body windows precede lower-specificity lexical detail.
   For explicitly supplied changed paths, keep complete fresh indexed body chunks
   when those chunks and the direct callers/checks fit the first six citations.
   Native parameters and local variables use their enclosing function, method or
   variable/property initializer (including arrows) for this edit-specific
   selection. Larger bundles or partially available bodies retain
   compact selection. Query-only ranking is unchanged by this edit-specific rule.
6. Pack complete context with fair capacity across the first six candidates,
   then refill skipped or clipped early citations from unused capacity before
   adding lower-ranked detail. Required skills, dependency identities,
   critical decisions, adapter measurement and the final byte bound retain their
   existing fail-closed behavior.

Windows contain contiguous real source: up to 60 lines for modest definitions
and checks, compact windows of at most 24 lines for larger bodies. Small files
may retain their complete available span. Every window remains within the
union of the supplied fresh spans. It preserves original raw-source SHA-256,
relative path, exact redacted text and correct line bounds. No disjoint lines are
presented as a contiguous excerpt.

Complete changed-body bundles reuse original indexed chunks rather than widening
compact excerpts. The context packer still enforces the complete serialized byte
bound: six candidates fitting the selection limit does not imply that all their
text fits a particular prompt budget. Inspect clipping and omitted candidates.

The existing raw 60-line index and embedding candidate identities remain unchanged.
Host-supplied context candidates still require actual indexed identities; invented
text is not accepted. The public lexical mode continues to mean local retrieval
without embeddings; its ranking now includes these structural hints.

## Limits and authority

Selection improves early source diversity, not completeness guarantees. Large
or ambiguous tasks still need decomposition, more targeted reads and independent
behavior checks. Tiny budgets, very long lines, unresolved dispatch and policy
omissions can leave useful context unavailable. Inspect context truncation and
coverage instead of assuming an agent saw an entire repository.

Selection never grants a tool, network access, source writes, command execution
or approval. Known-secret redaction and the native parser's secret-file omission
remain intact. Extra snippets cannot introduce stale or excluded sources. Model
candidates remain saved proposals; apply, test and rollback still require their
separate exact current digests and host grants.

## Evaluation

Independent synthetic regressions cover long bodies, multiple target files,
symbol-only questions, current redacted spans, stale sources, bounded packing and
same-named native declarations. The existing six-task evaluation manifest and
target anchors remain frozen.

The evaluator's optional --isolate-evaluation-metadata selects the declared
policy-bounded-without-evaluation-metadata-v2 dataset, excluding only the exact
workspace-relative evaluations/understanding/ subtree. It records omitted hashes
and copied-source identity. Legacy policy-bounded-v1 remains the default. This
is explicit evaluation dataset selection, not a runtime exclusion or gold-aware
ranking rule. Compare baseline/candidate with the same evaluator, source inputs,
protocol, anchors, chunk count and byte bound. Retain failed and unavailable rows.

A separate frozen corpus must be scored after the selector is fixed, without
tuning on its results. Neither static targeting nor supplied-patch replay measures
live-model quality, autonomous repair effectiveness or production readiness.
