# Use the workbench from an MCP editor or agent host

`agentic mcp` is a stdio [Model Context Protocol](https://modelcontextprotocol.io) server. With it, Claude Code, VS Code, Cursor and other MCP hosts can read and review one local workspace from inside their own agent loop. Copyable configurations live in [examples/integrations/mcp](../../examples/integrations/mcp/).

## What the server exposes

| Tool | What it does |
| --- | --- |
| `scan` | Workspace inventory: files, languages, frameworks, symbols and calls |
| `explain` | Cited explanation of a file, symbol or query |
| `search` | Lexical search over current source, cited by path, line span and hash |
| `impact` | Cited definitions, callers, imports, references and tests for changed files |
| `plan` | Coordinated analysis; returns proposal IDs, never writes source |
| `run` | Runs one agent role on an instruction |
| `status` | State and result of one task |
| `review` | Diff and digest of one stored proposal |

These are all of the server's tools.

- No tool writes source, runs tests or commands, rolls back, or approves anything. A call to any other tool name is rejected.
- Applying a change, running a check and approving are separate host actions, outside MCP: `agentic apply`, `agentic test`, `agentic repair`, or the Python SDK, each with its exact approval digest.
- A digest shown by `review` is information, not authority.

## What the host and its model see

Tool results go to the host, and through it to the host's model. Results include source excerpts, symbols, paths and proposal diffs.

- The server reads the workspace through its normal policy: exclusions, bounds and secret redaction. It keeps its own state under `.agentic/` in that workspace.
- Register it only for workspaces whose contents you are willing to share with that host and its model provider.

Every example passes `--provider none`, so the server makes no model calls of its own: `plan` and `run` stay static, offline analysis. Without that flag, a provider configured in the workspace's `.agentic/config.toml` could be used. Even then, it would make network requests only if you also add `--allow-network`.

## Claude Code

Register the server from a terminal, using absolute paths:

```bash
claude mcp add agentic -- /absolute/path/to/venv/bin/agentic mcp \
  --root /absolute/path/to/application --provider none
```

That command uses Claude Code's default local scope, which stores the server in your Claude Code user configuration for the current project only. To share the setup with a team instead, commit [claude-code.mcp.json](../../examples/integrations/mcp/claude-code.mcp.json) as `.mcp.json` at the project root. Claude Code asks each user to approve project servers. Until a user approves, `claude mcp list` shows the server as pending, and Claude Code does not start it. Check the result with `claude mcp list` or `claude mcp get agentic`.

## VS Code

Copy [vscode.mcp.json](../../examples/integrations/mcp/vscode.mcp.json) to `.vscode/mcp.json` in the workspace and replace the two absolute paths. VS Code reads servers from the `servers` key.

## Cursor

Copy [cursor.mcp.json](../../examples/integrations/mcp/cursor.mcp.json) to `.cursor/mcp.json` in the project, or to `~/.cursor/mcp.json` for every project, and replace the two absolute paths.

## Verification

- **Offline contract tests.** `tests/test_mcp_integration_recipe.py` checks every example. Each must launch only `agentic mcp --root ... --provider none`. Each example's own command must also start the real stdio server and pass these checks:
  - it answers `initialize` for a newer client protocol version with a version it supports;
  - its listed tools are exactly the table above;
  - a read-only `search` returns results cited by source hash;
  - a call to `apply` is rejected;
  - the synthetic source is unchanged.

  This proves the configurations and the server, not any particular host.
- **Installed-host check.** `scripts/verify_mcp_integration.py --claude PATH --output DIR` (macOS) runs the installed Claude Code CLI against a disposable synthetic workspace:
  - It requires a new output directory and preserves existing evidence. It registers the server in a throwaway `HOME` and `CLAUDE_CONFIG_DIR`, with no credentials.
  - It runs `claude mcp list` and `claude mcp get` under a `sandbox-exec` profile that denies outbound network traffic, with a hard timeout that also stops MCP descendants. No model session is started.
  - A relay between the host and the server logs only message methods, ids and sizes, never payloads.
  - The receipt says exactly what the host did: initialized, listed tools, or invoked one. It also names the user files it fingerprinted (`~/.claude.json` and `~/.claude/settings.json`) to show they were not changed. That fingerprint is not a full filesystem audit.

Recorded on 2026-10-15 with Claude Code 2.1.300:

- The host first sent `server/discover`, which this server answers with "Method not found". The host then fell back to `initialize`, `notifications/initialized` and `tools/list`.
- It reported "✔ Connected" for both `claude mcp list` and `claude mcp get`, and left the two fingerprinted files and the source unchanged.
- It invoked no tool. That is all a health check does, so model-driven tool use inside a host session remains unverified here.

VS Code and Cursor are configured from their documented formats but were not exercised by these checks.

MCP stdout remains JSON-RPC during SIGINT shutdown. The CLI exits with status 130
without adding a normal CLI error envelope; regular non-MCP command behavior remains
the versioned CLI contract.
