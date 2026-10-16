# Specification: harness extensions

Status: experimental. Extends the capability map and existing module specifications; exact approval, unknown-outcome and v1 compatibility rules continue to apply.

## Objective and modules

Deliver working, Python-first tool, model, context and execution infrastructure for long-running software engineering tasks. Reuse the current runner, writer, policy, state, index and role runtime.

| Module | Responsibility | Dependencies |
|---|---|---|
| tool-registry | Typed descriptors, lazy host registrations, per-effect grants, approvals, structured results, retries, idempotency and backend bindings | contracts, policy, state, runner |
| model-routing | Capability-aware host adapters, explicit safe fallback, configured pricing, durable token/cost accounting and latency | provider-runtime, state, policy |
| context-management | Ranked source selection, deterministic compression, provenance-bearing decision memory and freshness | repository-index, state, policy |
| execution-loop | Persisted plan/execute/observe/verify/reflect phases, bounded recovery/replan, cancellation and resume | agent-runtime, context-management, tool-registry |
| harness-interfaces | SDK/CLI/Node access, operating documentation and evaluation | preceding modules |

Build independently after baseline; integrate and validate together. No additional orchestration dependency is needed.

## Contracts and acceptance

- Registrations are host objects, never imports named in untrusted project configuration. Validate input/output schemas, JSON sizes, duplicate names and remote schema references. Model-visible tools remain read-only by default. A host explicitly invokes privileged tools with grants and exact reviewed approval; approval is outside tool arguments.
- External execution uses named approved Runner commands or explicitly trusted host transports. Process separation is identified accurately; it is not an OS sandbox. Timeouts do not authorize replay of uncertain effects. Retry only known failures of replay-safe operations. Idempotency binds registry/operation/arguments and preserves an unknown-effect record across restart.
- Routing selects only registered models with the required capabilities. Alternative adapters are explicitly configured by trusted code. Fallback never occurs after unknown outcomes, policy denial, invalid output or budget exhaustion. Keep existing request budgets; add shared durable token/cost admission using supplied prices and conservative reservations. Dollar accounting is a local estimate, not a provider-enforced spending guarantee.
- Context is redacted, cited, bounded and marked as untrusted. Preserve dependency identities and critical decision provenance under compression. Exclude changed-source decisions. Semantic retrieval continues to use real vectors, separately labeled from lexical search.
- A loop checkpoints phases and results, accepts a validated bounded dependency plan, observes real outcomes, calls a host verifier and completes only when that verifier succeeds. Persist failures/reflections, stop repeated unsuccessful actions and bound steps/replans/deadline. Cancellation prevents further dispatch. Resume reuses completed work, rechecks pins and refuses unresolved external effects. Approval requests suspend privileged work; model output cannot approve it.
- CLI/SDK retain existing defaults and envelopes; Node continues to call Python. New public operations validate arguments and return actual checkpoint, trace and verification evidence.

## Verification and boundaries

Focused pytest checks cover schemas, permission denial, stale context, budget concurrency, safe fallback, timeout/unknown replay, idempotency, cancellation, repeated failure and resumed verified workflows. Run full non-Docker suite, Ruff lint/format, strict mypy, Node build/protocol/integration, wheel/sdist and clean-install checks. Use existing Docker fixtures only with a present pinned image. Ordinary tests never call paid models. Evaluation records solved/failed/recovered task counts, tokens, latency and configured cost; fixture evaluation does not establish live agent quality.

Use standard-library dataclasses, Protocols and SQLite transactions, current JSON Schema validation and surrounding code style. Add code only for the requested behavior. Do not bypass exact writer/runner approvals, silently broaden grants, replace staged work, auto-import repository modules or claim production readiness from local fixtures.
