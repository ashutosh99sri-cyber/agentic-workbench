# Getting help

This repository is an experimental public developer preview maintained by
[@ashutosh99sri-cyber](https://github.com/ashutosh99sri-cyber). Use the
[issue forms](https://github.com/ashutosh99sri-cyber/agentic-workbench/issues/new/choose)
for non-security bugs and feature requests. No response-time or maintenance
guarantee is established. See [maintainer responsibilities](MAINTAINERS.md).

For installation and usage, start with the [installation guide](docs/installation.md), [CLI/SDK guide](docs/api.md), [recovery guide](docs/recovery.md) and [support matrix](docs/support-matrix.md). Keep one problem per issue, search existing issues first, and include:

- The exact `agentic --version` output and Git revision, install method, OS/architecture, Python, Node and Docker versions relevant to the problem.
- A small disposable reproduction with synthetic inputs, commands, expected/actual behavior and a redacted trace or error code.
- Test evidence, skipped prerequisites and whether source changes, network calls or budget effects occurred.

Do not attach API keys, private source, `.agentic/` state, approval digests, raw provider payloads or unredacted environment output. Review attachments yourself; automated secret redaction is not complete. A suspected vulnerability belongs in a verified private channel under [SECURITY.md](SECURITY.md), never in a public issue or pull request.

Maintainers may ask for a smaller reproduction, route a platform limitation to documentation, or close duplicates with a link to the tracked issue. A request does not authorize provider spending, source mutation, remote publication or an external account change. [CONTRIBUTING.md](CONTRIBUTING.md) explains how to prepare a tested change.
