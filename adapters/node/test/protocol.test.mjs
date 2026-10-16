import assert from "node:assert/strict";
import { mkdtemp, rm, access } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { AgenticError, Workbench } from "../dist/index.js";

const fixture = fileURLToPath(new URL("fixture-cli.mjs", import.meta.url));
const make = (options = {}, root = process.cwd()) => new Workbench(root, {
  executable: process.execPath, executableArgs: [fixture], ...options,
});
const argv = async (result) => (await result).argv;
const expectCode = (code) => (error) => {
  assert.ok(error instanceof AgenticError);
  assert.equal(error.code, code);
  return true;
};
const withEnv = async (values, body) => {
  const before = Object.fromEntries(Object.keys(values).map((key) => [key, process.env[key]]));
  try {
    for (const [key, value] of Object.entries(values)) process.env[key] = value;
    await body();
  } finally {
    for (const [key, value] of Object.entries(before)) {
      if (value === undefined) delete process.env[key]; else process.env[key] = value;
    }
  }
};

test("protocol fixture: six commands and supporting operations use fixed argv and safe defaults", async () => {
  const typescriptPackage = join(process.cwd(), "trusted-typescript");
  const wb = make({ typescriptPackage, nodeExecutable: process.execPath });
  const suffix = ["--typescript-package", typescriptPackage, "--node-executable", process.execPath, "--root", process.cwd(), "--json"];
  assert.deepEqual(await argv(wb.init()), ["init", ...suffix]);
  assert.deepEqual(await argv(wb.scan()), ["scan", ...suffix]);
  assert.deepEqual(await argv(wb.explain("src/main.py")), ["explain", "src/main.py", ...suffix]);
  assert.deepEqual(await argv(wb.plan("fix rounding")), ["plan", "fix rounding", ...suffix]);
  assert.deepEqual(await argv(wb.apply("proposal-1")), ["apply", "proposal-1", "--dry-run", ...suffix]);
  assert.deepEqual(await argv(wb.test("unit")), ["test", "--command-id", "unit", "--dry-run", ...suffix]);
  assert.deepEqual(await argv(wb.rollback("change-1")), ["apply", "--rollback", "change-1", "--dry-run", ...suffix]);
  assert.deepEqual(await argv(wb.runAgent("architecture", "inspect dependencies")), ["run", "architecture", "inspect dependencies", ...suffix]);
  assert.deepEqual(await argv(wb.status("task-1")), ["status", "task-1", ...suffix]);
  assert.deepEqual(await argv(wb.resume("task-1")), ["resume", "task-1", ...suffix]);
  assert.deepEqual(await argv(wb.search("rounding")), ["search", "rounding", ...suffix]);
  assert.deepEqual(await argv(wb.execute("inspect rounding")), ["execute", "inspect rounding", ...suffix]);
  assert.deepEqual(await argv(wb.cancel("task-1")), ["cancel", "task-1", ...suffix]);
  assert.deepEqual(await argv(wb.trace("task-1")), ["trace", "task-1", ...suffix]);
  assert.deepEqual(await argv(wb.tools()), ["tools", ...suffix]);
  assert.deepEqual(await argv(wb.skills()), ["skills", ...suffix]);
  assert.deepEqual(await argv(wb.context("rounding")), ["context", "rounding", ...suffix]);
  assert.deepEqual(await argv(wb.impact(["src/main.ts"])), ["impact", "src/main.ts", "--limit", "20", ...suffix]);
  assert.deepEqual(await argv(wb.state("export")), ["state", "export", ...suffix]);
  assert.deepEqual(await argv(wb.state("prune")), ["state", "prune", "--dry-run", ...suffix]);
  assert.deepEqual(await argv(wb.plan("import reviewed edits", { proposalFile: "review.json" })), ["plan", "import reviewed edits", "--proposal-file", join(process.cwd(), "review.json"), ...suffix]);
});

