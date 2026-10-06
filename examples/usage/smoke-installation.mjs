// Use only with a fresh, disposable local deployment; never resets an installation.
import assert from "node:assert/strict";
import { randomBytes } from "node:crypto";

const base = process.env.TIERX_SMOKE_URL || "http://127.0.0.1:18080";
if (!["localhost", "127.0.0.1", "::1"].includes(new URL(base).hostname)) throw new Error("Smoke test is restricted to localhost");
const token = process.env.TIERX_SMOKE_TOKEN;
if (!token) throw new Error("Set TIERX_SMOKE_TOKEN without putting it in Git");
async function request(path, init = {}) {
  const response = await fetch(`${base}/api/v1${path}`, init);
  return { status: response.status, body: await response.json() };
}
function post(body, headers = {}) {
  return { method: "POST", headers: { "Content-Type": "application/json", ...headers }, body: JSON.stringify(body) };
}
assert.equal((await request("/installation/status")).body.installed, false, "Use a fresh disposable deployment");
assert.equal((await request("/auth/login", post({ email: "admin@example.com", password: "unused" }))).status, 503);
const values = (await request("/installation/status")).body.defaults;
values.public_url = base;
const password = process.env.TIERX_SMOKE_PASSWORD || randomBytes(24).toString("base64url");
const payload = { email: "admin@example.com", password, values };
assert.equal((await request("/installation/complete", post(payload, { "X-TierX-Installation-Token": "incorrect" }))).status, 403);
assert.equal((await request("/installation/complete", post(payload, { "X-TierX-Installation-Token": token }))).status, 200);
assert.equal((await request("/installation/complete", post(payload, { "X-TierX-Installation-Token": token }))).status, 404);
const login = await request("/auth/login", post({ email: payload.email, password }));
assert.equal(login.status, 200);
const headers = { "Content-Type": "application/json", Authorization: `Bearer ${login.body.access_token}` };
const first = await request("/admin/settings/platform", { headers });
assert.equal(first.body.revision, 1);
values.correlation_enabled = true;
values.knowledge_base_processing_enabled = true;
const changed = await request("/admin/settings/platform", { method: "PUT", headers, body: JSON.stringify({ expected_revision: 1, values }) });
assert.equal(changed.status, 200);
assert.equal(changed.body.revision, 2);
const stale = await request("/admin/settings/platform", { method: "PUT", headers, body: JSON.stringify({ expected_revision: 1, values }) });
assert.equal(stale.status, 409);
const deadline = Date.now() + 45000;
let services = [];
while (Date.now() < deadline) {
  services = (await request("/admin/settings/platform", { headers })).body.services;
  if (["backend", "pipeline", "knowledge-base-processor", "ingestion-proxy"].every(name => services.some(service => service.service === name && service.applied_revision === 2))) break;
  await new Promise(resolve => setTimeout(resolve, 1000));
}
for (const name of ["backend", "pipeline", "knowledge-base-processor", "ingestion-proxy"]) {
  assert.ok(services.some(service => service.service === name && service.applied_revision === 2), `Missing applied revision for ${name}`);
}
assert.equal((await request("/installation/status")).body.wizard_available, false);
console.log("PASS: gated APIs, token rejection/consumption, login, revision conflict, and four-service propagation. No credentials printed.");
