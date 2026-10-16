# Providers, credentials and source transmission

The optional OpenAI extra is installed with `python -m pip install '/absolute/path/to/agentic-workbench[openai]'` from a local source checkout, or append `[openai]` to an actual published package requirement after publication. Choose a model available to your account. No default model or fabricated offline response is supplied.

Configure names, not credential values:

```toml
[provider]
name = "openai"
model = "your-account-model-name"
embedding_model = "your-account-embedding-model-name"
credential_env = "OPENAI_API_KEY"
```

Set that variable securely in the process launching agentic. Do not paste a key into chat, source, skills, config or proposal JSON. For each explicit request the adapter resolves it immediately and sends it only to fixed verified HTTPS `api.openai.com`. Environment endpoint overrides, custom headers, proxies and redirects are disabled. `store=False` disables Responses API storage for these requests; it is not a claim about all provider data-retention obligations. Review your provider agreement before transmitting proprietary code.

For an interactive terminal, use the hidden prompt instead of putting the key in a shell command:

```sh
agentic explain app.py --root . --provider openai --model gpt-6-luna --allow-network --prompt-key
```

Choose a model your own account can access. `--prompt-key` also works with `plan`, `run`, `resume`, and semantic `search`. It checks the configured provider, required model, network policy and optional SDK before asking. It requires an interactive stdin terminal and refuses an input method that cannot disable echo. The value lives in this command's process environment under `provider.credential_env`; it is never written to configuration or state, and the previous environment value is restored when the command exits, fails or is interrupted. Keys still exist in process memory during execution; this is not an operating-system secret vault. Automated SDK/Node integrations should inject a credential through their secret manager into the child environment rather than request the interactive prompt. Entering a key does not grant source writes or test execution.

`agentic explain app.py --root . --provider openai --model MODEL --allow-network` grants this invocation source transmission. With a configured embedding model, `agentic search "invoice totals" --semantic --root . --allow-network` grants embedding transmission. Recognized/known secrets are filtered, but secret recognition is conservative and cannot prove all sensitive information is removed. Narrow source exclusions and review context accordingly.

Complete request payloads include instructions, schemas, context, prior tool output and requested outputs. Local bounds apply before dispatch. Usage records contain known token counts, request/response/model provenance and uncertain receipts; no dollar amount is invented. The ledger counts retries, embeddings and children against one root limit. At most two explicit 429 rejection retries fit inside the shared deadline; unknown transports/timeouts/server outcomes stop automatic replay.

OpenAI Responses carries actual output items and call IDs through validated read-tool rounds. Refusals, incomplete output, unknown item forms and invalid JSON/schema become explicit errors. Candidate edits are validated and saved as proposals; source writes still need separate host approval. Embeddings validate text hashes, count/order, finite vectors and dimensions. Cached vectors bind source fingerprint, configured provider/model and dimensions. Query embeddings are new explicitly granted requests.

The locked SDK/httpx versions have genuine transport-fixture coverage. Response byte limiting and suppression of SDK environment headers use two inspected SDK/httpx internals; upgrades must rerun those fixtures. Additional providers are explicit trusted host adapters. Live availability, model quality, billing and semantic relevance remain environment acceptance checks, excluded from normal CI.

The optional package extra pins those two transport versions exactly, so ordinary pip installations cannot silently upgrade the inspected internal bridge. Maintainers should deliberately update the pins and lockfile after transport-fixture validation.
