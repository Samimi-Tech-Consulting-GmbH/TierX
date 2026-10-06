import assert from "node:assert/strict";
import test from "node:test";
import { TERMINAL_UI_STATES, cleanupPreviousDestination } from "../src/lib/ui-state.js";

test("cancelled observations terminate UI polling", () => {
  assert.equal(TERMINAL_UI_STATES.has("CANCELLED"), true);
  assert.equal(TERMINAL_UI_STATES.has("QUEUED"), false);
});

test("replacement removes only the previous destination and skips unchanged groups", async () => {
  const removed = [];
  const egress = { deleteGroup: async value => removed.push(value.key) };
  assert.equal(await cleanupPreviousDestination(egress, "old", "new"), null);
  await cleanupPreviousDestination(egress, "new", "new");
  await cleanupPreviousDestination(egress, null, "new");
  assert.deepEqual(removed, ["old"]);
});

test("cleanup failure is a separate safe warning after successful replacement", async () => {
  const warning = await cleanupPreviousDestination({ deleteGroup: async () => { throw new Error("secret-bearing-error"); } }, "old", "new");
  assert.match(warning, /new connection is saved/);
  assert.equal(warning.includes("secret-bearing-error"), false);
});
