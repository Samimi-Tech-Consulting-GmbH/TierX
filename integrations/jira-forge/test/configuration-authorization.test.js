import test from "node:test";
import assert from "node:assert/strict";
import { requireJiraAdministrator } from "../src/index.js";
test("configuration authorization rejects absent identities, non-admins, and failed checks", async () => {
  await assert.rejects(requireJiraAdministrator(null), /unavailable/);
  for (const [ok, havePermission] of [[false, true], [true, false]]) {
    const client = { asUser: () => ({ requestJira: async () => ({
      ok, json: async () => ({ permissions: { ADMINISTER: { havePermission } } }),
    }) }) };
    await assert.rejects(requireJiraAdministrator("operator", client));
  }
});
test("configuration authorization checks the actual invoking administrator", async () => {
  let actual;
  const client = { asUser: id => {
    actual = id;
    return { requestJira: async () => ({ ok: true, json: async () => ({
      permissions: { ADMINISTER: { havePermission: true } },
    }) }) };
  } };
  await requireJiraAdministrator("admin-a", client);
  assert.equal(actual, "admin-a");
});
