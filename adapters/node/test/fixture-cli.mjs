// Deterministic protocol fixture, not the Python implementation.
const argv = process.argv.slice(2);
const mode = argv[1];
const key = process.env.OPENAI_API_KEY ?? process.env.WORKBENCH_TEST_KEY ?? "no-key";
const write = (value) => process.stdout.write(JSON.stringify(value));
const ok = (data) => write({ schema_version: 1, ok: true, data });
switch (mode) {
  case "fixture:error":
    process.stderr.write(`fixture diagnostic ${key}`);
    write({ schema_version: 1, ok: false, error: { code: "POLICY_DENIED", message: `denied ${key}`, retryable: false } });
    process.exitCode = 3;
    break;
  case "fixture:malformed": process.stdout.write("not JSON"); break;
  case "fixture:multiple": ok({}); ok({}); break;
  case "fixture:array": write({ schema_version: 1, ok: true, data: [] }); break;
  case "fixture:null": write({ schema_version: 1, ok: true, data: null }); break;
  case "fixture:version": write({ schema_version: 2, ok: true, data: {} }); break;
  case "fixture:extra": write({ schema_version: 1, ok: true, data: {}, other: true }); break;
  case "fixture:bad-error":
    write({ schema_version: 1, ok: false, error: { code: "FAIL", message: "bad", retryable: "false" } });
    process.exitCode = 1;
    break;
  case "fixture:zero-error":
    write({ schema_version: 1, ok: false, error: { code: "FAIL", message: "bad", retryable: false } });
    break;
  case "fixture:nonzero-ok": ok({}); process.exitCode = 1; break;
  case "fixture:infinite": process.stdout.write('{"schema_version":1,"ok":true,"data":{"n":1e999}}'); break;
  case "fixture:duplicate": process.stdout.write('{"schema_version":1,"ok":false,"ok":true,"data":{}}'); break;
  case "fixture:nested-duplicate": process.stdout.write('{"schema_version":1,"ok":true,"data":{"x":1,"\\u0078":2}}'); break;
  case "fixture:deep": process.stdout.write('{"schema_version":1,"ok":true,"data":{"deep":' + '['.repeat(300) + '0' + ']'.repeat(300) + '}}'); break;
  case "fixture:large-array": ok({ values: Array(200_000).fill(0) }); break;
  case "fixture:timeout": setInterval(() => {}, 1000); break;
  case "fixture:output": process.stdout.write("x".repeat(10_000)); break;
  case "fixture:stderr-output": process.stderr.write("x".repeat(10_000)); break;
  case "fixture:combined-output": process.stdout.write("x".repeat(60)); process.stderr.write("y".repeat(60)); break;
  case "fixture:credential-output": process.stdout.write(key.repeat(100)); break;
  case "fixture:signal": process.kill(process.pid, "SIGTERM"); break;
  case "fixture:redact":
    process.stderr.write(`diagnostic ${key}`);
    ok({ key, nested: [{ [key]: key }] });
    break;
  case "fixture:redact-unicode":
    process.stdout.write('{"schema_version":1,"ok":true,"data":{"key":' + JSON.stringify(key).replaceAll("e", "\\u0065") + '}}');
    break;
  default:
    ok({ argv, env: Object.fromEntries(Object.entries(process.env).filter(([name]) => !name.startsWith("NODE_"))) });
}
