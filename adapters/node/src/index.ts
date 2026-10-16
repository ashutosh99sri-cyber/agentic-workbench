import { spawn } from "node:child_process";
import { isAbsolute, resolve } from "node:path";

export type JsonValue = null | boolean | number | string | JsonValue[] | JsonObject;
export type JsonObject = { [key: string]: JsonValue };

export interface ProcessEvidence {
  exitCode: number | null;
  signal: NodeJS.Signals | null;
  stdout: string;
  stderr: string;
  spawnErrorCode?: string;
}

export class AgenticError extends Error implements ProcessEvidence {
  readonly name = "AgenticError";
  readonly exitCode: number | null;
  readonly signal: NodeJS.Signals | null;
  readonly stdout: string;
  readonly stderr: string;
  readonly spawnErrorCode?: string;

  constructor(
    readonly code: string,
    message: string,
    readonly retryable = false,
    evidence: ProcessEvidence = { exitCode: null, signal: null, stdout: "", stderr: "" },
  ) {
    super(message);
    this.exitCode = evidence.exitCode;
    this.signal = evidence.signal;
    this.stdout = evidence.stdout;
    this.stderr = evidence.stderr;
    if (evidence.spawnErrorCode !== undefined) this.spawnErrorCode = evidence.spawnErrorCode;
  }
}

/** Trusted host configuration; never construct it from model/tool input. */
export interface HostOptions {
  executable?: string;
  /** Interpreter prefix for a trusted CLI, e.g. Python's -m entrypoint. */
  executableArgs?: readonly string[];
  timeoutMs?: number;
  /** Combined raw stdout and stderr byte limit. */
  maxOutputBytes?: number;
  /** Name resolved by CLI configuration; forwarding does not edit that configuration. */
  credentialEnv?: string;
  /** Trusted absolute TypeScript package directory; requires nodeExecutable. */
  typescriptPackage?: string;
  /** Trusted absolute Node executable; requires typescriptPackage. */
  nodeExecutable?: string;
}

export interface ProviderOptions {
  provider: "openai";
  model: string;
  allowNetwork: true;
}

export interface AnalysisOptions {
  /** Explicit host grant, separate from the instruction/context. */
  provider?: ProviderOptions;
}

export interface PlanOptions extends AnalysisOptions {
  proposalFile?: string;
}

export interface ApprovalOptions {
  dryRun?: boolean;
  /** Exact current digest obtained from a review, supplied by the trusted host. */
  approve?: string;
}

export interface TestOptions extends ApprovalOptions {
  backend?: "docker";
  trustedHost?: boolean;
}

export interface ExecutionOptions extends AnalysisOptions {
  proposalId?: string;
  commandId?: string;
  taskId?: string;
  /** Approval of the exact source change, separate from the task instruction. */
  approve?: string;
  /** Approval of the exact current command and snapshot. */
  approveTest?: string;
  backend?: "docker";
  trustedHost?: boolean;
}

export interface SearchOptions extends AnalysisOptions {
  semantic?: boolean;
  mode?: "lexical" | "semantic" | "combined";
  dimensions?: number;
  limit?: number;
}

export interface ContextOptions {
  changedPaths?: string[];
}

type Envelope =
  | { schema_version: 1; ok: true; data: JsonObject }
  | { schema_version: 1; ok: false; error: { code: string; message: string; retryable: boolean } };

const runtimeEnvNames = [
  "PATH", "HOME", "USERPROFILE", "SystemRoot", "WINDIR", "TMPDIR", "TMP", "TEMP", "LANG", "LC_ALL",
] as const;

function textArgument(value: string, label: string, positional = false): string {
  if (typeof value !== "string" || !value.trim() || value.includes("\0") || (positional && value.startsWith("-"))) {
    throw new AgenticError("INVALID_ARGUMENT", `${label} must be nonempty text without NUL or a leading option flag.`);
  }
  return value;
}

function positiveInteger(value: number, label: string): number {
  if (!Number.isSafeInteger(value) || value < 1) {
    throw new AgenticError("INVALID_ARGUMENT", `${label} must be a positive safe integer.`);
  }
  return value;
}

function changedPathArguments(paths: string[]): string[] {
  if (!Array.isArray(paths) || paths.length < 1 || paths.length > 20 || new Set(paths).size !== paths.length) {
    throw new AgenticError("INVALID_ARGUMENT", "changedPaths must contain 1 to 20 unique paths.");
  }
  return Array.from(paths, (path) => textArgument(path, "Changed path", true));
}