test("protocol fixture: impact and context preserve explicit changed paths and bounds", async () => {
  const wb = make();
  const suffix = ["--root", process.cwd(), "--json"];
  const paths = ["src/main.ts", "test/main.test.ts"];
  assert.deepEqual(await argv(wb.impact(paths, 50)), ["impact", ...paths, "--limit", "50", ...suffix]);
  assert.deepEqual(await argv(wb.context("rounding", { changedPaths: paths })), ["context", "rounding", "--changed-path", paths[0], "--changed-path", paths[1], ...suffix]);
  assert.deepEqual(paths, ["src/main.ts", "test/main.test.ts"]);
  const maximumPaths = Array.from({ length: 20 }, (_, index) => `src/file${index}.ts`);
  assert.deepEqual(await argv(wb.impact(maximumPaths, 1)), ["impact", ...maximumPaths, "--limit", "1", ...suffix]);
});

test("protocol fixture: explicit retrieval modes preserve legacy semantic options and provider grants", async () => {
  const wb = make();
  const suffix = ["--root", process.cwd(), "--json"];
  assert.deepEqual(await argv(wb.search("rounding", { mode: "lexical" })), ["search", "rounding", ...suffix]);
  assert.deepEqual(await argv(wb.search("rounding", { semantic: true })), ["search", "rounding", "--semantic", ...suffix]);
  assert.deepEqual(await argv(wb.search("rounding", { mode: "semantic" })), ["search", "rounding", "--semantic", ...suffix]);
  assert.deepEqual(await argv(wb.search("rounding", { mode: "semantic", semantic: true, dimensions: 256, limit: 3 })), ["search", "rounding", "--semantic", "--dimensions", "256", "--limit", "3", ...suffix]);
  assert.deepEqual(await argv(wb.search("rounding", { mode: "combined", semantic: false })), ["search", "rounding", "--combined", ...suffix]);
  await withEnv({ WORKBENCH_TEST_KEY: "combined-provider-credential" }, async () => {
    const result = await make({ credentialEnv: "WORKBENCH_TEST_KEY" }).search("rounding", {
      mode: "combined", provider: { provider: "openai", model: "embedding-model", allowNetwork: true },
    });
    assert.deepEqual(result.argv, ["search", "rounding", "--combined", ...suffix, "--provider", "openai", "--model", "embedding-model", "--allow-network"]);
    assert.equal(result.env.WORKBENCH_TEST_KEY, "[REDACTED]");
  });
});

test("adapter rejects invalid path selections and retrieval modes before spawning", async () => {
  const wb = make({ executable: join(process.cwd(), "absent-cli") });
  for (const paths of [null, "src/main.ts", [], ["a.ts", "a.ts"], Array(1), [""], ["--root"], ["bad\0path"], [1], Array.from({ length: 21 }, (_, index) => `${index}.ts`)]) {
    await assert.rejects(wb.impact(paths), expectCode("INVALID_ARGUMENT"));
    await assert.rejects(wb.context("rounding", { changedPaths: paths }), expectCode("INVALID_ARGUMENT"));
  }
  for (const limit of [0, 51, 1.5, true, "5", null]) {
    await assert.rejects(wb.impact(["src/main.ts"], limit), expectCode("INVALID_ARGUMENT"));
  }
  for (const options of [{ mode: "other" }, { mode: null }, { semantic: "true" }, { mode: "lexical", semantic: true }, { mode: "combined", semantic: true }]) {
    await assert.rejects(wb.search("rounding", options), expectCode("INVALID_ARGUMENT"));
  }
  await assert.rejects(wb.search("rounding", { mode: "combined", provider: { provider: "openai", model: "embedding-model", allowNetwork: false } }), expectCode("INVALID_ARGUMENT"));
});

