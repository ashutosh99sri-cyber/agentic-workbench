# Contributing

Start with a small, reproducible issue or documentation correction. For a larger interface or security change, describe the affected callers, trust boundary, tests and compatibility before implementation. Keep core policy independent of providers/frameworks, preserve the v1 envelope and actual source citations, and follow the module specifications and dependency map in `docs/design/`.

Follow the [community conduct policy](CODE_OF_CONDUCT.md). Contribute only material you have the right to share under the project's stated license. Identify copied or adapted third-party material, its source, license and required notices; do not replace its terms with a project ownership claim. See the [licensing guide](docs/public/LICENSING.md) and [third-party notices](THIRD_PARTY_NOTICES.md). The owner must confirm distribution rights and security reporting and conduct intake procedures before public release.

From a checkout on Linux or macOS with Python 3.11+ and uv installed, use the committed lockfile:

```sh
uv sync --locked --all-extras
uv run --locked agentic --help
uv run --locked pytest -m "not docker and not distribution" -W error
uv run --locked ruff check src tests scripts
uv run --locked ruff format --check src tests scripts
uv run --locked mypy src/agentic_workbench
```

The default test run can skip optional native TypeScript coverage when its runtime is absent. For changes to TypeScript analysis or the Node adapter, install Node 24+ and the locked adapter dependencies; do not omit optional dependencies because TypeScript 7.0.2 uses a native platform package. Run these commands from the checkout root:

```sh
cd adapters/node
npm ci --ignore-scripts
npm run build
npm test
cd ../..
AGENTIC_REQUIRE_TYPESCRIPT=1 uv run --locked pytest tests/test_typescript.py -W error
```

Setting `AGENTIC_REQUIRE_TYPESCRIPT=1` makes a missing native runtime fail the selected check. Native analysis requires POSIX macOS/Linux on arm64 or x64; Node alone does not enable it. See the [support matrix](docs/support-matrix.md) and [TypeScript analysis guide](docs/typescript-analysis.md).

Before a pull request, build the wheel and source distribution into a fresh directory and verify a clean installed wheel. These POSIX commands keep existing build output intact:

```sh
acceptance_dir=$(mktemp -d)
uv build --out-dir "$acceptance_dir/dist"
uv venv "$acceptance_dir/venv"
uv pip install --python "$acceptance_dir/venv/bin/python" "$acceptance_dir"/dist/*.whl
"$acceptance_dir/venv/bin/python" scripts/verify_distribution.py
uv run --locked python scripts/check_release.py
```

For Node changes, also run the real installed-CLI integration after building the adapter above:

```sh
cd adapters/node
AGENTIC_EXECUTABLE="$acceptance_dir/venv/bin/agentic" npm run test:integration
cd ../..
```

`AGENTIC_EXECUTABLE` must name the absolute installed CLI executable; an unset value fails the check. For runner changes, additionally select explicitly approved, already-local digest-pinned Node 24+ and Python images and run both real Docker suites:

```sh
AGENTIC_DOCKER_IMAGE='node@sha256:REPLACE_WITH_APPROVED_LOCAL_IMAGE_DIGEST' \
  uv run --locked pytest -m docker tests/integration/test_sandbox.py -W error
AGENTIC_DOCKER_IMAGE='python@sha256:REPLACE_WITH_APPROVED_LOCAL_IMAGE_DIGEST' \
  uv run --locked pytest -m docker tests/integration/test_python_repair.py -W error
```

Replace the digest placeholders before running. The runner does not pull images; provision the reviewed images separately. CI declares these Docker suites as automatic checks, but a hosted result exists only after the exact commit runs there. State which checks you ran, their exact revisions and any skips in the pull request. Windows contributors can use the read-only checks listed in the support matrix; guarded writes and execution require POSIX.

Write behavioral regressions for meaningful logic and security boundaries. Avoid tests that merely restate implementation. Test denial, source drift, partial writes, ambiguous external effects, serialization, package resources and honest coverage. Keep test source contained in disposable owned examples. Never commit credentials, `.agentic/`, private materials or generated dependency environments.

Use small conventional commits. Update public documentation and CHANGELOG for consumer changes. Preserve concurrent work and maintain backward compatibility within the v1 CLI/result/skill contracts. New providers are explicit trusted SDK integrations; repository content cannot auto-register executable modules. Original contributed code/instructions use Apache-2.0, with third-party provenance and licenses recorded.

Review correctness, maintainability, security, performance and user impact. Include redacted traces or a synthetic reproduction, never API keys, `.agentic/` state dumps, private source, approval digests or raw provider payloads. Report a suspected vulnerability privately using [SECURITY.md](SECURITY.md); do not put exploit details in an issue or pull request.

CI does not send paid provider requests. Transport fixtures validate the locked official SDK, not live model quality. Live provider acceptance requires an explicitly authorized environment and budget; report request/token estimates and any observed cost separately from offline results. Remote publication remains a separate owner action in the [release process](docs/releasing.md). [MAINTAINERS.md](MAINTAINERS.md) describes the proposed local review roles and the owner configuration required before public release.
