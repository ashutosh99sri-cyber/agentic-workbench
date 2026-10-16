# Installation tutorial

Install the Python package into a dedicated project environment as shown in the README. You can also install a built wheel with `python -m pip install /absolute/path/to/agentic_workbench-0.1.0-py3-none-any.whl`. The package ships JSON schemas and ten original skill packages. Run `agentic --version` from outside this checkout to verify the installed entry point.

`agentic init --root /absolute/path/to/application` creates private `.agentic/` state. It does not rewrite source or replace valid existing settings. Ignore that directory in Git. Configuration is TOML, schema version 1. Unknown keys, credential values used as model names, shell command strings and permission fields are rejected. Credentials belong in the host process environment; do not place them in this repository, proposal JSON or conversation.

For a clean installed SDK acceptance example, run the repository's
`examples/sdk_walkthrough.py` with the installed environment's Python. Its default
path is offline analysis; `--execute` opts into a predefined synthetic fix, trusted-host
unittest and byte-identical rollback in a disposable directory. See the
[developer adoption guide](developer-adoption.md).

Start offline:

```sh
agentic scan --root /absolute/path/to/application --json
agentic explain app.py --root /absolute/path/to/application --json
agentic search "discount total" --root /absolute/path/to/application --json
agentic plan "Investigate percentage discounts" --root /absolute/path/to/application --json
```

For optional OpenAI use, install the reviewed checkout with the `[openai]` extra into
the same isolated environment, choose an account-available model, and grant network
for that invocation. An interactive terminal can collect a key without echo or shell
history:

```sh
agentic explain app.py --root /absolute/path/to/disposable-copy \
  --provider openai --model YOUR_MODEL --allow-network --prompt-key
```

The key is held only in this process environment and removed or restored afterward.
For automation, inject the configured `credential_env` from your secret manager.
Never put the key in an argument, TOML, source or chat. `--prompt-key` also supports
provider-backed `plan`, `run`, `resume`, `execute`, `repair`, and semantic/combined
`search`; it grants no source write or command approval. Review provider source
transmission and account costs before opting in. See [providers](providers.md).

On Windows PowerShell, the environment's entry points live under `Scripts`:

```powershell
.\.venv-agentic\Scripts\agentic.exe --version
.\.venv-agentic\Scripts\agentic.exe scan --root C:\src\application --json
.\.venv-agentic\Scripts\agentic.exe explain app.py --root C:\src\application --json
```

Use the environment path you installed into. Windows support is limited to the documented read-only operations; guarded changes and Runner execution require POSIX. The authored Windows CI subset does not establish support for source mutation or descendant process cleanup.

For a complete provider-free repair, use the [offline repair walkthrough](../examples/offline_repair/README.md). It creates a fresh disposable workspace, demonstrates a failing check, reviews a hash-bound patch, pauses for separate approvals across reopened sessions, verifies a passing check, and rolls back. It requires an explicit trusted-host opt-in for its supplied unittest fixture and never uses an existing application as its target.

Framework selection uses source manifests/imports. Python, Node/TypeScript, Go, Rust, Java, .NET, Ruby and PHP have manifest detection. Detection is an inventory fact, not compiler-level analysis for each language. Coverage reports show inaccessible, oversized, ignored and capped scope.

To exercise imported changes, copy an example into a disposable folder. Create a JSON proposal containing `schema_version: 1`, `rationale`, and `edits`. An edit has relative `path`, SHA-256 `base_hash` of current UTF-8 source (null for creation), full replacement `content`, and `delete: false`. Deletion uses a non-null base hash, null content and `delete: true`. Optional evidence contains current path/line/hash citations. `agentic plan "Reviewed example change" --proposal-file /absolute/path/to/proposal.json --root /absolute/path/to/disposable-copy` validates and stores the proposal.

Inspect the returned `proposals` diff/digest. `agentic apply PROPOSAL_ID --root /absolute/path/to/disposable-copy` reviews it again; `--approve DIGEST` applies only that exact current proposal. A wrong or stale digest fails. Inspect the result's change ID and retain its journal for rollback. Never transplant a proposal or approval into another workspace.

Configure a named test command. For Python use an absolute isolated Python executable plus `-m unittest -q`; no automatic package installation occurs. Docker commands use container executables and require an approved present digest-pinned image. Review and execute with `agentic test --command-id unit`; use `--trusted-host` only when consciously accepting host execution. Read-only snapshots may require your test configuration to put build/cache output in `/tmp`.

Maintainers use `UV_LINK_MODE=copy uv sync --locked --all-extras`. uv installs must use copy mode because the skill loader rejects hard-linked files; use `UV_LINK_MODE=copy uv pip install ...` for clean consumers too. See the [uv link-mode setting](https://docs.astral.sh/uv/reference/settings/#link-mode). Hosted CI selects managed Python so its executable meets Runner ownership and non-writable-by-group/others requirements; a rejected host executable must be replaced with a trusted installation, without weakening the guard. Some macOS synchronized Documents locations can mark editable `.pth` files hidden and prevent Python imports. A clean wheel installation or a task-local environment outside the synchronized folder avoids that issue without changing global flags or shell configuration. The delivered wheel was tested in a separate environment.
