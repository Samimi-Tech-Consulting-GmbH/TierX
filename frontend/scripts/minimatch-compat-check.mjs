import { test } from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
const load = createRequire(import.meta.url);

test("compatibility patch is idempotent and preserves legacy/named/ESM APIs", async () => {
  const script = fileURLToPath(new URL("minimatch-compat.mjs", import.meta.url));
  execFileSync(process.execPath, [script]);
  execFileSync(process.execPath, [script]);
  const match = load("minimatch");
  assert.equal(typeof match, "function");
  assert.equal(match("src/test.ts", "**/*.ts"), true);
  assert.equal(match("src/test.js", "**/*.ts"), false);
  assert.equal(match.defaults({ nocase: true })("A.TS", "*.ts"), true);
  assert.equal(new match.Minimatch("*.ts").match("a.ts"), true);
  assert.equal(match.minimatch, match);
  const esm = await import("minimatch");
  assert.equal(esm.default("a.ts", "*.ts"), true);
  assert.equal(esm.minimatch("a.ts", "*.ts"), true);
  assert.equal(load("minimatch/package.json").version, "11.0.4");
});
