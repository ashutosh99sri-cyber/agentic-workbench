# Local candidate and owner release process

The public source preview has owner and private reporting records in
[MAINTAINERS.md](../MAINTAINERS.md) and [.github/release-owner.json](../.github/release-owner.json).
GitHub source publication does not publish a registry package or approve a tagged
release. The process below continues to govern those separate artifacts.

The repository can prepare a local candidate without a GitHub destination. A passing
local receipt is not permission to publish, proof of hosted CI, or a verified private
security reporting channel. See [maintainer responsibilities](../MAINTAINERS.md),
[support matrix](support-matrix.md) and [security reporting](../SECURITY.md).

## What the workflows require

CI is reusable and accepts only a full immutable source SHA. Pushes and pull requests
verify their event commit. Its Python 3.11–3.14 Linux/macOS matrix, Windows read-only
subset, Node 24/26 matrix and pinned-image Node/Python Docker acceptance are automatic.
The Python jobs install both wheel and sdist consumers and run them outside checkout.
Actual Docker tests fail when prerequisites are absent; a skipped suite is not evidence.
Images are provisioned before acceptance; the Runner still never pulls an image.
The Python Docker case proves that an unstartable entrypoint is an unusable baseline;
the seven Node cases exercise confinement and cleanup. These are different checks.

Manual release verification takes plain `X.Y.Z`, resolves the existing
`refs/tags/vX.Y.Z` to a commit, runs the entire reusable acceptance workflow on that
SHA, then packages that same SHA only after acceptance succeeds. It repeats clean
consumer and installed Node adapter checks, downloads JUnit/source receipts, verifies
artifact source bytes and records hashes. All actions are pinned, repository permission
is read-only, and the workflow has no publication credentials or publishing step.
Authored workflow tests do not establish that GitHub runners have executed them.

## Local verification, with exact evidence

Use a clean isolated checkout. Keep reports and distributions outside source or under
ignored `dist/`; do not delete someone else's build output. Install the locked dev
environment and trusted TypeScript compiler as shown in [CONTRIBUTING](../CONTRIBUTING.md).
Freeze source before generating final reports. Set `COMMIT` to that full Git SHA.

```sh
COMMIT=$(git rev-parse HEAD)
EVIDENCE=/absolute/path/to/new-evidence-directory
mkdir -p "$EVIDENCE/artifacts"
AGENTIC_REQUIRE_TYPESCRIPT=1 uv run --locked pytest -m 'not docker and not distribution' -W error --junitxml="$EVIDENCE/python.xml"
AGENTIC_DOCKER_IMAGE=node@sha256:d6aa754f16b3197301076f047b5def2f02ea1dbbc2ca920407d46d7ec7f87b20 uv run --locked pytest -m docker tests/integration/test_sandbox.py -W error --junitxml="$EVIDENCE/docker-node.xml"
AGENTIC_DOCKER_IMAGE=python@sha256:e88e9763f943ec1834f992a4b51e0f24500486803e8bc534e5767af9ea65f6ce uv run --locked pytest -m docker tests/integration/test_python_repair.py -W error --junitxml="$EVIDENCE/docker-python.xml"
uv run --locked ruff check src tests scripts
uv run --locked ruff format --check src tests scripts
uv run --locked mypy src/agentic_workbench
uv audit --locked --output-format json
uv build --out-dir "$EVIDENCE/artifacts"
```

Each job must also create its `source.json` **where the tests actually execute**,
using `git rev-parse HEAD`. Ordinary Python receipt: `{"commit":"<full SHA>"}`.
Docker receipts additionally contain `node_image` or `python_image` with the actual
pinned reference used by that job. The committed workflows generate these companion
receipts automatically. They are consistency records supplied by the operator, not
cryptographic attestation. Do not fabricate them for tests that did not execute.

Install the wheel and sdist separately into fresh venvs, then run
`scripts/verify_distribution.py` using each installed Python from outside checkout.
Run installed SDK type acceptance with
`AGENTIC_INSTALLED_PYTHON=/absolute/path/to/clean/bin/python uv run --locked pytest tests/test_packaging.py -m distribution -W error`.
Run `examples/sdk_walkthrough.py --execute` with that clean Python; it must verify source
analysis, imported proposal planning, a failed then passing synthetic check, and exact
rollback without importing a paid provider. The offline suite separately checks each
of the eight roles and their coordinated graph, including mocked OpenAI SDK transport. CI and manual release verification include
these consumer gates. This does not establish live provider quality.

Build/test the Node adapter against the clean installed `agentic` executable and run
its locked audit and example type check. The [MCP host check](integrations/mcp-editors.md)
and [provider recipe check](integrations/provider-adapters.md) have separate,
explicitly bounded acceptance. Ordinary CI never invokes a paid provider.

```sh
uv run --locked python scripts/record_release_evidence.py \
  --expected-commit "$COMMIT" --artifacts "$EVIDENCE/artifacts" \
  --junit "python=$EVIDENCE/python.xml" \
  --junit "docker-node=$EVIDENCE/docker-node.xml" \
  --junit "docker-python=$EVIDENCE/docker-python.xml" \
  --source-receipt "python=$EVIDENCE/python-source.json" \
  --source-receipt "docker-node=$EVIDENCE/node-source.json" \
  --source-receipt "docker-python=$EVIDENCE/python-docker-source.json" \
  --node-image node@sha256:d6aa754f16b3197301076f047b5def2f02ea1dbbc2ca920407d46d7ec7f87b20 \
  --python-image python@sha256:e88e9763f943ec1834f992a4b51e0f24500486803e8bc534e5767af9ea65f6ce \
  --output "$EVIDENCE/release-receipt.json"
```

The collector requires clean exact HEAD, all three nonempty suites with zero failures,
errors or skips, actual Docker case identities, matching source/image receipts, one
wheel and one sdist, safe bounded archives, runtime bytes identical to Git and console entry points matching
the committed project configuration. It
records wheel/sdist versions and artifact SHA256 hashes; npm archives, if supplied,
receive hashes (their generated JavaScript is verified by the CI build/tests).
It always returns `publication_ready: false`. Owner metadata, including a populated
`.github/release-owner.json`, is configuration, never approval or proof of an operating
reporting channel. Review the exact commit, tree, report hashes and artifact hashes.

## Tagged and public releases

Version comes from Git through setuptools-scm. Review the diff/evidence, update the
changelog and commit source before creating the intended `vX.Y.Z` tag. Existing tags
stay immutable; fixes require a new tag. Build after tagging.
`uv run --locked python scripts/check_release.py` checks local essentials without a
tag. `--expected-version X.Y.Z` additionally requires an existing exact tag, clean HEAD
at that tag and matching installed metadata. Pass the same option to the evidence
collector for a tagged candidate. Retain distributions, receipts and SHA256SUMS; never
include `.agentic`, credentials, user/editor state or local environment files.

Before publication the owner must create/choose the remote, fill real maintainer and
support metadata, enable and verify a private reporting channel, configure actual
required checks/review policy, verify exact-commit hosted CI and package registry
ownership, and approve the exact artifact hashes. Copy CODEOWNERS.example only after
replacing placeholders with real authorized reviewers. See MAINTAINERS for triage and
contribution review. This implementation creates no remote, account, public contact,
publication token, registry release or GitHub release.
