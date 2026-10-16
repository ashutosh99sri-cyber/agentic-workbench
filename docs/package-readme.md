# Agentic Workbench

A Python CLI and SDK for supervised AI-assisted development, with a typed Node
adapter. Inspect a repository, gather source evidence, review a proposed change,
approve its exact digest, run a separately approved check, and recover or roll back.

Version 0.1.1 is a pre-1.0 developer preview. APIs may change; pin versions.

## Install

Requires Python 3.11 or newer. Use a dedicated environment:

```sh
python3 -m venv .venv-agentic
.venv-agentic/bin/python -m pip install "agentic-workbench==0.1.1"
.venv-agentic/bin/agentic --version
.venv-agentic/bin/agentic --help
```

For a Node 24+ application, install the Python CLI first, then
`npm install --ignore-scripts @agentic-workbench/node@0.1.1`. Configure the adapter
with the absolute path to that installed `agentic` executable.

## Start offline

Replace the root with a project you control and `app.py` with one of its source files:

```sh
.venv-agentic/bin/agentic init --root /absolute/path/to/application
.venv-agentic/bin/agentic scan --root /absolute/path/to/application
.venv-agentic/bin/agentic explain app.py --root /absolute/path/to/application --provider none
```

Ignore `.agentic/` in the target project's Git configuration: it holds private
task state, source results, diffs and rollback content. Analysis preserves source
but can write that local state. No target dependencies are installed automatically.

Eight roles cover discovery, code intelligence, engineering, architecture, UX,
testing, documentation and orchestration. Ten packaged skills, retrieval, source
context, persistent execution and resumable workflows share the same policy layer.

## Permissions and limits

The provider defaults to disabled. Optional OpenAI access requires the `[openai]`
extra, a configured model, an external credential and an explicit network grant.
Inject credentials from a host secret manager or use `--prompt-key` interactively;
never put secrets in source, arguments, project configuration or chat.

Source changes and command execution require separate exact approvals. Guarded
changes and Runner execution require POSIX. Windows supports the documented
read-only subset. Docker execution requires a trusted daemon and an already-present
digest-pinned image. Explicit trusted-host execution has no OS sandbox and requires
a protected executable owned by the user or root, without group/world write access.

Offline and mocked-provider tests verify workflow contracts; they do not establish
live-model quality, cost savings or autonomous heavy-task effectiveness.

## Documentation

- [Installation and platform requirements](https://github.com/ashutosh99sri-cyber/agentic-workbench/blob/main/docs/installation.md)
- [CLI and Python SDK reference](https://github.com/ashutosh99sri-cyber/agentic-workbench/blob/main/docs/api.md)
- [Node adapter](https://github.com/ashutosh99sri-cyber/agentic-workbench/blob/main/adapters/node/README.md)
- [Offline repair tutorial](https://github.com/ashutosh99sri-cyber/agentic-workbench/blob/main/examples/offline_repair/README.md)
- [Security model](https://github.com/ashutosh99sri-cyber/agentic-workbench/blob/main/docs/security.md)
- [Changelog and release records](https://github.com/ashutosh99sri-cyber/agentic-workbench/blob/main/CHANGELOG.md)

Apache-2.0 for original contributions, with retained third-party notices.
[Source and contribution guide](https://github.com/ashutosh99sri-cyber/agentic-workbench).
