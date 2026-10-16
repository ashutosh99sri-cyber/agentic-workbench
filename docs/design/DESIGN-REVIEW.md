# Agentic Workbench design documents

These are design artifacts; runtime features require implementation and verification.

- [Capability map](CAPABILITY-MAP.md)
- [Threat model](THREAT-MODEL.md)
- [Source provenance](SOURCE-PROVENANCE.md)

| Module | Detailed specification |
| --- | --- |
| core-contracts | [Typed models, errors, config and logs](SPEC-core-contracts.md) |
| workspace-policy | [Path, permission and secret boundaries](SPEC-workspace-policy.md) |
| repository-index | [Detection, AST, citations and retrieval](SPEC-repository-index.md) |
| execution-state | [Task state, memory, claims and recovery](SPEC-execution-state.md) |
| skill-registry | [Skill format, discovery, validation and hashes](SPEC-skill-registry.md) |
| provider-runtime | [OpenAI, tools, structured output, budgets and embeddings](SPEC-provider-runtime.md) |
| change-workflow | [Proposal, exact approval, guarded apply and rollback](SPEC-change-workflow.md) |
| agent-runtime | [Eight roles, DAG coordination, RAG and isolated tests](SPEC-agent-runtime.md) |
| interfaces | [Six required commands, SDK and TypeScript adapter](SPEC-interfaces.md) |
| delivery-validation | [Packaging, CI, docs, examples and release evidence](SPEC-delivery-validation.md) |
| harness (experimental) | [Tool registry, model routing, context and execution loop](SPEC-harness.md) |

## Key decisions

1. Python 3.11+ with uv-locked isolated development, pip-compatible distributions, a small TypeScript adapter and an optional official OpenAI SDK integration.
2. Apache-2.0 source license; no automatic remote publication.
3. Offline static analysis as a real supported mode; external LLM/embedding requests are explicit opt-in. Contract tests do not imply live model access or quality.
4. Exact-content/base/policy/workspace/skill approvals, POSIX guarded writes, journaled recovery and rollback that refuses later user edits. Initial Windows support is read-only/interface operation.
5. Docker is the default test execution backend, with a pre-existing approved digest-pinned image. Trusted-host execution is explicit and documented as weaker isolation.
6. Local owner-controlled SQLite state and memory, explicit retention, no automatic learning/promotion, no enterprise multi-tenant/authentication claims.