function object(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function exactKeys(value: Record<string, unknown>, keys: string[]): boolean {
  const actual = Object.keys(value);
  return actual.length === keys.length && keys.every((key) => Object.hasOwn(value, key));
}

function uniqueProperties(stdout: string): boolean {
  const stack: { keys?: Set<string>; expectKey: boolean }[] = [];
  for (const match of stdout.matchAll(/"(?:[^"\\]|\\[\s\S])*"|[{}\[\],]/g)) {
    const token = match[0];
    if (token === "{") stack.push({ keys: new Set(), expectKey: true });
    else if (token === "[") stack.push({ expectKey: false });
    else if (token === "}" || token === "]") stack.pop();
    else {
      const frame = stack.at(-1);
      if (token === "," && frame?.keys) frame.expectKey = true;
      else if (token.startsWith('"') && frame?.keys && frame.expectKey) {
        const key = JSON.parse(token) as string;
        if (frame.keys.has(key)) return false;
        frame.keys.add(key);
        frame.expectKey = false;
      }
    }
  }
  return true;
}

function redactJson(value: JsonValue, sanitize: (text: string) => string): JsonValue {
  if (typeof value === "string") return sanitize(value);
  if (Array.isArray(value)) return value.map((item) => redactJson(item, sanitize));
  if (object(value)) return Object.fromEntries(Object.entries(value).map(([key, item]) => [sanitize(key), redactJson(item, sanitize)]));
  return value;
}

function envelope(stdout: string): Envelope | undefined {
  let value: unknown;
  try { value = JSON.parse(stdout); } catch { return undefined; }
  if (!object(value) || value.schema_version !== 1 || !uniqueProperties(stdout)) return undefined;
  if (value.ok === true && exactKeys(value, ["schema_version", "ok", "data"]) && object(value.data)) {
    const pending: [unknown, number][] = [[value.data, 0]];
    while (pending.length) {
      const [item, depth] = pending.pop()!;
      if (depth > 256) return undefined;
      if (typeof item === "number" && !Number.isFinite(item)) return undefined;
      if (Array.isArray(item)) for (const child of item) pending.push([child, depth + 1]);
      else if (object(item)) for (const child of Object.values(item)) pending.push([child, depth + 1]);
    }
    return value as Envelope;
  }
  if (value.ok === false && exactKeys(value, ["schema_version", "ok", "error"]) && object(value.error)
    && exactKeys(value.error, ["code", "message", "retryable"])
    && typeof value.error.code === "string" && value.error.code.trim()
    && typeof value.error.message === "string" && value.error.message.trim()
    && typeof value.error.retryable === "boolean") return value as Envelope;
  return undefined;
}

function approvalArgs(options: ApprovalOptions): string[] {
  if (options.dryRun !== undefined && typeof options.dryRun !== "boolean") {
    throw new AgenticError("INVALID_ARGUMENT", "dryRun must be a boolean.");
  }
  if (options.approve !== undefined) {
    if (options.dryRun === true) throw new AgenticError("INVALID_ARGUMENT", "A dry-run cannot carry approval authority.");
    return ["--approve", textArgument(options.approve, "Approval digest", true)];
  }
  if (options.dryRun === false) throw new AgenticError("APPROVAL_REQUIRED", "Execution requires an explicit current approval digest.");
  return ["--dry-run"];
}

export class Workbench {
  readonly root: string;
  private readonly executable: string;
  private readonly executableArgs: readonly string[];
  private readonly timeoutMs: number;
  private readonly maxOutputBytes: number;
  private readonly credentialEnv: string;
  private readonly structureArgs: string[] = [];

