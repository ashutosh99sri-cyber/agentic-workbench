# Specification: delivery-validation

Depends on all preceding modules.

## Objective and contract

Deliver an installable, documented, tested local Git repository with reproducible dependencies and honest readiness evidence. Proposed license: Apache-2.0 for newly authored source. Initial target release: 0.1.0; tagged release metadata and generated package version must agree. No PyPI/npm publication, GitHub push or hosted deployment is part of local delivery.

Use `pyproject.toml`, a `src/` layout, setuptools/setuptools-scm packaging, optional OpenAI extra and a single authoritative `uv.lock`. The repository's isolated `.venv` is managed with `uv sync --locked --all-extras`; consumer wheel installation remains ordinary pip-compatible. Runtime dependencies are JSON Schema validation and gitignore matching; SQLite, argparse, AST, hashing and event logging use the standard library. Development dependencies cover pytest/coverage, Ruff, mypy, build checks and dependency audit. Node adapter dependencies and package manager have their own independent committed lockfile.

The current registry baseline observed during design is jsonschema 4.26.0, pathspec 1.1.1, openai 3.29.0, pytest 9.1.1, Ruff 0.17.0, mypy 2.4.0, build 1.6.1 and setuptools 84.0.0. Final compatibility/transitive versions come from the reviewed locked installation, not from this observation alone. Do not silently substitute a major SDK API.

Ship two disposable examples: a Python task service with a real regression test, and a TypeScript/Node application with real tests and UI-source evidence. The implementation acceptance flow scans both, coordinates agents, creates a real proposal, verifies denial/dry-run, explicitly approves the exact change, executes relevant tests and verifies rollback/conflict behavior. Examples contain no real credentials or user data.

CI jobs cover Python 3.11–3.14 on Linux, macOS core/mutation tests, Windows read-only/interface tests, Node adapter build/integration, locked dependency audit, package build/install and Linux Docker isolation tests. Actions are pinned to verified commit SHAs; permissions default to contents:read; secrets are absent from ordinary CI. Release workflow is manual/tag-triggered verification and artifact assembly, without configured automatic publication.

Required documents: README, installation tutorial, architecture diagram, SDK/CLI contracts, agent/skill authoring, security/threat model, state/recovery and rollback behavior, examples, contribution guidelines, changelog and release checklist. Every claimed capability links to code and evidence. The final validation report includes exact commands, versions, results and unavailable/unperformed checks.

## Structure and style

Own `pyproject.toml`, `uv.lock`, `README.md`, `docs/`, `examples/`, `scripts/`, `.github/workflows/`, `LICENSE`, `CONTRIBUTING.md`, `SECURITY.md`, `CHANGELOG.md` and delivery tests. Examples/docs must invoke supported commands and use clearly marked configuration fields, not fictitious completed outputs.

## Commands and verification

`uv sync --locked --all-extras`; `uv run --locked pytest`; `uv run --locked ruff check .`; `uv run --locked ruff format --check .`; `uv run --locked mypy src`; `uv build`; clean-environment wheel/sdist installation; `npm ci --ignore-scripts`, `npm run build`, `npm test`; `uv audit --locked --output-format json` and `npm audit` against their authoritative lockfiles; `git diff --check`.

## Success criteria

- Wheel and sdist include schemas/skills, install cleanly, expose the CLI/SDK and pass example acceptance flows.
- Tests exercise permissions, agent coordination, approved source changes, recovery, retrieval, provider contracts and the actual available Docker backend; no skipped requirement is reported as passed.
- Documentation, local Git history and distributable artifacts are consistent, with clear limits for live LLM evaluation, Windows mutations, browser/visual UX validation and deployment hardening.

## Boundaries and open questions

Always record actual checks and triage audit findings. Ask before remote publishing, paid live-provider tests or changing the proposed source license. Never claim that local tests, authored CI YAML or an unexecuted workflow proves cross-platform CI success, hosted production readiness or a security certification.
