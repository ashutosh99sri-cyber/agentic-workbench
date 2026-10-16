# Specification: repository-index

Depends on `workspace-policy` and transitively on `core-contracts`.

## Objective and contract

Produce a bounded, source-grounded repository inventory and retrieval index without running project code or fetching dependencies. `scan_workspace(policy)` returns framework evidence, file metadata/hashes, dependency manifest facts, source chunks, symbols, static call edges, coverage exclusions and an index fingerprint. Consumers persist the result through execution-state; this module does not import state or provider modules.

Initial manifest detection covers Python, Node/TypeScript, Go, Rust, Java, .NET, Ruby and PHP. Framework labels require actual manifest/import evidence: examples include Django/FastAPI/Flask, React/Next/Vue/Express, Spring, Rails and Laravel. Unknown or ambiguous manifests remain explicit. Detection does not imply that every stack has a language-specific compiler analysis.

Honor nested `.gitignore` rules using `pathspec`, then mandatory policy exclusions. Excluded parent directories remain pruned. Default limits: 10,000 files, 512 KiB per source file, 50 MiB total scanned source, and bounded manifest/source parsing. Binary, undecodable, inaccessible, excluded and oversized files are counted as coverage gaps. Sort results deterministically.

Python AST extraction identifies functions, classes, imports, direct call expressions and source spans. Calls that cannot be statically resolved remain unresolved. Other languages use language-neutral line chunks and manifest detection; no runtime execution trace or compiler completeness is claimed.

Lexical retrieval uses deterministic token ranking with stable tie breaks and returns source citations. Vector retrieval accepts validated embedding vectors from the coordinating runtime, uses cosine similarity and binds vectors to chunk hashes, provider, model and dimensions. It never labels lexical retrieval semantic. Changed/deleted source invalidates stale citations and vectors.

## Structure and style

Own `repository.py`, `retrieval.py` and relevant fixtures/tests. APIs return typed data; no subprocesses, dependency installs or provider calls. Example: `index.search("invoice rounding", limit=5)` returns bounded cited chunks.

## Commands and verification

`uv run --locked pytest tests/test_repository.py tests/test_retrieval.py`; installed CLI: `agentic scan --root examples/python_app --json` and `agentic scan --root examples/typescript_app --json`.

## Success criteria

- Both example stacks are detected from evidence; nested ignore rules, secret paths and declared scan limits are respected.
- Python symbol/call results match controlled fixtures; unresolved/dynamic behavior is accurately labelled.
- Lexical and vector tests have separate evidence; malformed, mismatched and stale vectors/citations fail safely.

## Boundaries and open questions

Always report coverage and hashes alongside findings. Ask before adding executable parsers or expanding source/network scope. Never execute project manifests, import repository modules or infer runtime scalability/security from framework names alone.
