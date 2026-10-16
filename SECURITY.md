# Security reporting

Use **Security → Report a vulnerability** in
[this repository's private vulnerability reporting form](https://github.com/ashutosh99sri-cyber/agentic-workbench/security/advisories/new).
GitHub private vulnerability reporting was enabled and verified through GitHub's
repository API on 17 October 2026. The responsible maintainer is
[@ashutosh99sri-cyber](https://github.com/ashutosh99sri-cyber); the real repository,
support and reporting URLs are recorded in [.github/release-owner.json](.github/release-owner.json).

Keep suspected vulnerabilities, exploit details, credentials and sensitive traces
out of public issues and pull requests. If the private form is unavailable,
retain the details privately until the maintainer restores the channel. Conduct
concerns follow the private-channel request procedure in [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
Neither policy promises a response time or establishes a security certification.

Include the exact version and Git revision, operating system and runtime, affected trust boundary, minimal reproduction, expected/actual behavior, impact and redacted evidence. Use a disposable repository and synthetic credentials. State whether any request, source write or external effect occurred and whether reproduction could incur provider cost. Share sensitive evidence only through the verified private channel.

Priorities include path/symlink/alias escape, approval or grant bypass, credential leakage, unintended paid replay, source loss and removal of unrelated containers. Static findings need source evidence and a demonstrated reachable boundary; framework detection alone is not a vulnerability. Maintainers should acknowledge privately, reproduce against the reported revision, agree on disclosure with the reporter and release a verified fix with affected-version guidance. No response-time guarantee is established.

Version 0.1.0 is the initial release candidate; no older-version maintenance window is promised. See the [support matrix](docs/support-matrix.md) for scope and [security model](docs/security.md) for OS-owner, advisory-lock, Docker-daemon and explicit host-runner limits. This guidance is not a security certification.