test("protocol fixture: approval and backend authority are supplied only by explicit options", async () => {
  const wb = make();
  const suffix = ["--root", process.cwd(), "--json"];
  assert.deepEqual(await argv(wb.apply("p", { approve: "digest" })), ["apply", "p", "--approve", "digest", ...suffix]);
  assert.deepEqual(await argv(wb.rollback("c", { approve: "digest" })), ["apply", "--rollback", "c", "--approve", "digest", ...suffix]);
  assert.deepEqual(await argv(wb.state("prune", { approve: "digest" })), ["state", "prune", "--approve", "digest", ...suffix]);
  assert.deepEqual(await argv(wb.test("unit", { approve: "digest", backend: "docker" })), ["test", "--command-id", "unit", "--approve", "digest", "--backend", "docker", ...suffix]);
  assert.deepEqual(await argv(wb.test("unit", { approve: "digest", trustedHost: true })), ["test", "--command-id", "unit", "--approve", "digest", "--trusted-host", ...suffix]);
  await assert.rejects(wb.apply("p", { dryRun: false }), expectCode("APPROVAL_REQUIRED"));
  await assert.rejects(wb.test("unit", { approve: "digest" }), expectCode("BACKEND_REQUIRED"));
  await assert.rejects(wb.test("unit", { backend: "docker", trustedHost: true }), expectCode("INVALID_ARGUMENT"));
  await assert.rejects(wb.apply("p", { dryRun: true, approve: "digest" }), expectCode("INVALID_ARGUMENT"));
  await assert.rejects(wb.state("export", { approve: "digest" }), expectCode("INVALID_ARGUMENT"));
});

test("protocol fixture: metacharacters remain one argument; option injection is rejected", async () => {
  const root = await mkdtemp(join(tmpdir(), "agentic-node-injection-"));
  try {
    const marker = join(root, "injected");
    const instruction = `fix; touch ${marker} $(touch ${marker}) & | > < \" ' \`test\``;
    const result = await make({}, root).plan(instruction);
    assert.equal(result.argv[1], instruction);
    await assert.rejects(access(marker), { code: "ENOENT" });
    await assert.rejects(make().plan("--trusted-host"), expectCode("INVALID_ARGUMENT"));
    await assert.rejects(make().explain("bad\0path"), expectCode("INVALID_ARGUMENT"));
  } finally { await rm(root, { recursive: true, force: true }); }
});

test("protocol fixture: minimal environment and explicit provider-only credential forwarding", async () => {
  await withEnv({ OPENAI_API_KEY: "node-test-credential", UNRELATED_SECRET: "not-forwarded", PYTHONPATH: "/untrusted" }, async () => {
    const offline = await make().scan();
    assert.equal(offline.env.OPENAI_API_KEY, undefined);
    assert.equal(offline.env.UNRELATED_SECRET, undefined);
    assert.equal(offline.env.PYTHONPATH, undefined);
    assert.equal(offline.env.PATH, process.env.PATH);
    const provider = { provider: "openai", model: "test-model", allowNetwork: true };
    const online = await make().explain("src/main.py", { provider });
    assert.equal(online.env.OPENAI_API_KEY, "[REDACTED]");
    assert.deepEqual(online.argv.slice(-5), ["--provider", "openai", "--model", "test-model", "--allow-network"]);
    assert.ok(!online.argv.includes(process.env.OPENAI_API_KEY));
    await assert.rejects(make().explain("src/main.py", { provider: { ...provider, allowNetwork: false } }), expectCode("INVALID_ARGUMENT"));
    await assert.rejects(make().plan(process.env.OPENAI_API_KEY), expectCode("INVALID_ARGUMENT"));
  });
  await withEnv({ OPENAI_API_KEY: "default-key-should-stay-local", WORKBENCH_TEST_KEY: "explicit-key" }, async () => {
    const wb = make({ credentialEnv: "WORKBENCH_TEST_KEY" });
    const offline = await wb.scan();
    assert.equal(offline.env.WORKBENCH_TEST_KEY, undefined);
    const online = await wb.plan("inspect", { provider: { provider: "openai", model: "test-model", allowNetwork: true } });
    assert.equal(online.env.OPENAI_API_KEY, undefined);
    assert.equal(online.env.WORKBENCH_TEST_KEY, "[REDACTED]");
  });
});

