# A trusted host provider adapter recipe

The SDK accepts the `Provider` protocol through an explicit `ProviderRegistry`.
[`CallbackProvider`](../../examples/integrations/provider_adapter.py) is a small,
direct-analysis example to copy into trusted host code. It adds no provider to the
CLI, dependency, HTTP stack, automatic retry or fallback. Its deterministic test
transport makes **zero external calls**; the fixture establishes contract behavior,
not model quality, vendor interoperability or billing accuracy.

The adapter accepts a trusted `WorkspacePolicy` and a transport callback. It measures
the complete serialized request, redacts recognized and environment-known secrets,
checks the exact host's network grant, reserves the shared request budget, and writes
a durable intent before dispatch. The SDK's context builder uses `context_size` to
fit source context within that complete request. An instance belongs to one root
task: child calls share its monotonic deadline and unknown-outcome latch.

The transport receives only `(payload_bytes, monotonic_deadline, response_byte_limit)`.
It receives neither credentials nor the host executor. This recipe offers `tools=[]`
and accepts only `ModelAnalysis`, so it cannot expand or execute a supplied host tool
scope. For an adapter with tool rounds, route requested calls through the supplied
`ToolExecutor` and its permission-filtered schemas; never implement model-selected
filesystem, shell or vendor tools beside that boundary. Use the existing OpenAI
adapter when OpenAI Responses and read-tool rounds are needed.

## Explicit host registration, with an offline transport

Run this from a source checkout with the core package installed. Installed consumers
can copy `provider_adapter.py` into their own host application and import it there.
The example domain is reserved for documentation; this callback never connects to it.
The network grant remains necessary because the SDK deliberately treats all providers
as potential source transmission.

```python
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from agentic_workbench import Config, Grant, Workbench
from agentic_workbench.config import ProviderConfig
from agentic_workbench.models import canonical_json
from agentic_workbench.policy import WorkspacePolicy
from agentic_workbench.providers import ProviderRegistry
from examples.integrations.provider_adapter import CallbackProvider


def offline_transport(payload: bytes, deadline: float, response_limit: int) -> str:
    # Fixture only: a real trusted transport must enforce both supplied bounds.
    request = json.loads(payload)
    assert request["tools"] == []
    return canonical_json({
        "analysis": {
            "summary": "Offline transport fixture; no model inference",
            "findings": [],
            "recommendations": [],
            "candidate_edits": [],
            "limitations": ["No live-provider or model-quality evidence"],
        },
        "usage": {"input_tokens": 0, "output_tokens": 0},
    })


with TemporaryDirectory(prefix="provider-recipe-") as directory:
    root = Path(directory)
    (root / "app.py").write_text("value = 1\n")
    config = Config(provider=ProviderConfig(name="callback", model="offline-fixture"))
    grants = Grant(network=True, provider_hosts=("provider.example",))
    registry = ProviderRegistry()
    registry.register("callback", CallbackProvider(
        WorkspacePolicy(root, config, grants=grants),
        offline_transport,
        domain="provider.example",
    ))
    with Workbench(root, config, grants=grants, provider_registry=registry) as wb:
        result = wb.run_agent("engineering", "Review app.py")
        print(result["summary"])
        print(wb.store.export()["intents"])
```

Config supplies the name and model. Only trusted host registration supplies executable
adapter code. Neither repository config nor model output can import a provider or grant
network, write, execute or tool authority. Bind the adapter and `Workbench` to the same
workspace, config and host grant decisions. Keep live transport code outside untrusted
repository inputs.

## Transport contract and failure handling

The transport converts the bounded request to the vendor's format and normalizes a
complete response to JSON text with exactly these fields:

```json
{
  "analysis": {
    "summary": "A source-grounded explanation",
    "findings": [],
    "recommendations": [],
    "candidate_edits": [],
    "limitations": []
  },
  "usage": {"input_tokens": null, "output_tokens": null}
}
```

Use null for unavailable token counts; known counts must be exact nonnegative integers
at most `2**63 - 1`, matching the durable receipt contract. Zero in the example means the
fixture performed no inference. The adapter sets `requests=1` itself and constructs
`ProviderResult`, which validates both `ModelAnalysis` and `Usage`. Invalid counts, invalid
candidate shapes, extra envelope fields, duplicate JSON properties and oversized
normalized responses fail with `PROVIDER_INVALID_RESPONSE` and an `invalid_response`
receipt. A validated candidate is saved as a proposal; it still needs the current exact
review digest and a separate write grant before it can change source.

The trusted transport must resolve its credential privately, use fixed approved HTTPS
destinations, validate TLS, disable unapproved redirects/proxies/environment endpoint
overrides, and bound the streamed vendor response **before** buffering or parsing it.
It must honor the absolute `time.monotonic()` deadline, including connect, read and
normalization time. The callback deadline is cooperative: Python cannot forcibly stop
an arbitrary synchronous callback. The adapter also checks elapsed time after recording
a complete receipt; this does not substitute for transport-enforced timeouts. Do not
pass credential-bearing headers, errors or SDK objects back in the normalized response.
Secret recognition is conservative and cannot prove all sensitive data was removed;
review source exclusions and register any transport-only opaque credential with the
host's redactor before constructing model payloads.

Raise `ProviderRejected` only for an explicit, known rejection where the vendor confirms
the request was not accepted, such as an authoritative rejection response. The adapter
records a `rejected` receipt and performs no retry. A connection loss, timeout, ambiguous
server outcome or any other callback exception records `unknown`, raises
`OUTCOME_UNKNOWN`, and blocks further calls on that instance. Reservations are retained.
Cancellation also marks an in-flight intent unknown before it propagates. Consult the
retained task/intent state before a host deliberately constructs a new instance; creating
one must never be used to bypass an unresolved task's uncertain outcome. Invalid complete
output is a known receipt and a typed error, not a rejection eligible for fallback.

## A real disposable repair check, with a supplied candidate

From the checkout, run the contract suite in the existing locked development environment:

```sh
python -m pytest -q tests/test_provider_recipe.py
```

To run just the repair workflow:

```sh
python -m pytest -q tests/test_provider_recipe.py::test_callback_drives_real_disposable_repair_with_supplied_candidate
```

That test copies `examples/python_app` to pytest's disposable temporary directory. It
registers the callback through `ProviderRegistry` and the named command `unit`, whose
actual argv is `[sys.executable, "-B", "-m", "unittest", "-q"]`. With explicit fixture-host
grants it uses the existing `repair(..., command_id="unit", backend="trusted-host")`
workflow: review and approve the baseline command, reproduce the failing percentage
discount test, receive one **known supplied candidate**, review and approve its exact
change digest, then separately review and approve the verification command. The named
command really runs before and after the change; the fixture callback performs no
inference. Trusted-host execution has weaker isolation than Docker and is limited here
to that copied, known fixture. This check requires POSIX source mutation support.

The suite also proves that the adapter cannot dispatch without network/domain grants
or budget, that excluded `.env*` source and a synthetic known credential stay out of
payloads, and that a schema-valid candidate cannot write with a missing or stale digest.
It does not assess live provider availability, latency, model quality, HTTP security or
real provider spend.
