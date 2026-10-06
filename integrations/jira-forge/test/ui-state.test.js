import assert from "node:assert/strict";
import test from "node:test";
import { TERMINAL_UI_STATES, permissionCleanupMessage, watchSubmission } from "../src/lib/ui-state.js";

test("cancelled observations terminate UI polling", () => {
  assert.equal(TERMINAL_UI_STATES.has("CANCELLED"), true);
  assert.equal(TERMINAL_UI_STATES.has("QUEUED"), false);
});

test("permission cleanup is explicitly manual for replacement and disconnect", () => {
  assert.match(permissionCleanupMessage(false), /Connection saved/);
  assert.match(permissionCleanupMessage(true), /Saved credentials are removed/);
  for (const disconnected of [false, true]) {
    assert.match(permissionCleanupMessage(disconnected), /manually remove unused destinations/);
    assert.match(permissionCleanupMessage(disconnected), /another administrator/);
  }
});

const flush = () => new Promise(resolve => setImmediate(resolve));
function watcher(invoke) {
  const timers = new Map(), jobs = [], errors = [];
  let id = 0;
  const stop = watchSubmission(invoke, job => jobs.push(job), error => errors.push(error),
    fn => { timers.set(++id, fn); return id; }, key => timers.delete(key));
  return { timers, jobs, errors, stop, async tick() {
    const [key, fn] = timers.entries().next().value;
    timers.delete(key); await fn();
  } };
}
test("watcher stops when cancelled, without overlapping requests", async () => {
  const watched = watcher(async method => method === "enqueueIssue" ?
    { requestId: "a", state: "QUEUED" } : { state: "CANCELLED" });
  await flush(); await watched.tick();
  assert.equal(watched.jobs.at(-1).state, "CANCELLED");
  assert.equal(watched.timers.size, 0);
});
test("closing before enqueue returns never creates a late polling timer", async () => {
  let resolve;
  const watched = watcher(() => new Promise(done => { resolve = done; }));
  await flush(); watched.stop(); resolve({ requestId: "a", state: "QUEUED" });
  await flush();
  assert.equal(watched.timers.size, 0);
  assert.equal(watched.jobs.length, 0);
});
test("polling failures and unknown jobs are safe terminal observation errors", async () => {
  for (const failure of [true, false]) {
    const watched = watcher(async method => {
      if (method === "enqueueIssue") return { requestId: "a", state: "QUEUED" };
      if (failure) throw new Error("secret-bearing error");
      return { state: "UNKNOWN" };
    });
    await flush(); await watched.tick();
    assert.equal(watched.timers.size, 0);
    assert.equal(watched.errors.length, 1);
    assert.equal(watched.errors[0].includes("secret-bearing"), false);
  }
});
