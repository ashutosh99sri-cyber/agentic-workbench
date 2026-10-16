Describe the user-visible problem, current behavior and resulting behavior. Link the non-security issue if one exists. Keep suspected vulnerabilities and sensitive evidence private under [SECURITY.md](../SECURITY.md).

## Scope and reproduction

- Exact base/head Git revisions and `agentic --version`:
- OS/architecture and relevant Python, Node/TypeScript or Docker versions:
- Minimal synthetic reproduction; expected and actual behavior:
- Affected callers/contracts and compatibility or migration impact:

## Evidence and effects

- Exact checks run and results (include skipped prerequisites; distinguish local results from remote CI):
- Redacted trace or error code, or why no safe trace is available:
- Source-write, execution/container, network/provider and budget effects (use none or unknown explicitly):
- Remaining risk or support-matrix limitation:

## Review checklist

- [ ] I reviewed the diff and attachments for secrets/private data; no credentials, `.agentic/` dumps, approval digests or raw provider payloads are included.
- [ ] I included meaningful regression evidence or explained why this change needs no behavioral test.
- [ ] I updated affected documentation/changelog, or explained why no update is needed.
- [ ] I ran the relevant checks in [CONTRIBUTING.md](../CONTRIBUTING.md) and recorded failures/skips honestly.

This pull request does not approve provider spending, registry publication or a release. Owner configuration and the separate release gates still apply.