test("protocol fixture: successful data and failure evidence redact known credentials", async () => {
  await withEnv({ OPENAI_API_KEY: "credential-\"quoted\\value\n" }, async () => {
    const provider = { provider: "openai", model: "test-model", allowNetwork: true };
    const data = await make().explain("fixture:redact", { provider });
    assert.deepEqual(data, { key: "[REDACTED]", nested: [{ "[REDACTED]": "[REDACTED]" }] });
    assert.deepEqual(await make().explain("fixture:redact-unicode", { provider }), { key: "[REDACTED]" });
    await assert.rejects(make().explain("fixture:error", { provider }), (error) => {
      expectCode("POLICY_DENIED")(error);
      assert.equal(error.exitCode, 3);
      assert.equal(error.retryable, false);
      assert.equal(error.message, "denied [REDACTED]");
      assert.equal(error.stderr, "fixture diagnostic [REDACTED]");
      assert.ok(!error.stdout.includes("quoted"));
      assert.ok(!String(error).includes("quoted"));
      return true;
    });
  });
});

test("protocol fixture: malformed, incompatible, contradictory and multiple envelopes fail closed", async () => {
  for (const mode of ["malformed", "multiple", "array", "null", "version", "extra", "bad-error", "zero-error", "nonzero-ok", "infinite", "duplicate", "nested-duplicate", "deep"]) {
    await assert.rejects(make().explain(`fixture:${mode}`), expectCode("INVALID_ENVELOPE"));
  }
  assert.equal((await make().explain("fixture:large-array")).values.length, 200_000);
});

test("protocol fixture: timeout, combined output limit, signals and spawn failure preserve evidence", async () => {
  await assert.rejects(make({ timeoutMs: 150 }).explain("fixture:timeout"), (error) => {
    expectCode("TIMEOUT")(error);
    assert.equal(error.signal, "SIGKILL");
    assert.equal(error.exitCode, null);
    return true;
  });
  for (const mode of ["output", "stderr-output", "combined-output"]) {
    await assert.rejects(make({ maxOutputBytes: 100 }).explain(`fixture:${mode}`), (error) => {
      expectCode("OUTPUT_LIMIT")(error);
      assert.ok(Buffer.byteLength(error.stdout) + Buffer.byteLength(error.stderr) <= 100);
      return true;
    });
  }
  await assert.rejects(make().explain("fixture:signal"), (error) => {
    expectCode("INVALID_ENVELOPE")(error);
    assert.equal(error.signal, "SIGTERM");
    return true;
  });
  await assert.rejects(new Workbench(process.cwd(), { executable: join(process.cwd(), "absent-cli") }).scan(), (error) => {
    expectCode("SPAWN_ERROR")(error);
    assert.equal(error.spawnErrorCode, "ENOENT");
    assert.equal(typeof error.exitCode, "number");
    assert.notEqual(error.exitCode, 0);
    return true;
  });
});

test("protocol fixture: output truncation redacts even a partial credential suffix", async () => {
  await withEnv({ OPENAI_API_KEY: "credential-prefix-that-must-not-leak" }, async () => {
    await assert.rejects(make({ maxOutputBytes: 8 }).explain("fixture:credential-output", {
      provider: { provider: "openai", model: "test-model", allowNetwork: true },
    }), (error) => {
      expectCode("OUTPUT_LIMIT")(error);
      assert.equal(error.stdout, "[REDACTED]");
      return true;
    });
  });
});

test("adapter validates local runtime options", () => {
  for (const options of [{ timeoutMs: 0 }, { timeoutMs: 2 ** 32 }, { maxOutputBytes: -1 }, { credentialEnv: "PYTHONPATH" }, { credentialEnv: "PATH" }, { credentialEnv: "bad=name" }]) {
    assert.throws(() => make(options), expectCode("INVALID_ARGUMENT"));
  }
  for (const options of [
    { typescriptPackage: "/trusted/typescript" },
    { nodeExecutable: process.execPath },
    { typescriptPackage: "relative/typescript", nodeExecutable: process.execPath },
    { typescriptPackage: process.cwd(), nodeExecutable: "node" },
    { typescriptPackage: "", nodeExecutable: process.execPath },
    { typescriptPackage: "bad\0path", nodeExecutable: process.execPath },
    { typescriptPackage: null, nodeExecutable: process.execPath },
  ]) assert.throws(() => make(options), expectCode("INVALID_ARGUMENT"));
});
