# Maintainer setup and workflow

The public developer preview is owned and maintained by
[@ashutosh99sri-cyber](https://github.com/ashutosh99sri-cyber), who confirmed
maintainer responsibility and source/brand distribution rights on 17 October
2026. [.github/release-owner.json](.github/release-owner.json) records the real
repository, support and private security-reporting URLs; [.github/CODEOWNERS](.github/CODEOWNERS)
assigns source review. Conduct reports use the owner-authorized contact in
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). There is no response-time guarantee.

GitHub private vulnerability reporting is enabled. Package registry ownership
and registry releases are separate from this source preview and remain unverified.

For subsequent releases, the repository owner must keep these records current:

1. Name consenting maintainers and a reachable support destination. Copy `.github/release-owner.example.json` to `.github/release-owner.json`, replace every blank value and empty maintainer list with verified details, and confirm the repository and package registries are owned by the intended account. Never put credentials in this file. Follow the [release process](docs/releasing.md) to verify that configuration.
2. Establish and test a private vulnerability-reporting channel, then update [SECURITY.md](SECURITY.md) and the owner metadata with its real URL. Public issues are not a substitute.
3. Replace the placeholders in `.github/CODEOWNERS.example`, save the reviewed rules as `.github/CODEOWNERS`, and verify that each handle or team can review this repository. The example file does not request reviews. Configure required reviews and CI checks on the actual remote separately.
4. Verify public issue/support links, maintainer access, package ownership and the release gates. A filled template alone is not approval to publish.

| Role | Responsibility |
| --- | --- |
| Repository owner | Maintain access, assign reviewers, configure remote protections and owner metadata, approve publication. |
| Change reviewer | Reproduce the problem, review compatibility and trust boundaries, inspect regression evidence and document skips. |
| Security responder | Receive private reports, reproduce safely, coordinate disclosure and verify fixes. |
| Release owner | Run the release checks, verify tag/commit/artifact provenance and registry ownership, record acceptance and release decisions. |

For each non-security issue, check the exact revision, support matrix and synthetic reproduction. Ask for missing evidence without requesting secrets. Classify it as a bug, enhancement, documentation change or question; record whether it needs reproduction, is confirmed, is a duplicate or is outside current support. These are proposed triage states, not pre-created GitHub labels. If the owner creates labels, keep them limited to those categories and states. Link duplicates and explain closures. Keep suspected security reports private and follow [SECURITY.md](SECURITY.md).

For a pull request, assign a reviewer, confirm the scope and affected callers, check meaningful regressions and the contributor's actual test evidence, and review source/budget effects before merge. Do not equate authored CI with a successful remote run. Record remaining platform or integration gaps. [CONTRIBUTING.md](CONTRIBUTING.md) supplies the local checks.

Use semantic versions for public CLI, SDK, result-envelope and skill contracts. Document compatibility changes and migrations in the changelog; do not alter an existing release tag or replace an artifact under the same version. The initial 0.1.0 candidate has no promised older-version maintenance window. Assign backports and deprecation support explicitly before promising them. Follow [docs/releasing.md](docs/releasing.md) for the separate owner-approved release process.
