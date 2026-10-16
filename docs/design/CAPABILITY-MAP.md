# Agentic Workbench capability map

This is the module boundary and build-order reference, not an implementation or a production-readiness claim.

## Objective

An installable Python CLI and SDK that helps developers understand, investigate, design, improve, test, and document existing applications. Eight specialized agents share explicit task contracts, source evidence, versioned skills, and durable execution state. TypeScript applications can integrate through a small Node.js adapter. No existing project is overwritten by repository creation.

## Module boundaries and dependency direction

| Stable module ID | Owns | Depends on |
| --- | --- | --- |
| `core-contracts` | Typed tasks, results, evidence, errors, configuration, versioning, structured event logging | None |
| `workspace-policy` | Root confinement, deny rules, secret filtering, permission checks, exact-operation approvals, safe filesystem access | `core-contracts` |
| `repository-index` | Manifest/framework detection, bounded file inventory, Python symbols, language-neutral chunks, citations, lexical retrieval | `workspace-policy` |
| `execution-state` | SQLite task/event store, scoped contextual memory, immutable task/skill references, interruption and recovery states | `core-contracts`, `workspace-policy` |
| `skill-registry` | Original bundled skills, explicit local skill discovery, validation, framework matching, content hashes | `core-contracts`, `workspace-policy` |
| `provider-runtime` | Provider protocol, OpenAI Responses adapter, structured output validation, bounded tool-call loop, retries, usage telemetry, optional embeddings | `core-contracts`, `workspace-policy` |
| `change-workflow` | Reviewable change proposals, approval bound to exact content and base hashes, dry run, guarded application, rollback journal | `execution-state`, `repository-index`, `workspace-policy` |
| `agent-runtime` | Eight independently callable agents, tool registry, orchestrator task graph, relevant skill/context assembly, source-grounded RAG | `repository-index`, `execution-state`, `skill-registry`, `provider-runtime`, `change-workflow` |
| `interfaces` | `agentic` CLI, Python SDK, Node/TypeScript subprocess adapter, stable JSON envelopes | `agent-runtime` |
| `delivery-validation` | Packaging, CI, example projects, installation and security/regression tests, documentation, architecture diagram, contributor/release guidance | All preceding modules |

Dependencies point from consumers to providers. No provider imports its consumer. The integration test module may exercise every module; it does not become a runtime dependency.

## Agent responsibilities

| Agent | Concrete responsibility | Write boundary |
| --- | --- | --- |
| Repository Discovery | Inventory files, frameworks, dependency manifests, entry points, architecture evidence | Read-only source access |
| Code Intelligence | Explain symbols and code paths, collect evidence for bug hypotheses | Read-only source access |
| Software Engineering | Produce plans and exact reviewable changes; apply only an explicitly approved proposal | Guarded change workflow |
| Architecture | Evaluate source-backed API, database, security, infrastructure and scaling decisions; label unknown runtime facts | Read-only analysis |
| UX/UI | Inspect interface source and design conventions; recommend actionable improvements with file citations | Read-only analysis |
| Testing | Propose relevant tests, validate approved changes, report command/result evidence | Approved isolated runner |
| Documentation | Propose onboarding, API and architecture documents with provenance | Guarded change workflow |
| Orchestrator | Select agents/skills, manage task dependencies, bounded execution, recovery, approvals and final evidence | Delegates through the same permission controls |

## Build order and validation slices

1. Installable package → configuration and policy → `init` and read-only `scan` against Python and TypeScript examples.
2. Source index → skills → durable task state → independently callable discovery, intelligence, architecture and UX agents.
3. Provider protocol → Responses/tool-call handling → source-grounded `explain` and `plan`, structured outputs, RAG and optional embedding search.
4. Exact-content approval → dry-run `apply` → guarded approved application → interrupted-write recovery and conflict-safe rollback.
5. Isolated test runner → `test` → testing/documentation/software-engineering agents → orchestrator coordination and recovery.
6. Python SDK and TypeScript adapter → wheel/sdist installation checks → CI, security tests, contribution/release guides and final evidence report.

Each implementation task will have acceptance criteria, owned files and an executable verification command in the reviewed plan.

## Proposed operating defaults

- Python 3.11+; a `src/` layout and `pyproject.toml`; isolated development/install environments. TypeScript is an adapter, not a second orchestration engine.
- Local-first state stored outside indexed source content. Local repository discovery works without an LLM, network access or an API key.
- External LLM use is opt-in. Credentials come from environment variables or an injected credential resolver; credentials never enter prompts, persisted task state, reports or logs.
- No model name, paid budget or additional provider is silently assumed. The OpenAI adapter uses a configured model and bounded requests. Provider/API access will be contract-tested without charging a live account unless separately authorized.
- Repository documents, retrieved chunks and third-party skills are untrusted data. They cannot grant permissions, change configured policy or bypass approval.
- Default tools are read-only. A model cannot approve its own changes. Approvals identify the exact proposed operation, content digest and expected base version; approval is invalidated by relevant changes.
- Secret paths and detected secret values are excluded/redacted before indexing, retrieval, provider transmission and observability. This reduces exposure; it is not a claim that arbitrary secrets can be detected perfectly.
- The file policy is not described as an OS sandbox. Test/command execution is denied by default and uses an explicit isolated runner with restricted filesystem/network settings. Any trusted-host mode must be explicitly enabled and documented as weaker isolation.
- No arbitrary shell strings. Commands use structured argument arrays, declared tools, explicit permission checks, timeouts and bounded output.
- Change application rejects traversal, symlink escapes, stale base hashes, forbidden targets, malformed proposals and conflicting writes. Rollback refuses to overwrite later user edits.
- Retrieved memory is persisted context, not autonomous model training. Semantic search uses an explicitly configured embedding provider; lexical retrieval remains a distinct supported path.
- Skills are original, provider-neutral, versioned and hash-pinned per execution. Third-party skills supply design guidance and provenance; they are not copied wholesale into a distributable repository without licensing evidence.
- GitHub-ready means a tested local Git repository, distributable packages, CI configuration and release documentation. Publishing, remote pushes, hosted deployment and paid scans are separate actions.

## Acceptance evidence required for delivery

- Install the built wheel into a clean environment and execute all six required CLI commands.
- Scan at least two example stacks and verify framework detection, source citations, ignored files and secret filtering.
- Exercise all eight agent contracts and an orchestrated multi-agent task with real durable state transitions.
- Validate provider request/response parsing, tool calling, refusal/error handling, retry bounds and structured outputs through deterministic contract tests; distinguish these from unperformed live-provider tests.
- Retrieve source-grounded context through lexical retrieval and test vector search against controlled embedding fixtures; distinguish fixture results from live semantic relevance evaluation.
- Verify dry runs leave source unchanged; unapproved changes fail; exact approved changes apply; stale approvals fail; rollback preserves unrelated user edits.
- Verify test execution policy, isolation settings, timeouts, output limits and accurate pass/fail reports against example projects.
- Build and test the TypeScript adapter against the installed Python CLI.
- Run repository checks and record exact results and limitations. A passing local suite alone does not establish deployment hardening or third-party security certification.

Module specifications are indexed in [DESIGN-REVIEW.md](DESIGN-REVIEW.md).
