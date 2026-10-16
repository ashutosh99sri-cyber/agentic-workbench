# Engineering execution harness

Status: experimental. Interfaces and state formats may change without a compatibility period.

The audit and implementation contract are [harness-gap-analysis.md](harness-gap-analysis.md) and [SPEC-harness.md](design/SPEC-harness.md). Python owns policy and execution. Existing CLI envelopes, AgentResult schemas, approved writer/rollback and Runner boundaries remain in place.

## Run and inspect a workflow

```sh
agentic tools --root /path/to/project
agentic skills --root /path/to/project
agentic context "invoice rounding" --root /path/to/project
agentic execute "Investigate invoice rounding" --root /path/to/project
agentic trace TASK_ID --root /path/to/project
agentic cancel TASK_ID --root /path/to/project
```

The default execution performs engineering analysis and validates current source citations. Its verification evidence says `scope: source-contracts`; it does not claim that an application bug was repaired or tested. Static mode remains offline. Configured LLM analysis still requires a host network grant.

To execute a selected saved proposal, supply a configured verification command. The workflow returns `awaiting_approval` and a concrete change review before writing:

```sh
agentic execute "Repair invoice rounding" --proposal-id PROPOSAL_ID \
  --command-id unit --root /path/to/project
```

Repeat with the same instruction/options, its `--task-id TASK_ID` and the reviewed `--approve CHANGE_DIGEST`. The framework applies once, then returns the current command/snapshot review. Repeat with `--approve-test TEST_DIGEST` to run the check. Success requires exit code zero, no timeout/output limit, and a receipt matching the current source snapshot. Docker remains the default. `--trusted-host` is the separate explicit weaker opt-in; approvals never select it automatically.

Use `execute ... --task-id` with matching options and grants for privileged built-in workflows. Generic `resume` resumes analysis tasks, orchestrations and read-only built-in loops. Custom loops resume through the same trusted host callbacks and pins. Changed configuration, skills or provider registry invalidate resume; approved source edits create freshly pinned child analysis tasks. Cancellation terminally stops active, failed and interrupted task trees at dispatch boundaries; completed outcomes and outstanding effect receipts remain recorded.

## Tool extensions

`ToolSpec` binds name/version, input/output JSON Schemas, effect, backend, deadline, replay policy and optional destination. `ToolRegistry` supports explicit handlers and lazy host factories. It never imports an executable named by repository or skill content.

```python
from agentic_workbench import ToolSpec, Workbench

empty = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}
output = {"type": "object", "properties": {"healthy": {"type": "boolean"}},
          "required": ["healthy"], "additionalProperties": False}

def configure(registry):
    registry.register(
        ToolSpec("host_health", "Read host readiness", empty, output,
                 model_visible=True, version="host-health-v1"),
        lambda arguments, call: {"healthy": True},
    )

with Workbench("/path/to/project", configure_tools=configure) as wb:
    descriptors = wb.tools().discover()
    result = wb.tools().invoke("host_health", {})
```

Repository read tools are added automatically. Host-opted model tools are read-only and intersect effective policy; executable/writing/destructive tools cannot enter the model scope. Registrations must supply an updated version when the trusted implementation contract changes.

Python and CLI executables use `registry.register_command(name, command_id, backend="docker", python=True)` with an existing named `CommandConfig`. `review()` includes the exact Runner command, executable, backend, image and snapshot. `invoke()` needs its exact host digest plus an idempotency key. Python callbacks loaded by `register_lazy` are trusted in-process code with cooperative deadlines; executable repository Python uses Runner isolation.

`JSONAPI` in `tool_backends.py` binds a fixed HTTPS POST URL, verifies the destination grant, disables ambient proxies/redirects and resolves credentials separately from arguments. Its default transport executes in a terminable process with a total deadline and bounded JSON. Credential echoes are redacted; credentials in request bodies are denied. An explicitly injected host transport owns its own deadline. API approval includes the full URL and method.

`StdioMCPClient` in `mcp_client.py` implements the initialize/initialized/tools handshake using UTF-8 newline JSON-RPC. Discovery is bounded; structured tool content is schema-checked by the registry. It launches a sanitized trusted-host process, bounds input/output and kills the process group on timeout. Register it as an `execute` effect with `reviewer=client.review`; it cannot be exposed as a model read tool. Reviews pin the executable, argv and existing argument files; repository file arguments are denied. External read MCP transports can implement the typed `MCPClient` protocol with declared destination grants. This subset deliberately omits HTTP/SSE sessions, pagination, prompts and resources. Protocol basis: [MCP stdio transport](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports) and [lifecycle](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle).

`ToolResult` reports status, validated data/error, attempts, backend, elapsed milliseconds and cache provenance. Durable idempotency binds the exact operation and arguments. Reusing a key with different content conflicts; an interrupted operation without a receipt cannot replay. Retries require a replay-safe descriptor and a known admission rejection. Generic transport errors and MCP tool errors remain uncertain. Task-scoped calls share a durable root tool budget and produce policy/receipt events.

## Model routing and budgets

`ModelRegistry.register(ModelSpec(...), adapter)` accepts trusted implementations of the existing Provider protocol. `RoutedProvider` selects from the host preference list by required capabilities. Supply it through `Workbench(provider=router)`. Alternatively, `Workbench(provider_registry=registry)` resolves a configured provider name from an explicit trusted `ProviderRegistry`; repository configuration never imports adapters.

