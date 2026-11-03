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
    for (const version of ["v01.2.3", "v1.02.3", "v1.2.03"]) assert.throws(() => run("--release", version));
    const output = run("--release", "v1.2.3");
    const first = await readFile(join(directory, ".env"), "utf8");
    assert.match(first, /^TIERX_RELEASE=1\.2\.3$/m);
    assert.equal((await stat(join(directory, ".env"))).mode & 0o777, 0o600);
    for (const key of ["TIERX_MONGO_ROOT_PASSWORD", "TIERX_JWT_SECRET_KEY", "TIERX_WEBHOOK_SECRET_ENCRYPTION_KEY"]) {
      const secret = first.match(new RegExp(`^${key}=(.+)$`, "m"))[1];
      assert.equal(Buffer.from(secret, "base64url").length, 32);
      assert.ok(!output.includes(secret));
    }
    const { spawnSync } = await import("node:child_process");
    const mismatch = spawnSync(process.execPath, [join(directory, "setup.mjs"), "--release", "v9.9.9"], {encoding: "utf8"});
    assert.equal(mismatch.status, 0);
    assert.match(mismatch.stderr, /Requested release differs.*existing value preserved/);
    assert.equal(await readFile(join(directory, ".env"), "utf8"), first);
    await writeFile(join(directory, ".env"), first.replace(/^TIERX_INSTALLATION_TOKEN=.*$/m, "TIERX_INSTALLATION_TOKEN=synthetic-operator-token"));
    run();
    assert.match(await readFile(join(directory, ".env"), "utf8"), /TIERX_INSTALLATION_TOKEN=synthetic-operator-token/);
    await writeFile(join(directory, ".env"), first.replace("TIERX_RELEASE=1.2.3", "TIERX_RELEASE=01.2.3"));
    assert.throws(() => run());
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});

test("proxy preserves only valid outer TLS scheme values", async () => {
  const config = await readFile(new URL("nginx.conf", import.meta.url), "utf8");
  assert.match(config, /map \$http_x_forwarded_proto \$tierx_forwarded_proto/);
  assert.match(config, /default \$scheme;/);
  assert.equal((config.match(/proxy_set_header X-Forwarded-Proto \$tierx_forwarded_proto;/g) || []).length, 2);
});

test("shared example environment excludes authentication and setup secrets", async () => {
  const compose = await readFile(new URL("compose.common.yaml", import.meta.url), "utf8");
  const shared = compose.split("x-app:")[0];
  for (const key of ["JWT_SECRET_KEY", "WEBHOOK_SECRET_ENCRYPTION_KEY", "INSTALLATION_TOKEN", "PLATFORM_ADMIN_PASSWORD", "PLATFORM_ADMIN_EMAIL"]) {
    assert.ok(!shared.includes(key));
  }
  assert.match(compose, /qdrant:\n\s+image:.*\n\s+restart: unless-stopped/);
});
