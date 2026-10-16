# Specification: workspace-policy

Depends on `core-contracts`.

## Objective and contract

Make repository content untrusted input and enforce every privileged operation in code. `WorkspacePolicy` provides bounded reads, validated relative paths, source enumeration rules, secret filtering and effective permission calculation. A host-owned `PermissionGrant` is distinct from model/tool input. Neither source text, a skill nor a model response can create a grant.

Protected paths include `.git`, `.agentic` state, dependency/build/cache directories, credential files, `.env*`, private keys and configured exclusions. Internal state/configuration operations use separate narrow application-owned accessors; they do not expose state files to repository tools. Repository configuration cannot remove mandatory secret and state exclusions.

Reject absolute paths, `..`, NULs, platform drive/UNC paths, alternate-data-stream syntax, symlinks, non-regular files and hard-linked source files. Reads are bounded by bytes and total inventory limits. Known credential environment values and recognized credential patterns are removed before persistence, retrieval, provider transmission and logs. Files with detected secrets are not eligible for model-authored replacement.

Read-only analysis is portable. Guarded source mutation initially supports POSIX platforms with directory-relative file operations and no-follow flags; unsupported platforms fail closed instead of substituting a weaker writer. Root/parent/file identities and hashes are checked while holding a workspace writer lock. The policy is a file/tool guard, not an OS sandbox.

## Structure and style

Own `src/agentic_workbench/policy.py`, `secrets.py` and their tests. Use explicit operations such as `policy.read_source(relative_path)`; no arbitrary filesystem callbacks or shell strings. Return sanitized data or a stable typed error, never a raw credential-bearing exception.

## Commands and verification

`uv run --locked pytest tests/test_policy.py tests/test_secrets.py`. Tests cover traversal, Unicode/path variants, symlink parents and targets, FIFO/device files, hard links, file swaps, protected paths, permission escalation through skills/configuration, oversized input and secret filtering at each output boundary.

## Success criteria

- Traversal, aliasing and forbidden access fail before any source read/write or provider transmission.
- A malicious README, skill or configuration cannot grant network, execute tools or authorize mutation.
- Policy fingerprints include all effective limits, exclusions and grants; relevant policy changes invalidate privileged-operation approvals.

## Boundaries and open questions

Always fail closed at path/permission boundaries. Ask before changing exclusions, supported mutation platforms or permission semantics. Never claim protection against a malicious process running as the same OS user, a compromised host, arbitrary unknown secrets or kernel/container escape. Those are explicit deployment limits, not omitted checks.