ModelSpec declares input/output bounds, maximum requests and optional supplied prices. For OpenAI the descriptor must cover the configured full payload, output maximum and all tool rounds/retries, such as `max_requests=config.limits.provider_requests`. The existing Responses SDK adapter remains available; no alternative endpoint is silently trusted.

RoutingLimits governs shared root tokens and estimated dollars. Reservations are atomic across child tasks and SQLite connections and survive restart. Known receipts settle usage; unknown outcomes retain conservative reservations. Missing prices stay unknown and cannot satisfy dollar admission: provide actual host prices or explicitly choose `maximum_cost_usd=None`. Explicit zero prices mean a host-declared free adapter. Supplied pricing and local reservation are estimates, not provider-enforced spending guarantees.

Fallback requires the adapter's explicit `ProviderRejected` after known rejection receipts. It never follows policy denial, invalid output, budget exhaustion, cancellation or unknown transport outcomes. Adapters must reserve every actual dispatch, record intent/receipt and honor their registered resource bounds. Traces include selected model, requests, measured latency, tokens and cost provenance.

## Context and persistent decisions

ContextManager ranks current source, compresses excerpts and dependency results deterministically, and budgets the complete serialized bundle. OpenAI also measures the actual initial wire payload, including schemas and escaped context. Dependency identities and citations survive compression; stale dependency content is excluded. Critical decisions retain full text and provenance or fail closed when they cannot fit.

`wb.remember_decision(task_id, text, evidence, critical=True)` records a source-bound decision. `wb.decisions(query)` retrieves relevant current decisions. ContextManager supports explicit supersession and retirement while retaining audit provenance. Memory is untrusted context, not authority. Automatic role summaries are cited and source-bound. Semantic search ranks a relevance-first, file-diverse candidate set with real vectors, caches each vector by adapter/model/dimensions/text hash and discloses indexed/total coverage; lexical and semantic modes stay distinct.

## Custom controlled loops

`wb.harness(planner=..., executor=..., verifier=..., pins=..., limits=...)` constructs a Harness. Planner receives instruction and observation/reflection history and returns a typed, validated dependency Plan of Steps. Each Step has a distinct action/arguments and dependencies. The trusted executor returns an Observation of actual work. The trusted verifier returns nonempty verification evidence and its boolean decision. Neither a plan nor model output supplies approval.

The controller persists Plan → Execute → Observe → Verify → Reflect phases, accepted plan revisions, attempts, observations, failure signatures and deadlines. It completes only after verification succeeds. Replanning preserves identical completed steps and effect receipts; changing the step ID cannot disguise an unsuccessful operation. Known read retries also require `replay_safe_actions` from the host. All dispatches have durable intents; crashes with an unresolved effect refuse replay. Observation/receipt checkpointing is transactional. Approval suspension retains the concrete review, and resumed execution reuses already completed effects.

Effect reuse is keyed by each operation's identity: its action, its arguments and, for every dependency, that dependency's own identity and an immutable digest of its sanitized, initially bounded result. Later evidence compaction changes presentation, never this digest. Step IDs are routing labels only, so a renamed step is the same operation; put meaningful input roles in action arguments, not in dependency names. A completed effect is reused only while it belongs to the current or the immediately previous plan round. Preserving a completed step carries its effect into the current round, including across approval suspension and process restart. Once a later round has run other effects, planning the same operation again dispatches it as a new logical instance: A, then B, then A applies A twice, because B may have changed what A wrote. Built-in apply and test steps dispatch fresh. A custom adapter that derives a backend idempotency key from the operation alone would return its first receipt for the second instance, so such adapters must key each logical instance separately, or require approval before repeating an arbitrary external effect. A failed operation that is not replay-safe stays denied in every later round, whatever its upstream steps are called. Observations over 64 KiB and checkpoints near the 1 MB state limit keep their known receipts with bounded evidence, marked `truncated`.

Checkpoints record their `execution_contract` (currently 4). **Upgrading:** an execution paused under an earlier contract is refused on resume with `CONFLICT`, because its completed effects were keyed under an older identity and could otherwise run twice. Missing or malformed persisted result digests also refuse resume before dispatch; they are never reconstructed from compacted evidence. Inspect it with `agentic trace TASK_ID`, review which effects already completed, then `agentic cancel TASK_ID` and start a new execution. A completed execution still returns its stored result under any contract. The old checkpoint and trace stay readable.

The role orchestrator separately supports up to 32 dependency nodes, distinct optional instructions and at most two read specialists. Readiness scheduling releases a node when its own prerequisites finish, without waiting for unrelated nodes. Mutation remains serialized through the shared writer and Runner.

TypeScript `Workbench` forwards execute/cancel/trace/tools/skills/context and semantic search to the same Python CLI. It retains argument arrays, strict envelopes, minimal credential forwarding and bounded process termination. Custom Python callback registration stays in the trusted Python host.

## Evidence and operating limits

Run `python scripts/evaluate_harness.py` for actual disposable-fixture commands and recovery checks. [harness-evaluation.json](harness-evaluation.json) records the measured run. It intentionally includes one unrepaired failure; this is control-flow acceptance, not a statistical live-model task-success score. [validation.md](validation.md) records the full check results.

This is a local owner-controlled execution framework. It is not a distributed scheduler or multi-tenant service. Trusted in-process callbacks cannot be forcibly stopped; cancellation is cooperative at callback boundaries. Docker supplies the executable sandbox; stdio MCP process separation and API transport process deadlines are not OS sandboxes. Host adapter declarations, supplied prices, unknown-secret recognition, local audit mutability and cooperating filesystem writers remain explicit trust limits. Live agent repair quality and provider-enforced billing require separate acceptance.
