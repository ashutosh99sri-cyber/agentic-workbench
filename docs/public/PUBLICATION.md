# Source-preview publication record and release procedure

The owner approved a public current-source snapshot at
[ashutosh99sri-cyber/agentic-workbench](https://github.com/ashutosh99sri-cyber/agentic-workbench)
on 17 October 2026, including Apache-2.0 distribution rights, WOOKhoop branding,
maintainer responsibility and the separately documented conduct contact. GitHub
private vulnerability reporting is enabled. Earlier development history remains
local. Actual source identity and hosted acceptance are visible in GitHub;
[readiness](READINESS.md) retains the local evidence and limits.

The checklist below remains the procedure for subsequent tagged or registry
releases. The source-preview approval does not approve those releases, claim a
stable product, or establish registry ownership.

## Repository presentation

Suggested display name: **WOOKhoop Agentic Workbench**.

Suggested repository description:

> A Python framework for source-grounded coding workflows: explicit approvals, verified Python repair, durable recovery, and CLI, SDK, Node and MCP integration.

Suggested topics: `ai-agents`, `agent-harness`, `developer-tools`, `python`, `mcp`, `code-analysis`, `human-in-the-loop`, `software-engineering`, `workflow-automation`, `typescript`.

The brand is WOOKhoop. Distribution/import/command names remain `agentic-workbench`, `agentic_workbench` and `agentic`; the existing alias and Node package contract remain compatible. Confirm any future namespace with the registry before advertising it. No package-name availability is assumed.

## Ordered release checklist

- [ ] Owner attests to original-code, documentation, fixture, contribution and brand rights; resolve employment/client restrictions and any third-party exceptions.
- [ ] Select real maintainers, a verified private reporting channel, support policy and escalation responsibility. Update `SECURITY.md`, `CODE_OF_CONDUCT.md` and contact documentation with verified information.
- [ ] Review `LICENSE`, `NOTICE`, `THIRD_PARTY_NOTICES.md` and any bundled dependency/image obligations. Keep provenance for upstream snippets.
- [ ] Choose full reviewed Git history or a current-source export. Review historical author/path metadata. Do not rewrite or discard the development history automatically.
- [ ] Choose the destination account and repository; confirm permission and package namespace ownership. Do not infer a GitHub owner from a domain or local Git identity.
- [ ] Select the exact clean candidate commit and inspect its diff, Markdown links, PDF, SVGs and archive. Exclude private `.agentic/` data, secrets, local outputs and numbered duplicate files.
- [ ] Run source, security, dependency, lint/type, unit/integration and appropriate Docker checks on that exact commit. Retain command output and environment/version evidence. Distinguish offline tests from live model task success.
- [ ] Build wheel and sdist from the same clean source. Inspect licenses and packaged skills/schemas/parser files. Verify both with fresh installed consumers outside the checkout. Build/test the Node adapter where it is included.
- [ ] Review release artifacts and SHA-256 values. Document known limitations, supported platforms and recovery steps. Do not treat a successful build as a security or ownership clearance.
- [ ] Obtain explicit owner approval to make the named repository and selected history public. This checkbox requires an actual decision; it is not satisfied by this document.
- [ ] After approval, configure the real hosted settings, publish source, run hosted checks and retain their actual links. Publish registry packages only after separate artifact/namespace approval.
- [ ] Verify the public landing page, install instructions, release assets, private reporting path and required checks from a clean consumer environment. Add real CI/release badges only when their target URLs exist.

## Recommended GitHub settings

Before merging changes publicly, require pull requests and reviews on the default branch, dismiss stale approvals as appropriate, require the actual CI status checks emitted by the workflows, prevent force pushes/deletion, and restrict bypass permissions. Map these controls to the destination account's available features; none are configured by this file.

Enable dependency review/advisories and supported secret scanning/push protection. Set workflow token permissions to least privilege, keep publishing credentials in the appropriate protected environment, and use trusted publishing only after registry ownership is verified. Review external actions and workflow changes as code. Copy `.github/CODEOWNERS.example` into a real CODEOWNERS file only after named maintainers agree.

Enable issues and the supplied templates. Use discussions when maintainers have capacity to moderate them. Publish a real roadmap with bounded scope and reproducible contribution examples. Enable private vulnerability reporting where available and test it with the designated maintainers. GitHub documents its setup [here](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/configure-vulnerability-reporting/configure-for-a-repository); a draft setting is not an operational channel.

## Versioning and release notes

Proposed next public version: **v0.2.0**, marked as a **GitHub prerelease** until broader acceptance is complete. This is a recommendation, not an existing tag. Current release scripts validate plain `X.Y.Z` values; a GitHub prerelease flag is separate from the tag syntax. Do not create an `alpha` suffix without updating and testing that contract.

Use a minor version for intentional feature/API changes during the pre-1.0 period and a patch version for compatible fixes. Document API changes and migration instructions. Reserve v1.0 for defined compatibility, support and acceptance expectations. The actual version must be selected and approved with the final artifacts, rather than inferred from these notes.

Use [draft release notes](RELEASE-NOTES.md) as a starting point, update them to the exact selected commit and include real checksums. Follow [the existing release procedure](../releasing.md), including its owner manifest and evidence gates. Never label a local candidate as a published release.

## Adoption without unsupported claims

Lead with one completed offline exercise and three honest use cases: understanding a module, reproducing/reviewing a Python fix, and embedding a controlled workflow in an internal tool. Keep commands copyable, report supported platforms clearly and link source evidence for claims.

Recruit a small group of Python maintainers and AI engineers to finish an unfamiliar-project task. Measure time to first verified result, setup failures, review minutes, accepted fixes, regression failures, tokens, latency and spend. Preserve failed and blocked tasks. Use this evidence to prioritize work before broad marketing or comparisons.

Publish short original walkthroughs, good-first-issue tasks and small reproducible bug reports. Keep English documentation accessible; accept reviewed translations after the English commands are stable. Describe interoperability with established tools without claiming superiority. Track completed workflows and repeat usage alongside repository stars.
