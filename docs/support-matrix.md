# Support matrix

This matrix describes the implementation and authored CI configuration for the 0.1.0 local release candidate. A configured workflow is not evidence that GitHub has run it. Consult [validation evidence](validation.md) for recorded local results and the actual remote run for a particular commit; report exact versions and skips when contributing. There is no older-version maintenance window or response-time guarantee.

| Area | Declared scope | Configured checks and limits |
| --- | --- | --- |
| Python core and offline CLI/SDK | Python 3.11+; Linux and macOS for the complete local workflow | CI declares Python 3.11, 3.12, 3.13 and 3.14 on Ubuntu and macOS. Versions beyond that matrix are not established by those checks. |
| Guarded apply, rollback and Runner execution | POSIX only | Requires POSIX descriptor/process behavior. Cooperating writers must respect the advisory workspace lock. Multi-file crash recovery can be partial. |
| Windows | Documented read-only subset | CI declares Python 3.12 with portable read-only integration, contracts, config and retrieval tests. No Windows source mutation or Runner execution is supported; Node descendant cleanup is unverified. |
| Node adapter | Node 24+ with an installed Python CLI | CI declares Node 24.0.0 and 26.7.0 on Ubuntu. Protocol tests use a fixture; separate integration uses `AGENTIC_EXECUTABLE` pointing to a clean installed CLI. This does not establish every newer Node version or Windows process cleanup. |
| Native TypeScript/JavaScript structure | Optional; TypeScript 7.0.2 with its matching native package, trusted Node, POSIX macOS/Linux arm64/x64 | `npm ci --ignore-scripts` in `adapters/node` supplies the locked package. `AGENTIC_REQUIRE_TYPESCRIPT=1` makes selected native tests fail if the runtime is missing. Ordinary Python-only operation remains available without it. |
| Docker Runner | Trusted local Docker daemon/CLI and an explicitly approved, already-local digest-pinned image suitable for the command | CI declares automatic real Docker acceptance with separately provisioned pinned Node and Python images. Local acceptance requires `AGENTIC_DOCKER_IMAGE` and is separate from the default test run. The runner does not pull images; daemon/kernel safety remains a host responsibility. Hosted results remain unverified until that exact commit runs. |
| Trusted-host Runner | Explicit POSIX host-execution opt-in with exact command/snapshot approval | Uses the host without an OS sandbox. Disposable test fixtures do not establish safe execution of arbitrary repositories. |
| Provider integration | Optional locked OpenAI SDK integration with explicit credentials/network permission | Offline transport fixtures do not establish live access, model quality or billing. Live acceptance needs an authorized account, current pricing and an explicit budget; local request estimates are not provider-enforced dollar caps. |

For the Windows read-only subset, run from the checkout with Python 3.12 and uv:

```powershell
uv sync --locked --all-extras
uv run --locked pytest tests/integration/test_portable_readonly.py tests/test_contracts.py tests/test_config.py tests/test_retrieval.py -W error
```

For POSIX contributor and native/installed-CLI/Docker acceptance commands, use [CONTRIBUTING.md](../CONTRIBUTING.md). See [security limits](security.md), [TypeScript analysis](typescript-analysis.md) and the [Node adapter](../adapters/node/README.md) for the relevant trust boundaries. Report limitations through [SUPPORT.md](../SUPPORT.md); report vulnerabilities privately under [SECURITY.md](../SECURITY.md).