  constructor(root: string, options: HostOptions = {}) {
    this.root = resolve(textArgument(root, "Workspace root"));
    this.executable = textArgument(options.executable ?? "agentic", "CLI executable");
    this.executableArgs = (options.executableArgs ?? []).map((arg) => textArgument(arg, "CLI prefix argument"));
    this.timeoutMs = positiveInteger(options.timeoutMs ?? 60_000, "timeoutMs");
    if (this.timeoutMs > 2_147_483_647) throw new AgenticError("INVALID_ARGUMENT", "timeoutMs exceeds the platform timer limit.");
    this.maxOutputBytes = positiveInteger(options.maxOutputBytes ?? 1_048_576, "maxOutputBytes");
    if ((options.typescriptPackage === undefined) !== (options.nodeExecutable === undefined)) {
      throw new AgenticError("INVALID_ARGUMENT", "Select both typescriptPackage and nodeExecutable.");
    }
    if (options.typescriptPackage !== undefined && options.nodeExecutable !== undefined) {
      for (const [flag, path] of [["--typescript-package", options.typescriptPackage], ["--node-executable", options.nodeExecutable]] as const) {
        if (!isAbsolute(textArgument(path, flag))) {
          throw new AgenticError("INVALID_ARGUMENT", `${flag} must be an absolute trusted host path.`);
        }
        this.structureArgs.push(flag, path);
      }
    }
    this.credentialEnv = options.credentialEnv ?? "OPENAI_API_KEY";
    if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(this.credentialEnv)
      || runtimeEnvNames.some((name) => name.toUpperCase() === this.credentialEnv.toUpperCase())
      || /^(?:PYTHON|NODE|LD_|DYLD_)/i.test(this.credentialEnv)) {
      throw new AgenticError("INVALID_ARGUMENT", "credentialEnv must name a credential variable, not a runtime control variable.");
    }
  }

  async init(): Promise<JsonObject> { return this.invoke(["init"]); }
  async scan(): Promise<JsonObject> { return this.invoke(["scan"]); }
  async explain(target: string, options: AnalysisOptions = {}): Promise<JsonObject> {
    return this.invoke(["explain", textArgument(target, "Target", true)], options);
  }
  async plan(instruction: string, options: PlanOptions = {}): Promise<JsonObject> {
    const args = ["plan", textArgument(instruction, "Instruction", true)];
    if (options.proposalFile !== undefined) args.push("--proposal-file", resolve(textArgument(options.proposalFile, "Proposal file")));
    return this.invoke(args, options);
  }
  async apply(proposalId: string, options: ApprovalOptions = {}): Promise<JsonObject> {
    return this.invoke(["apply", textArgument(proposalId, "Proposal ID", true), ...approvalArgs(options)]);
  }
  async rollback(changeId: string, options: ApprovalOptions = {}): Promise<JsonObject> {
    return this.invoke(["apply", "--rollback", textArgument(changeId, "Change ID", true), ...approvalArgs(options)]);
  }
  async test(commandId: string, options: TestOptions = {}): Promise<JsonObject> {
    const args = ["test", "--command-id", textArgument(commandId, "Command ID", true), ...approvalArgs(options)];
    if (options.trustedHost !== undefined && typeof options.trustedHost !== "boolean") {
      throw new AgenticError("INVALID_ARGUMENT", "trustedHost must be a boolean.");
    }
    if (options.backend !== undefined && options.backend !== "docker") {
      throw new AgenticError("INVALID_ARGUMENT", "The supported isolated backend is docker.");
    }
    if (options.backend !== undefined && options.trustedHost === true) {
      throw new AgenticError("INVALID_ARGUMENT", "Select docker or trustedHost, not both.");
    }
    if (options.approve !== undefined && options.backend === undefined && options.trustedHost !== true) {
      throw new AgenticError("BACKEND_REQUIRED", "Approved test execution requires docker or explicit trustedHost.");
    }
    if (options.backend !== undefined) args.push("--backend", options.backend);
    if (options.trustedHost === true) args.push("--trusted-host");
    return this.invoke(args);
  }
  async runAgent(agent: string, instruction: string, options: AnalysisOptions = {}): Promise<JsonObject> {
    return this.invoke(["run", textArgument(agent, "Agent", true), textArgument(instruction, "Instruction", true)], options);
  }
  async status(taskId: string): Promise<JsonObject> {
    return this.invoke(["status", textArgument(taskId, "Task ID", true)]);
  }
  async resume(taskId: string, options: AnalysisOptions = {}): Promise<JsonObject> {
    return this.invoke(["resume", textArgument(taskId, "Task ID", true)], options);
  }
  async execute(instruction: string, options: ExecutionOptions = {}): Promise<JsonObject> {
    const args = ["execute", textArgument(instruction, "Instruction", true)];
    for (const [key, flag] of [["proposalId", "--proposal-id"], ["commandId", "--command-id"], ["taskId", "--task-id"], ["approve", "--approve"], ["approveTest", "--approve-test"]] as const) {
      if (options[key] !== undefined) args.push(flag, textArgument(options[key], key, true));
    }
    if (options.trustedHost !== undefined && typeof options.trustedHost !== "boolean") {
      throw new AgenticError("INVALID_ARGUMENT", "trustedHost must be a boolean.");
    }
    if (options.backend !== undefined && options.backend !== "docker") {
      throw new AgenticError("INVALID_ARGUMENT", "The supported isolated backend is docker.");
    }
    if (options.backend !== undefined && options.trustedHost === true) {
      throw new AgenticError("INVALID_ARGUMENT", "Select docker or trustedHost, not both.");
    }
    if (options.approveTest !== undefined && options.backend === undefined && options.trustedHost !== true) {
      throw new AgenticError("BACKEND_REQUIRED", "Execution approval requires docker or explicit trustedHost.");
    }
    if (options.proposalId !== undefined && options.commandId === undefined) {
      throw new AgenticError("INVALID_ARGUMENT", "Applied workflows require a verification command.");
    }
    if (options.backend !== undefined) args.push("--backend", options.backend);
    if (options.trustedHost === true) args.push("--trusted-host");
    return this.invoke(args, options);
  }
  async cancel(taskId: string): Promise<JsonObject> {
    return this.invoke(["cancel", textArgument(taskId, "Task ID", true)]);
  }
  async trace(taskId: string): Promise<JsonObject> {
    return this.invoke(["trace", textArgument(taskId, "Task ID", true)]);
  }
  async tools(): Promise<JsonObject> { return this.invoke(["tools"]); }
  async skills(): Promise<JsonObject> { return this.invoke(["skills"]); }
  async context(query: string, options: ContextOptions = {}): Promise<JsonObject> {
    const args = ["context", textArgument(query, "Query", true)];
    if (options.changedPaths !== undefined) {
      for (const path of changedPathArguments(options.changedPaths)) args.push("--changed-path", path);
    }
    return this.invoke(args);
  }
  async impact(changedPaths: string[], limit = 20): Promise<JsonObject> {
    const paths = changedPathArguments(changedPaths);
    if (positiveInteger(limit, "limit") > 50) throw new AgenticError("INVALID_ARGUMENT", "limit must be at most 50.");
    return this.invoke(["impact", ...paths, "--limit", String(limit)]);
  }
  async search(query: string, options: SearchOptions = {}): Promise<JsonObject> {
    const args = ["search", textArgument(query, "Query", true)];
    if (options.semantic !== undefined && typeof options.semantic !== "boolean") {
      throw new AgenticError("INVALID_ARGUMENT", "semantic must be a boolean.");
    }
    if (options.mode !== undefined && !["lexical", "semantic", "combined"].includes(options.mode)) {
      throw new AgenticError("INVALID_ARGUMENT", "mode must be lexical, semantic or combined.");
    }
    if (options.semantic === true && options.mode !== undefined && options.mode !== "semantic") {
      throw new AgenticError("INVALID_ARGUMENT", "semantic: true conflicts with the selected mode.");
    }
    const mode = options.mode ?? (options.semantic === true ? "semantic" : "lexical");
    if (mode === "semantic") args.push("--semantic");
    if (mode === "combined") args.push("--combined");
    if (options.dimensions !== undefined) args.push("--dimensions", String(positiveInteger(options.dimensions, "dimensions")));
    if (options.limit !== undefined) args.push("--limit", String(positiveInteger(options.limit, "limit")));
    return this.invoke(args, options);
  }
  async state(action: "export" | "prune", options: ApprovalOptions = {}): Promise<JsonObject> {
    if (action === "prune") return this.invoke(["state", "prune", ...approvalArgs(options)]);
    if (action !== "export" || options.approve !== undefined || options.dryRun !== undefined) {
      throw new AgenticError("INVALID_ARGUMENT", "State export is read-only; only prune accepts approval options.");
    }
    return this.invoke(["state", "export"]);
  }

  private async invoke(commandArgs: string[], options: AnalysisOptions = {}): Promise<JsonObject> {
    const env: NodeJS.ProcessEnv = {};
    for (const name of runtimeEnvNames) if (process.env[name] !== undefined) env[name] = process.env[name];
    const args = [...this.executableArgs, ...commandArgs, ...this.structureArgs, "--root", this.root, "--json"];
    if (options.provider !== undefined) {
      const provider = options.provider;
      if (!object(provider) || provider.provider !== "openai" || provider.allowNetwork !== true) {
        throw new AgenticError("INVALID_ARGUMENT", "Provider invocation requires openai and explicit allowNetwork: true.");
      }
      args.push("--provider", "openai", "--model", textArgument(provider.model, "Model", true), "--allow-network");
      if (process.env[this.credentialEnv] !== undefined) env[this.credentialEnv] = process.env[this.credentialEnv];
    }
    // Redact known credentials even if a broken offline CLI accidentally prints one.
    const secrets = [...new Set([process.env.OPENAI_API_KEY, process.env[this.credentialEnv]].filter((value): value is string => !!value))]
      .sort((left, right) => right.length - left.length);
    const sanitize = (value: string, truncated = false): string => {
      for (const secret of secrets) {
        value = value.split(JSON.stringify(secret).slice(1, -1)).join("[REDACTED]");
        value = value.split(secret).join("[REDACTED]");
        if (truncated) {
          for (const spelling of [secret, JSON.stringify(secret).slice(1, -1)]) {
            for (let size = Math.min(value.length, spelling.length - 1); size > 0; size--) {
              if (value.endsWith(spelling.slice(0, size))) {
                value = value.slice(0, -size) + "[REDACTED]";
                break;
              }
            }
          }
        }
      }
      return value;
    };
    if ([this.executable, ...args].some((arg) => secrets.some((secret) => arg.includes(secret)))) {
      throw new AgenticError("INVALID_ARGUMENT", "Known credentials cannot be included in CLI arguments.");
    }
    return new Promise<JsonObject>((resolveResult, reject) => {
      const stdout: Buffer[] = [];
      const stderr: Buffer[] = [];
      let bytes = 0;
      let failure: "TIMEOUT" | "OUTPUT_LIMIT" | undefined;
      let spawnError: NodeJS.ErrnoException | undefined;
      const child = spawn(this.executable, args, {
        shell: false, env, stdio: ["ignore", "pipe", "pipe"], windowsHide: true,
        detached: process.platform !== "win32",
      });
      const stop = () => {
        if (process.platform !== "win32" && child.pid !== undefined) {
          try { process.kill(-child.pid, "SIGKILL"); } catch { child.kill("SIGKILL"); }
        } else child.kill("SIGKILL");
      };
      const timer = setTimeout(() => { failure ??= "TIMEOUT"; stop(); }, this.timeoutMs);
      const capture = (chunks: Buffer[], chunk: Buffer) => {
        if (failure !== undefined) return;
        const remaining = this.maxOutputBytes - bytes;
        chunks.push(chunk.subarray(0, Math.max(0, remaining)));
        bytes += chunk.length;
        if (bytes > this.maxOutputBytes) { failure = "OUTPUT_LIMIT"; stop(); }
      };
      child.stdout.on("data", (chunk: Buffer) => capture(stdout, chunk));
      child.stderr.on("data", (chunk: Buffer) => capture(stderr, chunk));
      child.on("error", (error: NodeJS.ErrnoException) => { spawnError = error; });
      child.on("close", (exitCode, signal) => {
        clearTimeout(timer);
        const evidence: ProcessEvidence = {
          exitCode, signal,
          stdout: sanitize(Buffer.concat(stdout).toString("utf8"), failure !== undefined),
          stderr: sanitize(Buffer.concat(stderr).toString("utf8"), failure !== undefined),
        };
        if (failure !== undefined) {
          reject(new AgenticError(failure, failure === "TIMEOUT" ? "CLI exceeded its process timeout." : "CLI exceeded its combined output byte limit.", false, evidence));
          return;
        }
        if (spawnError !== undefined) {
          if (spawnError.code !== undefined) evidence.spawnErrorCode = sanitize(spawnError.code);
          reject(new AgenticError("SPAWN_ERROR", sanitize(spawnError.message), false, evidence));
          return;
        }
        const response = envelope(Buffer.concat(stdout).toString("utf8"));
        if (response !== undefined) evidence.stdout = JSON.stringify(redactJson(response as unknown as JsonValue, sanitize));
        if (response === undefined || (response.ok && exitCode !== 0) || (!response.ok && (exitCode === 0 || exitCode === null)) || signal !== null) {
          reject(new AgenticError("INVALID_ENVELOPE", "CLI must emit exactly one v1 JSON envelope consistent with its exit code.", false, evidence));
        } else if (response.ok) resolveResult(redactJson(response.data, sanitize) as JsonObject);
        else reject(new AgenticError(sanitize(response.error.code), sanitize(response.error.message), response.error.retryable, evidence));
      });
    });
  }
}
