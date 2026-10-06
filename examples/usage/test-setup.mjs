import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, copyFile, readFile, stat, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { execFileSync } from "node:child_process";

test("setup generates restricted secrets, preserves values, and requires a pinned release", async () => {
  const directory = await mkdtemp(join(tmpdir(), "tierx-setup-test-"));
  try {
    for (const file of ["setup.mjs", ".env.example"]) await copyFile(new URL(file, import.meta.url), join(directory, file));
    const run = (...args) => execFileSync(process.execPath, [join(directory, "setup.mjs"), ...args], { stdio: "pipe" }).toString();
    assert.throws(() => run());
    assert.throws(() => run("--release", "latest"));
    const output = run("--release", "v1.2.3");
    const first = await readFile(join(directory, ".env"), "utf8");
    assert.match(first, /^TIERX_RELEASE=1\.2\.3$/m);
    assert.equal((await stat(join(directory, ".env"))).mode & 0o777, 0o600);
    for (const key of ["TIERX_MONGO_ROOT_PASSWORD", "TIERX_JWT_SECRET_KEY", "TIERX_WEBHOOK_SECRET_ENCRYPTION_KEY"]) {
      const secret = first.match(new RegExp(`^${key}=(.+)$`, "m"))[1];
      assert.equal(Buffer.from(secret, "base64url").length, 32);
      assert.ok(!output.includes(secret));
    }
    run("--release", "v9.9.9");
    assert.equal(await readFile(join(directory, ".env"), "utf8"), first);
    await writeFile(join(directory, ".env"), first.replace(/^TIERX_INSTALLATION_TOKEN=.*$/m, "TIERX_INSTALLATION_TOKEN=synthetic-operator-token"));
    run();
    assert.match(await readFile(join(directory, ".env"), "utf8"), /TIERX_INSTALLATION_TOKEN=synthetic-operator-token/);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});
