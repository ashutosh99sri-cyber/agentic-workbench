import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

test("package excludes stale and backup build artifacts", async () => {
  const root = await mkdtemp(join(tmpdir(), "agentic-node-package-"));
  try {
    await writeFile(join(root, "package.json"), await readFile(new URL("../package.json", import.meta.url)));
    await mkdir(join(root, "dist"));
    for (const name of ["index.js", "index.d.ts", "index 2.js", "index 2.d.ts"]) {
      await writeFile(join(root, "dist", name), "");
    }
    const [packed] = JSON.parse(execFileSync(process.execPath, [
      process.env.npm_execpath, "pack", "--ignore-scripts", "--dry-run", "--json",
    ], { cwd: root, encoding: "utf8" }));
    assert.deepEqual(packed.files.map((file) => file.path).filter((path) => path.startsWith("dist/")), [
      "dist/index.d.ts", "dist/index.js",
    ]);
  } finally { await rm(root, { recursive: true, force: true }); }
});
