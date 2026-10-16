# Specification: provider-runtime

Depends on `core-contracts` and `workspace-policy`.

## Objective and contract

Support configurable LLM providers through a typed `Provider` Protocol and an optional official OpenAI SDK adapter. The core scan/index/approval machinery works without the SDK or an API key. Additional providers can be registered by trusted SDK host code; arbitrary provider modules from repository content are never imported automatically.

OpenAI uses the Responses API with a configured model, `store=False`, closed structured-result schemas and strict function schemas. The adapter carries required response output items forward during tool loops and associates outputs with the actual call_id. Refusal, incomplete output, malformed JSON, unexpected tools, schema errors and unknown item shapes produce bounded, explicit outcomes. No raw model response becomes a path, shell command, approval or state transition.

The provider-facing analysis schema includes bounded candidate edits as data, separate from the public AgentResult. Host code validates those candidates through change-workflow, creates immutable proposals, and returns their saved IDs in AgentResult. Candidate content is never written directly from the provider response.

The initial endpoint is the canonical OpenAI API over verified HTTPS. Credentials are obtained by environment variable/resolver immediately before a request and never passed through model context or durable state. Network use requires an explicit host grant identifying provider/workspace scope; configuration alone cannot enable it. Custom adapters own their transport but must satisfy the same result/tool contracts and remain explicitly trusted host extensions.

Default limits: maximum 8 provider requests, 6 tool rounds, 16,000 context bytes, 2,000 requested output tokens per request and 60-second request timeout per root task, including all child agents, retries and embedding calls; host configuration may reduce or explicitly change these. Reserve attempts atomically through an injected shared budget ledger before dispatch and reject overflow before another request. Bound complete context/schema/tool payloads, not only retrieved excerpts. Request/byte limits are enforced locally; output-token limits are sent to the provider and actual known token usage is recorded after receipts. Dollar estimates use explicitly configured rates; they are not an absolute charge cap.

Disable the SDK's hidden retry layer. At most two retries are allowed for explicit pre-admission rate-limit responses, bounded by task limits and Retry-After. Unknown transport outcomes, timeouts and possibly executed server failures are recorded and surfaced; no silent paid replay. Tool arguments and results are validated independently of provider-side schema promises.

Optional OpenAI embeddings use a configured model and explicit source-transmission grant. Validate finite vectors, dimensions, lengths and result ordering; bind persisted vectors to provider/model/chunk hashes. Live-provider billing, model access and semantic relevance require separate acceptance evidence.

## Structure and style

Own `providers.py`, `providers_openai.py` and `tests/test_providers.py`. Executor/event/intent sinks are injected Protocols so this module never imports agent-runtime or execution-state. The model sees only allowlisted tools; mutating/approval/test-execution tools are not exposed in the LLM loop.

## Commands and verification

`uv run --locked --extra openai pytest tests/test_providers.py`. Use deterministic SDK transport fixtures for genuine request/response contracts, multi-round function calls, refusals, invalid schemas, rate limits, unknown outcomes and embeddings. Live API tests are opt-in and never run in ordinary CI.

## Success criteria

- Validated structured Responses/tool loops operate through the actual SDK adapter contract; external calls cannot bypass effective policy.
- Retries, context/token/request bounds, refusal handling and uncertain receipts are tested; no credentials leak into captured state/output.
- Missing SDK, key, model or network grant has an actionable error; offline operation never invents an LLM result.

## Boundaries and open questions

Always validate provider input/output and preserve real call/usage provenance. Ask before enabling live paid requests or additional credential destinations. Never claim subscription sign-in substitutes for an API key, hard dollar caps exist without provider enforcement, or fixture tests establish live model quality.
