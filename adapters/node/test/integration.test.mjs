import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { appendFile, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, isAbsolute } from "node:path";
import test from "node:test";
import { AgenticError, Workbench } from "../dist/index.js";

test("installed CLI: six commands use the actual subprocess and preserve source during review", async () => {
  const executable = process.env.AGENTIC_EXECUTABLE;
  assert.ok(executable && isAbsolute(executable), "Set AGENTIC_EXECUTABLE to the absolute installed agentic executable; this integration check is not silently skipped.");
  const root = await mkdtemp(join(tmpdir(), "agentic-node-integration-"));
  const original = "def answer():\n    return 41\n";
  const replacement = "def answer():\n    return 42\n";
  try {
    await writeFile(join(root, "sample.py"), original);
    const wb = new Workbench(root, { executable });
    assert.equal(typeof await wb.init(), "object");
    const python = join(dirname(executable), process.platform === "win32" ? "python.exe" : "python");
    await appendFile(join(root, ".agentic", "config.toml"), '\n[commands.unit]\nargv = ' + JSON.stringify([python, "-m", "unittest", "-q"]) + '\n');
    assert.equal(typeof await wb.scan(), "object");
    assert.equal(typeof await wb.explain("sample.py"), "object");
    assert.equal(typeof await wb.plan("Explain the answer function and recommend a change"), "object");
    const execution = await wb.execute("Explain answer and identify its tests");
    assert.equal(execution.state, "succeeded");
    assert.equal(execution.verification.evidence.scope, "source-contracts");
    assert.ok((await wb.trace(execution.task_id)).phases.length > 0);
    assert.ok((await wb.tools()).tools.length >= 6);
    assert.ok((await wb.skills()).skills.length === 10);
    assert.ok((await wb.context("answer")).retrieval);
    const proposalFile = join(root, "reviewed-proposal.json");
    await writeFile(proposalFile, JSON.stringify({
      schema_version: 1,
      rationale: "Disposable Node integration review of a one-line change",
      edits: [{ path: "sample.py", base_hash: createHash("sha256").update(original).digest("hex"), content: replacement, delete: false }],
    }));
    const plan = await wb.plan("Import the reviewed disposable proposal", { proposalFile });
    assert.ok(Array.isArray(plan.proposal_ids) && typeof plan.proposal_ids[0] === "string", "The CLI plan must return the saved proposal ID.");
    assert.equal(typeof await wb.apply(plan.proposal_ids[0]), "object");
    assert.equal(typeof await wb.test("unit", { trustedHost: true }), "object");
    await assert.rejects(wb.apply(plan.proposal_ids[0], { approve: "0".repeat(64) }), (error) => {
      assert.ok(error instanceof AgenticError);
      assert.equal(error.exitCode, 3);
      return true;
    });
    assert.equal(await readFile(join(root, "sample.py"), "utf8"), original);
  } finally { await rm(root, { recursive: true, force: true }); }
});
