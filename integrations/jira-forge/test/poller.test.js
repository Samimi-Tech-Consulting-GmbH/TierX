import assert from "node:assert/strict";
import test from "node:test";

import { getPendingPage, refreshPendingSubmission } from "../src/poller.js";

function storageWithPages({ cursor = null, pages = [] } = {}) {
  const calls = [];
  const storage = {
    calls,
    async get(key) {
      calls.push(["get", key]);
      return cursor;
    },
    async set(key, value) {
      calls.push(["set", key, value]);
    },
    async delete(key) {
      calls.push(["delete", key]);
    },
    query() {
      const state = { cursor: null };
      return {
        where() {
          return this;
        },
        limit() {
          return this;
        },
        cursor(value) {
          state.cursor = value;
          calls.push(["cursor", value]);
          return this;
        },
        async getMany() {
          calls.push(["page", state.cursor]);
          const result = pages.shift();
          if (result instanceof Error) throw result;
          return result;
        },
      };
    },
  };
  return storage;
}

test("pending polling advances and persists the next cursor", async () => {
  const storage = storageWithPages({
    cursor: "page-2",
    pages: [{ results: [{ key: "pending:101" }], nextCursor: "page-3" }],
  });
  const page = await getPendingPage(storage);
  assert.equal(page.results[0].key, "pending:101");
  assert.ok(storage.calls.some((call) => call.join(":") === "cursor:page-2"));
  assert.ok(
    storage.calls.some(
      (call) => call[0] === "set" && call[2] === "page-3",
    ),
  );
});

test("a stale cursor restarts at the first page", async () => {
  const storage = storageWithPages({
    cursor: "stale",
    pages: [new Error("invalid cursor"), { results: [{ key: "pending:1" }] }],
  });
  const page = await getPendingPage(storage);
  assert.equal(page.results[0].key, "pending:1");
  assert.deepEqual(
    storage.calls.filter((call) => call[0] === "page"),
    [["page", "stale"], ["page", null]],
  );
});

test("an ambiguous finalizing delivery is retried by the poller", async () => {
  const calls = [];
  const request = async (path, options) => {
    calls.push([path, options]);
    if (!options) return { state: "FINALIZING" };
    return { state: "PROCESSING", alert_id: "alert-1" };
  };
  const result = await refreshPendingSubmission(
    { submissionId: "submission-1" },
    request,
  );
  assert.equal(result.state, "PROCESSING");
  assert.deepEqual(calls, [
    ["/api/v1/integrations/jira/submissions/submission-1", undefined],
    [
      "/api/v1/integrations/jira/submissions/submission-1/finalize",
      { method: "POST", body: {} },
    ],
  ]);
});
