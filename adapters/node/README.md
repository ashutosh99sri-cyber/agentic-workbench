# Agentic Workbench Node adapter

This Apache-2.0 package wraps the installed `agentic` CLI. It has no runtime npm dependencies and does not implement a second policy engine.
Check [the release status](https://github.com/ashutosh99sri-cyber/agentic-workbench/blob/main/docs/releases/0.1.0.md)
for registry availability. Once published, install the Python CLI and this adapter:

```sh
python -m pip install "agentic-workbench==0.1.0"
npm install --ignore-scripts @agentic-workbench/node@0.1.0
```

For a source checkout or local artifact, install the Python package first, then build locally:

```sh
npm ci --ignore-scripts
npm run build
npm test
```

The independent lockfile pins TypeScript 7.0.2 and `@types/node` 26.6.5, verified through the official npm registry. `packageManager` pins the observed npm 11.19.0. The supported runtime is Node 24 or newer; CI targets the declared minimum 24.0.0 and 26.7.0. No global tooling, install scripts, npm publication, or paid provider calls are required.

To use this package in another application, build it above, then create a local archive:

```sh
npm pack --ignore-scripts
```

From the consumer application's directory, install the resulting archive:

```sh
npm install --ignore-scripts /absolute/path/to/agentic-workbench-node-0.1.0.tgz
```

Use the filename printed by `npm pack` if its version differs. The consumer must also have the Python package installed; select its absolute `agentic` executable as shown below. On Windows the executable is typically `C:\path\to\venv\Scripts\agentic.exe`, and the Python runtime supports read-only operations. Guarded source mutation and command execution require POSIX.

```ts
import { Workbench, AgenticError } from "@agentic-workbench/node";

const workbench = new Workbench("/absolute/workspace", {
  executable: "/absolute/venv/bin/agentic", // defaults to agentic on PATH
  timeoutMs: 60_000,
  maxOutputBytes: 1_048_576,
});

await workbench.init();
const report = await workbench.scan();
const explanation = await workbench.explain("src/main.py");
const plan = await workbench.plan("Review rounding behavior");
await workbench.apply("proposal-id"); // dry-run
await workbench.test("unit"); // command/snapshot review

try {
  await workbench.apply("proposal-id", { approve: hostReviewedDigest });
} catch (error) {
  if (error instanceof AgenticError) {
    // code, retryable, exitCode, signal, stdout, stderr, spawnErrorCode
    throw error;
  }
  throw error;
}
```

Every async method returns `Promise<JsonObject>` because command payloads differ. `JsonValue` and `JsonObject` are exported. The API covers:

| Method | Explicit options |
| --- | --- |
| `init()`, `scan()` | None |
| `explain(target)` | `{ provider }` |
| `plan(instruction)` | `{ proposalFile, provider }` |
| `apply(proposalId)`, `rollback(changeId)` | `{ dryRun, approve }` |
| `test(commandId)` | `{ dryRun, approve, backend: "docker" }` or `{ dryRun, approve, trustedHost: true }` |
| `runAgent(agent, instruction)`, `resume(taskId)` | `{ provider }` |
| `search(query)` | `{ mode: "lexical" \| "semantic" \| "combined", semantic, dimensions, limit, provider }` |
| `context(query)` | `{ changedPaths }` |
| `impact(changedPaths, limit = 20)` | 1–20 unique paths and a limit of 1–50 |
| `status(taskId)` | None |
| `state("export")`, `state("prune")` | Prune alone accepts `{ dryRun, approve }` |

Apply, rollback, state pruning, and test default to `--dry-run`. `{ approve: digest }` explicitly requests execution; `{ dryRun: false }` without approval fails locally. Approval and dry-run cannot be combined. Test execution also requires Docker or a separate `trustedHost: true` opt-in. The CLI verifies the exact current digest and effective policy. Keep these options in trusted host code, outside model-visible request/tool schemas. Approval does not cause retrying, network access, dependency installation, or backend fallback.

Provider invocation is per call and requires all fields:

```ts
await workbench.explain("src/main.py", {
  provider: { provider: "openai", model: "host-selected-model", allowNetwork: true },
});
```

Only provider-enabled calls forward `OPENAI_API_KEY`, read from the host environment immediately before spawning. `new Workbench(root, { credentialEnv: "MY_API_TOKEN" })` selects an explicit host credential name; the workspace's `.agentic/config.toml` must already name the same variable. Runtime-control environment names are rejected. The child receives only PATH, home/system/temp/locale runtime variables and the explicitly selected provider credential. Arbitrary inherited environment variables, `PYTHONPATH`, and `NODE_OPTIONS` are excluded. Known credential values are rejected in arguments and redacted in returned data and captured evidence; unknown secrets remain the CLI's responsibility.

The executable and optional `executableArgs` interpreter prefix are trusted host configuration. Commands are fixed names with argument arrays and `shell: false`; metacharacters remain literal text. Leading option flags in positional text and NULs are rejected. Relative roots and proposal file paths are resolved by the host. No stdin/request JSON or adapter logs carry credentials or approvals.

Optional `HostOptions.typescriptPackage` and `HostOptions.nodeExecutable` select the trusted TypeScript package directory and Node executable for structural analysis. Supply both as absolute paths; the adapter forwards them on every CLI invocation. The CLI validates the pinned parser and reads only policy-approved source snapshots. The adapter does not discover compiler packages from the workspace or load workspace configs/plugins. Omitting both preserves the CLI's Python/lexical fallback.

`impact(["src/main.ts"], 20)` inspects static relationships for explicit source paths. `context("review callers", { changedPaths: ["src/main.ts"] })` forwards each path as `--changed-path` to guide source selection. Both reject empty, duplicate, or oversized path arrays before spawning; the CLI validates existing relative indexed paths against current policy and source. These selections do not grant source-write or execution authority.

Search defaults to lexical retrieval. `{ mode: "semantic" }` forwards `--semantic`, and `{ mode: "combined" }` forwards `--combined` for lexical/vector rank fusion. Legacy `{ semantic: true }` remains supported, including together with `mode: "semantic"`; it conflicts with explicit lexical or combined mode. Semantic and combined retrieval use the existing per-call provider options and explicit network grant, with credential forwarding and validation unchanged. Setting a mode alone does not grant network access or create embeddings.

The default 60-second timeout and combined 1 MiB raw stdout/stderr limit terminate the subprocess on excess. POSIX termination also targets its process group; Windows terminates the direct CLI process. Windows descendant cleanup has not been verified. Envelopes must be exactly one v1 JSON object with the correct success/error fields, object data, finite numbers, unique properties, depth at most 256, and exit-code agreement. Success returns data. A CLI error preserves its sanitized error code/message/retryable and process evidence. Adapter failures use `INVALID_ARGUMENT`, `APPROVAL_REQUIRED`, `BACKEND_REQUIRED`, `SPAWN_ERROR`, `TIMEOUT`, `OUTPUT_LIMIT`, or `INVALID_ENVELOPE`. Timeouts and unknown process outcomes are never automatically retried. Structured stdout evidence may be normalized during redaction.

`npm test` spawns a deterministic fixture CLI. Its protocol tests verify real process boundaries, all command argv, dry-run/approval behavior, environment filtering, redaction, invalid envelopes, injection text, timeout, output limits, signals, and spawn failures. They do not establish Python feature completion or live provider quality.

Run the separate actual integration check against an installed CLI from outside the repository:

```sh
AGENTIC_EXECUTABLE=/absolute/clean-venv/bin/agentic npm run test:integration
```

This check creates a disposable workspace, calls all six required commands, imports a real proposal, verifies apply/test dry-runs and wrong-approval denial, and checks source preservation. Missing `AGENTIC_EXECUTABLE` fails the check explicitly. It does not execute repository tests, approve a source change, call providers, or prove Docker isolation; the full repository acceptance flow covers those capabilities. Build before either test command. `npm audit` checks the independent authoritative lockfile.
# Harness interoperability

The same installed Python CLI now backs `execute(instruction, options)`, `cancel(taskId)`, `trace(taskId)`, `tools()`, `skills()`, `context(query, options)` and `impact(changedPaths, limit)`. `ContextOptions` and `SearchOptions` expose the source-selection and retrieval options described above. ExecutionOptions separates `approve` for source changes and `approveTest` for the exact command/snapshot; `taskId` resumes with the same options. A selected proposal requires `commandId`. Command execution keeps Docker or explicit `trustedHost`; model/network options stay host-owned. Custom planners, providers and tool handlers register in the trusted Python host. See the [harness guide](https://github.com/ashutosh99sri-cyber/agentic-workbench/blob/main/docs/harness.md).
