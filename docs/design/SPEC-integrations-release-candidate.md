# Recommendations 9 and 10: integrations and local release candidate

Status: implementation contract, 2026-10-15.
Baseline: fda7de3e74a9b5d6726c52da8f328a27da0f432d.

The accepted assessment asks for documented MCP/editor and provider recipes with
contract tests, one actual host interoperability check, and public release/CI/
maintainer infrastructure. The user delegated the destination choice: prepare
and verify a local candidate first. No remote, publication identity, reporting
address, owner approval, or paid inference is invented by this implementation.

## Boundaries and ownership

Preserve the primary checkout HEAD, index, staged edits and unrelated source.
Develop on codex/integrations-release-candidate; integrate only reviewed deltas.
Coordinate through ../outputs/COORDINATION.md. Previous implementation lanes stay
frozen. Claude owns only the MCP recipe, its verifier and contract tests, plus
mcp.py only after a demonstrated interoperability defect is reported. Native
workers own the provider recipe, CI workflows and maintainer intake separately.
Root owns this contract, release evidence, packaging and shared documentation.

No new runtime dependency, autonomous external harness, HTTP client framework,
global editor configuration, credential setup, model call or publication flow.
Existing policy, ProviderRegistry, intent, budget, schema and MCP interfaces apply.

## Recommendation 9 acceptance

- A trusted callback provider example registers explicitly with ProviderRegistry.
  It reserves budget before dispatch, records intent/outcome, validates bounded
  structured output and usage, and treats ambiguous transport outcomes as unknown.
  The callback receives no tool executor or credentials. Cooperative timeout and
  host transport responsibilities are documented. Regression tests include denied
  authority, rejection, malformed output, budget exhaustion and unknown outcomes.
- A disposable Python repair uses that adapter and the actual approved executor.
  A fixed known candidate proves wiring and verification, not model intelligence.
- Copyable MCP configs cover Claude Code, VS Code and Cursor. Offline is explicit
  with --provider none; no execution, mutation or approval tool is exposed.
  Docs explain that source excerpts go to the host and its model.
- Contract tests launch the real stdio server, negotiate initialize, list tools
  and call a read-only tool on synthetic source. No source mutation is allowed.
- One installed Claude Code host check uses throwaway HOME/CLAUDE_CONFIG_DIR,
  no credentials, macOS outbound-network denial and a hard timeout. It records
  whether the host only initializes, lists tools, or invokes one. Other hosts
  remain unverified. Project-server approval and source disclosure are explicit.

## Recommendation 10 acceptance

- PR/push CI runs the declared Python Linux/macOS matrix, Windows read-only
  subset, Node matrix and actual pinned-image Node/Python Docker acceptance.
  Clean wheel and sdist consumers run outside the source checkout.
- Reusable CI accepts an optional immutable source_ref. Release preparation
  resolves an existing version tag; acceptance and package jobs use that exact
  SHA. Packaging depends on acceptance. All actions are pinned, permissions are
  contents:read, no credentials or publication are added.
- JUnit and source.json artifacts bind Python and both Docker suites to the
  actual checkout commit. Docker receipts also bind their pinned image reference.
- scripts/record_release_evidence.py accepts --expected-commit SHA,
  --artifacts DIR, --junit LABEL=FILE and --source-receipt LABEL=FILE for labels
  python, docker-node, docker-python, --python-image REF, --node-image REF,
  --output FILE and optional --expected-version VERSION.
- Evidence collection requires a clean exact Git HEAD, nonempty passing JUnit
  suites with zero skips, the expected actual Docker case identities, matching
  source receipts and pinned images. It checks wheel/sdist runtime bytes against
  Git source, rejects unsafe archive entries and records artifact SHA256 hashes.
  A receipt is evidence from the running environment, not remote attestation.
- Output explicitly describes a verified local candidate. Public readiness is
  false until real remote CI, owner release approval, package ownership and an
  operational private reporting channel are independently established.
- Maintainer docs, support matrix, first-contribution commands, issue/PR forms,
  CODEOWNERS example and release-owner metadata example contain no invented
  identities or support commitments. .github/release-owner.json is the future
  concrete metadata path; the example is not approval or operational evidence.

## Verification and delivery

Use failing regression tests before nontrivial logic, focused checks per slice,
then a fresh complete offline suite, strict mypy/Ruff, Node contract checks,
actual Docker acceptance and clean installed wheel/sdist checks. Freeze source
before final evidence. Run positive collection and negative stale-source,
skipped/empty suite, wrong image and tampered-artifact controls. Retain exact
commands, receipts and limitations under ../outputs/agentic-rec9-10-t7gqc4qm.
A passing fixture or local workflow-source test never establishes hosted CI,
provider task success, or a production release. Preserve primary user changes
when applying the reviewed delta, then verify installed commands and source.
