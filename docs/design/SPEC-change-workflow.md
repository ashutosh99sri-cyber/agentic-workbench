# Specification: change-workflow

Depends on `execution-state`, `repository-index` and `workspace-policy`.

## Objective and contract

Turn proposed source changes into exact, reviewable, recoverable operations. A `ChangeProposal` has schema version, workspace identity, task/instruction references, policy/configuration/skill hashes, rationale, cited evidence and a bounded ordered set of file edits. An edit has relative path, expected base hash or null for creation, full UTF-8 replacement content or an explicit deletion operation, and resulting hash. No fuzzy patch application.

Proposal creation validates every path/content/size, protects credential/state/vendor files and generates the actual before/after diff. Replacing a file containing detected secrets is prohibited. Default maximum: 20 edits and 1 MiB total proposed content. Proposals persist privately; their content is immutable after creation. An edited proposal becomes a new proposal with a new digest.

Human approval is bound to the canonical proposal digest, workspace, base hashes, policy/configuration and relevant skill versions. The CLI accepts an explicit `--approve DIGEST` for one exact apply invocation; the SDK requires a host-supplied approval callback/record. LLM tools cannot create or consume approval authority. Dry-run verifies current eligibility and returns the review without approval consumption or source writes.

Before application, take the single-writer workspace lock, verify all expected hashes and create a durable journal of original content/modes and intended results. Use POSIX directory-relative no-follow operations, staged files, fsync and atomic per-file replacement. Recheck parent/target identities before each write. Multi-file application is journaled, not represented as an atomic filesystem transaction.

If an error occurs, restore only files still matching this operation's recorded resulting hash. On process interruption, mark the journal recovery-required; never silently complete or replay a partly applied operation. Recovery/rollback preflights every target, refuses later user edits, and restores/deletes only recorded changes. A new rollback review/digest requires explicit approval. Created directories may be removed only when recorded and empty.

## Structure and style

Own `changes.py`, `writer.py`, `tests/test_changes.py` and `tests/test_recovery.py`. Pure proposal validation/diff code is separate from the guarded filesystem writer. API methods: `propose`, `review`, `apply`, `review_rollback`, `rollback`; no general-purpose write-file tool.

## Commands and verification

`uv run --locked pytest tests/test_changes.py tests/test_recovery.py`. End-to-end CLI forms: `agentic apply PROPOSAL_ID --root PATH --dry-run --json`; after explicit review, `agentic apply PROPOSAL_ID --root PATH --approve DIGEST --json`; rollback: `agentic apply --rollback CHANGE_ID --root PATH --dry-run --json`, then repeat with the reviewed rollback digest.

## Success criteria

- Dry run leaves source unchanged; unapproved/stale/tampered/forbidden proposals fail before writes; the approved exact change applies once.
- Traversal, symlink/hard-link swaps, conflicts and concurrent writers are rejected; unrelated changes remain intact.
- Fault injection before/after each journal/write step yields honest recovery state; rollback restores only matching recorded content and protects subsequent user edits.

## Boundaries and open questions

Always bind approval to content and current base/policy state. Ask before changing mutation platforms, deletion scope or rollback policy. Never stage, commit, push, merge, deploy, modify credentials or overwrite a conflicting later edit as part of source application.
