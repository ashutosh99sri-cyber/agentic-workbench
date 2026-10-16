# Disposable integration examples

Both projects contain a deliberate percentage-discount regression. Tests assert that 1000 cents with a 10% discount becomes 900 cents. The initial implementations subtract the percent directly, so the tests fail. The integration workflow proposes a full replacement bound to the current SHA-256, reviews/dry-runs, applies with exact host approval, observes passing tests and rolls back to the original.

The [offline repair walkthrough](offline_repair/README.md) makes the Python workflow runnable outside pytest. It requires a fresh workspace and separate interactive approvals, reopens the Workbench between stages, retains its task/receipts for inspection, and restores the original fixture through approved rollback. No provider or API key is needed.

The installed SDK walkthrough creates its own disposable fixture and reports source
analysis, imported planning, source preservation and zero provider requests:

```sh
/path/to/installed/environment/bin/python examples/sdk_walkthrough.py
/path/to/installed/environment/bin/python examples/sdk_walkthrough.py --execute
```

`--execute` approves only the predefined synthetic fix and its explicitly trusted-host
unittest command, verifies failure then success, and restores the original bytes.
Run it outside the checkout too; no API key or optional OpenAI dependency is required.
See the [developer adoption guide](../docs/developer-adoption.md) before integrating
approvals into your own host.

Python uses standard-library unittest, no target dependencies. TypeScript uses Node 24+ native type stripping and standard-library `node:test`; its tsconfig is checked using the adapter's pinned TypeScript compiler. There is no automatic dependency install or compilation within the runner. A small HTML fixture supports source UX analysis; it is not a tested interactive UI or visual acceptance example.

Run `uv run --locked pytest tests/integration/test_workflow.py -q` for real disposable trusted-host workflows. Run `uv run --locked pytest -m docker tests/integration/test_sandbox.py -q` with `AGENTIC_DOCKER_IMAGE` naming your explicitly approved present Node image for actual Docker confinement/failure checks. The delivered validation report identifies the real image used locally.

`examples/config/agentic.toml` documents offline defaults and command configuration. Do not point acceptance automation at an existing application: tests copy these examples into fresh temporary directories and never overwrite the originals.
