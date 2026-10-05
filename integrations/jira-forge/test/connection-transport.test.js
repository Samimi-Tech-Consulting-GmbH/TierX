import assert from "node:assert/strict";
import test from "node:test";
import { sendRequest } from "../src/lib/tierx.js";
const config = { secret: "test-secret-never-log", integrationId: "connection-a" };
const path = "/api/v1/integrations/jira/connection";
test("credentials go only to the selected origin with redirects disabled", async () => {
  let captured;
  const result = await sendRequest("https://customer.example", path, config, {}, async (url, init) => {
    captured = { url, init };
    return new Response(JSON.stringify({ jira_cloud_id: "a" }), { headers: { "content-type": "application/json" } });
  });
  assert.equal(result.jira_cloud_id, "a");
  assert.equal(captured.url, "https://customer.example" + path);
  assert.equal(captured.init.redirect, "manual");
  assert.equal(captured.init.headers.Authorization, "Bearer " + config.secret);
});
test("redirects and arbitrary upstream bodies are never followed or reflected", async () => {
  for (const status of [301, 302, 307, 308, 401, 403, 500]) {
    await assert.rejects(sendRequest("https://customer.example", path, config, {}, async () =>
      new Response(config.secret, { status })), error => {
        assert.equal(error.message.includes(config.secret), false);
        return true;
      });
  }
});
test("denied egress and malformed JSON produce safe errors", async () => {
  await assert.rejects(sendRequest("https://customer.example", path, config, {}, async () => {
    throw new Error(config.secret);
  }), error => !error.message.includes(config.secret));
  await assert.rejects(sendRequest("https://customer.example", path, config, {}, async () =>
    new Response(config.secret, { headers: { "content-type": "application/json" } })), /invalid JSON/);
});
