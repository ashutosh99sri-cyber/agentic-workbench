# AI Hero research and runtime optimization

Reviewed 16 October 2026, starting from integration commit
`da07473268605273a88e7c81845d98202f1e3926`. The target is the existing Python
installable toolkit, with its optional OpenAI adapter and TypeScript CLI adapter.
Research preceded production edits. No paid lesson, API request, account action or
external publication is part of this work.

## Research scope and confidence

The public [homepage](https://www.aihero.dev/), [post index](https://www.aihero.dev/posts),
[skills catalogue](https://www.aihero.dev/skills), [open-source index](https://www.aihero.dev/open-source),
[roadmap](https://www.aihero.dev/ai-engineer-roadmap),
[MCP tutorial index](https://www.aihero.dev/model-context-protocol-tutorial) and
[AI SDK course overview](https://www.aihero.dev/workshops/ai-sdk-v6-crash-course)
were explored. Discovery used [llms.txt](https://www.aihero.dev/llms.txt),
[the public API catalogue](https://www.aihero.dev/api),
[sitemap.xml](https://www.aihero.dev/sitemap.xml) and
[sitemap.md](https://www.aihero.dev/sitemap.md): 196 XML URL entries and 208 normalized distinct
Markdown discovery URLs (212 raw URL references before trimming inline-code delimiters). These inventories overlap and are not a count of articles
read. The external research receipt retains the inventory and review-depth ledger.

The web reader rejected Markdown discovery content; a direct HTTPS fetch with TLS
verification succeeded. Python's local HTTPS trust configuration failed on the same
fetches; certificate verification was not disabled. Technical sections and examples
were reviewed on the sources below. Video pages were read through available text and
transcripts; videos were not watched. Remaining indexed posts/dictionary entries,
paid lessons, email lessons, account content and gated exercise implementations were
not reviewed. The advanced retrieval project is an overview, not implementation
evidence. This is systematic relevant-content research, not an exhaustive review of
every public page or a completed AI Hero course.

## Verified published recommendations

These are the author's recommendations, not measured results for this repository.

| Sources reviewed | Verified recommendation | Repository implication |
| --- | --- | --- |
| [Writing for agents](https://www.aihero.dev/skills-writing-for-agents), [AGENTS.md guide](https://www.aihero.dev/a-complete-guide-to-agents-md) | Keep always-loaded instructions focused; disclose detail when relevant; retain explicit completion conditions. | Preserve role-selected skills and bounded context. Avoid installing the whole skill collection into the runtime. |
| [Tracer bullets](https://www.aihero.dev/tracer-bullets), [TDD](https://www.aihero.dev/skills-tdd), [feedback loops](https://www.aihero.dev/essential-ai-coding-feedback-loops-for-type-script-projects) | Build a small complete behavior, test it and use types/checks for fast feedback. | Add focused behavior and operation-count regressions, then run the existing acceptance gates. |
| [Architecture survey](https://www.aihero.dev/skills-improve-codebase-architecture), [codebase design](https://www.aihero.dev/skills-codebase-design), [agent-friendly codebases](https://www.aihero.dev/how-to-make-codebases-ai-agents-love) | Hide complexity behind useful interfaces and refactor where a concrete change pays back. | Fix repeated work in shared contracts/retrieval/tool projections; retain the SDK and authority interfaces. |
| [Diagnosis](https://www.aihero.dev/skills-diagnosing-bugs), [review](https://www.aihero.dev/skills-code-review), [retrospectives](https://www.aihero.dev/skills-retro) | Reproduce first, compare against explicit requirements, and turn mechanical failures into checks. | Measure before/after and preserve a fixed baseline; keep regressions deterministic instead of adding prose-only rules. |
| [Specifications](https://www.aihero.dev/skills-to-spec), [tickets](https://www.aihero.dev/skills-to-tickets) | Capture decided requirements; divide work into independently verifiable vertical slices. | Keep each optimization bounded and test its own invariant. No tracker publishing is needed. |
| [Effective agents](https://www.aihero.dev/building-effective-agents), [tool calling](https://www.aihero.dev/tool-calls-with-vercel-ai-sdk), [agent steps](https://www.aihero.dev/agents-with-vercel-ai-sdk) | Start simple, define tools clearly, use environmental feedback and finite stopping conditions. | Existing typed tools, budgets, exact approvals and host verification already implement these principles. |
| [MCP logging](https://www.aihero.dev/logging-a-huge-mcp-footgun), [stateful MCP](https://www.aihero.dev/the-problem-with-mcp-stateful-server) | Keep logs off the protocol stream; understand the deployment model before choosing state storage. | Keep existing stderr/JSON-RPC separation and local SQLite; HTTP/serverless Redis examples are a different deployment. |
| [Context](https://www.aihero.dev/ai-coding-dictionary/context), [attention degradation](https://www.aihero.dev/ai-coding-dictionary/attention-degradation), [secondary sources](https://www.aihero.dev/ai-coding-dictionary/secondary-source) | Select relevant information and retain links back to source when summaries lose detail. | Existing source hashes, current-source checks, critical decisions and bounded citations remain authoritative. |
| [Tokens](https://www.aihero.dev/what-are-tokens), [context windows](https://www.aihero.dev/what-is-the-context-window), [messages and reasoning](https://www.aihero.dev/messages-system-prompts-and-reasoning-tokens) | Instructions, tools and history consume input; application code executes tools; prompts alone are insufficient controls. | Keep full-payload byte checks and deterministic permission enforcement. Character counts are not exact token counts. |
| [Usage lesson](https://www.aihero.dev/workshops/ai-sdk-v6-crash-course/tracking-token-usage~2u9a4), [solution](https://www.aihero.dev/workshops/ai-sdk-v6-crash-course/tracking-token-usage~2u9a4/solution), [prompt caching](https://www.aihero.dev/workshops/ai-sdk-v6-crash-course/prompt-caching-3kiw1) | Read final usage, including unavailable fields; prefix stability affects caching. | Unknown usage must remain unknown. Do not promise provider cache hits from a conceptual playground. |
| [Evals](https://www.aihero.dev/what-are-evals), [engineering mindset](https://www.aihero.dev/the-ai-engineer-mindset), [17 techniques](https://www.aihero.dev/how-to-improve-your-llm-powered-app), [retrieval project overview](https://www.aihero.dev/workshops/retrieval-project-day-2-san3f) | Define observable success, retain failure datasets, and try simple context/retrieval improvements before extra model stages. | Reuse the existing deterministic evaluations and content-addressed source-vector cache; measure local efficiency without claiming model-quality gains. |
| [Ralph setup](https://www.aihero.dev/getting-started-with-ralph) | Repeat small tasks with progress records and finite loops, starting with human supervision. | Existing checkpointed execution already serves this need. Do not import automatic edit acceptance or autonomous commits. |

## Version, license and dependency selection

AI Hero's older TypeScript examples use APIs such as `maxSteps` and `parameters`;
the current course overview discusses both v5 and v6. They are conceptual examples,
not a reason to replace the pinned Python provider. Its general chain-of-thought and
temperature advice is not imported: current [OpenAI reasoning guidance](https://developers.openai.com/api/docs/guides/reasoning-best-practices)
advises against asking reasoning models to expose step-by-step thought. Provider
[prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching) is
model-specific; local CPU caches do not establish token/cost savings.

The public [skills](https://github.com/mattpocock/skills) and
[Sandcastle](https://github.com/mattpocock/sandcastle) repositories declare MIT.
No upstream code/instructions are copied or redistributed here. Other candidate
packages were not installed or security-qualified. Existing project licensing and
third-party notices remain in force; advisory checks cover the actual lockfiles.

| Candidate | Decision | Compatibility, effort and maintenance |
| --- | --- | --- |
| Existing Python/JSON Schema primitives | Retain and optimize | Already required; no new dependency or public contract. Fresh validator instances avoid shared resolver state; failure diagnostics are copied before leaving the call. |
| Standard-library per-instance cached property | Use for frozen chunk identity | Same hash definition; cache lifetime follows the chunk. Concurrent first reads may compute the same digest twice. |
| Vercel AI SDK, Effect or Evalite migration | Reject for this change | TypeScript-centered additions duplicate the Python provider/evaluation/authority layers without a measured benefit here. |
| Sandcastle integration | Defer | Useful sandbox orchestration in another architecture; this toolkit already has an approved Runner. Integration needs a separate threat model and workload. |
| Redis/remote vector database | Reject for this change | No hosted/distributed workload requirement or measured local-storage bottleneck. |
| Husky/Vitest/lint-staged | Reject for this change | Existing pytest, Node test runner, Ruff, mypy, TypeScript and CI supply feedback without more dependencies or hook side effects. |
| Query-embedding cache | Defer | Repeated identical queries currently dispatch one request after source vectors are warm. Useful potential saving, but persistent query reuse/model-alias drift and coverage semantics deserve a separate change. |
| Shared validator-instance cache | Reject | Only a small additional microbenchmark gain over fresh validators; introduces avoidable concurrency assumptions. |

## Repository audit and prioritized implementation

The starting tree is clean and the prior exact-commit integration receipt covers
920 unique Python tests, installed consumers and Docker acceptance. This retained
baseline does not replace checks after these changes. The project has two required
runtime dependencies (`jsonschema`, `pathspec`), pinned optional OpenAI/httpx2, 35
Python source modules, a Node subprocess adapter and versioned contracts/skills.
Existing derivation reuse, source freshness, embedding content hashes, task budgets,
cancellation and separate apply/test approvals were verified in their current paths.

| Priority | Observed opportunity | Planned change and measurable acceptance | Cost |
| --- | --- | --- | --- |
| P1 | `validate()` deep-copies all contract definitions on every call | Use a private schema view with a fresh validator; public `schema()` stays defensive. Preserve malformed/fact/citation rejection, diagnostic mutation isolation and concurrent isolation; time public validation. | Small; no new persistent state |
| P1 | `Chunk.id` hashes its complete immutable content on each access | Cache the same digest on the frozen instance. Verify exact IDs, unchanged serialization, replacement isolation, fresh-source rejection and fewer hash operations. | Small; one digest per accessed chunk |
| P2 | `ToolRegistry.schemas` serializes full specs then discards most fields | Project the existing allowed read specs directly and copy only returned parameter schemas. Preserve order, visibility, effect exclusion and nested mutation isolation. | Small; no cache or API change |
| P2 | Benchmark aggregates missing usage as zero | Preserve `null` when a dispatched result lacks usage; retain actual zero for offline/no-request results and exact sums for known results. Add literal expected-output regressions. | Small; truthful benchmark output changes for previously unknown usage |

Validation: first capture repeatable microbenchmarks and example workflows on the
frozen baseline, then rerun the identical measurements. Record sample dispersion;
do not turn wall-clock timings into flaky CI thresholds. Preserve deterministic
output/quality and permission gates. Run affected tests, full offline acceptance,
lint/format/types, clean distribution consumers, Node checks, and actual Docker
acceptance. No live model calls or new dependencies are needed.

## Measured local results

Measurements used the same Python 3.14.0 interpreter and script against the frozen
baseline and candidate. Each kernel has seven samples, with identical warmup and
iteration counts. The real combined-search fixture used a supplied embedding
transport, not an external service, and selected the same ten source paths.

| Boundary | Baseline median | Candidate median | Local reduction |
| --- | --- | --- | --- |
| Evidence validation | 53.43 microseconds | 16.99 microseconds | 68.2% |
| AgentResult validation | 89.50 microseconds | 52.61 microseconds | 41.2% |
| Six tool schemas | 24.68 microseconds | 7.93 microseconds | 67.9% |
| 64 tool schemas | 283.73 microseconds | 85.58 microseconds | 69.8% |
| Repeated 50-candidate rank fusion | 377.02 microseconds | 17.75 microseconds | 95.3% |
| Combined-search chunk hashes | 60 computations | 10 computations | 83.3% fewer |

A separate seven-pair experiment alternated baseline/candidate order in fresh
processes, with one warmup and three measured runs per process. Its 21 samples per
revision covered all six existing static example tasks: median **235.47 ms to
227.77 ms (3.3% lower)**. Median absolute deviation was 3.01 ms and 1.52 ms,
respectively. File, symbol and test-target scores remained 1.0 in both variants.
This modest example-workflow result is the end-to-end measurement; the larger
kernel percentages must not be presented as whole-application speedups. Independent
production latency, LLM quality and API cost savings remain unmeasured.

Independent review caught a diagnostic-alias regression in the initial optimization:
a chained validation exception exposed shared definitions. The final implementation
copies the complete diagnostic on failure and raises outside the handler, isolating
both cause and context while keeping successful validation fast. Its regression
first reproduced process-wide schema poisoning, then passed after correction.

Focused regressions verify schema mutation/concurrency/exception isolation, model tool scope,
chunk hash/serialization identity and the benchmark's unknown/partial usage output.
The latter went from a fabricated zero or partial total to JSON `null`, while known
counts and zero-request static results retain correct totals.

## Results and boundaries

Final measured results and exact revision/artifact hashes are retained in the
task's external optimization receipt, separate from this pre-implementation plan.
Microbenchmark improvements establish local computational savings only. Application
latency, model quality, embedding relevance and user time/cost savings require
representative workloads and separate live acceptance. The existing
[public-release gates](public/READINESS.md) still apply.
