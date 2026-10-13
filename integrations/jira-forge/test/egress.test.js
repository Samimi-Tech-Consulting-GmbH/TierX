import assert from "node:assert/strict";
import test from "node:test";
import { approveDestination } from "../src/lib/egress.js";
const destination = { baseUrl: "https://customer.example", egressKey: "tierx-test" };
const approved = { results: [{ key: destination.egressKey, configured: [
  { domain: destination.baseUrl, type: ["FETCH_BACKEND_SIDE"] },
] }] };
test("existing exact backend permission permits credential rotation without duplicate group creation", async () => {
  await approveDestination({ get: async () => approved, set: () => assert.fail("unexpected consent") }, destination);
});
test("denied or missing consent stops configuration", async () => {
  await assert.rejects(approveDestination({ get: async () => ({ results: [] }), set: async () => { throw new Error("declined"); } }, destination), /declined/);
  await assert.rejects(approveDestination({ get: async () => ({ results: [] }), set: async () => {} }, destination), /not granted/);
});
test("new destination requests backend-only permission and verifies the result", async () => {
  let saved = false;
  await approveDestination({
    get: async () => saved ? approved : { results: [] },
    set: async payload => {
      assert.deepEqual(payload.egresses[0].configured, approved.results[0].configured);
      saved = true;
    },
  }, destination);
});
