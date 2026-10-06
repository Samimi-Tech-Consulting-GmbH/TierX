import assert from "node:assert/strict";
import test from "node:test";

import { getPendingPage, refreshPendingSubmission, safePollFailure, forEachPending } from "../src/poller.js";
import { TierXRequestError } from "../src/lib/tierx.js";

test("polling diagnostics distinguish HTTP and DNS failures without reflecting secrets", () => {
  for (const status of [401, 502]) {
    assert.deepEqual(safePollFailure(new TierXRequestError("Bearer must-not-persist", status)), {
      error_type: "TIERX_REQUEST_FAILED", http_status: status, retryable: status === 502,
    });
  }
  assert.deepEqual(safePollFailure(new Error("TierX destination could not be resolved.")), {
    error_type: "DESTINATION_DNS_FAILURE",
  });
  assert.deepEqual(safePollFailure(new Error("TierX destination must resolve only to public addresses.")), {
    error_type: "DESTINATION_NOT_PUBLIC",
  });
  assert.deepEqual(safePollFailure(new Error("secret=must-not-persist")), { error_type: "POLLING_FAILURE" });
});

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
        limit(value) {
          calls.push(["limit", value]);
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
  assert.ok(storage.calls.some(call => call[0] === "limit" && call[1] === 10));
  assert.ok(storage.calls.some((call) => call.join(":") === "cursor:page-2"));
  assert.ok(
    storage.calls.some(
      (call) => call[0] === "set" && call[2] === "page-3",
    ),
  );
});

test("pending work uses at most five workers and processes every item", async () => {
  let active = 0, peak = 0;
  const seen = [];
  await forEachPending(Array.from({ length: 10 }, (_, i) => i), async i => {
    active++; peak = Math.max(peak, active);
    await new Promise(resolve => setTimeout(resolve, 1));
    seen.push(i); active--;
  });
  assert.equal(peak, 5);
  assert.deepEqual(seen.sort((a, b) => a - b), Array.from({ length: 10 }, (_, i) => i));
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
