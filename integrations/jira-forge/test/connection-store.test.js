import assert from "node:assert/strict";
import test from "node:test";
import { createConnectionStore, CONNECTION_KEY, CONNECTION_MUTATION_KEY, cancelConnectionJob } from "../src/lib/connection-store.js";
import { validateDestination } from "../src/lib/destination.js";

function fixture(verify = async () => ({ jira_cloud_id: "cloud-a", name: "Test", route_count: 1 })) {
  const records = new Map();
  const storage = {
    getSecret: async key => records.get(key),
    setSecret: async (key, value, options) => {
      if (options?.keyPolicy === "FAIL_IF_EXISTS" && records.has(key)) {
        throw Object.assign(new Error("KEY_ALREADY_EXISTS"), { code: "KEY_ALREADY_EXISTS" });
      }
      records.set(key, structuredClone(value));
    },
    deleteSecret: async key => records.delete(key),
    delete: async key => records.delete(key),
  };
  return { records, storage, store: createConnectionStore(storage, verify) };
}
const candidate = { baseUrl: "https://customer.example", integrationId: "connection-a", secret: "test-only-secret" };

test("connection changes produce the same terminal cancellation for queued and pending work", async () => {
  const writes = [];
  await cancelConnectionJob({ set: async (...args) => writes.push(args) }, { requestId: "request-a", issueKey: "TEST-1" });
  assert.equal(writes[0][0], "job:request-a");
  assert.equal(writes[0][1].state, "CANCELLED");
  assert.match(writes[0][1].failure.error_detail, /changed or was disconnected/);
});

test("storage failures do not masquerade as abandoned mutation claims", async () => {
  const { store, storage } = fixture();
  storage.setSecret = async () => { throw Object.assign(new Error("private storage detail"), { code: "RATE_LIMIT_EXCEEDED" }); };
  await assert.rejects(store.save(candidate, "cloud-a"), {
    message: "TierX connection storage is unavailable. Retry later; contact the operator if it persists.",
  });
});
test("disconnect returns the current stored destination rather than a stale page key", async () => {
  const { store } = fixture();
  await store.save({ ...candidate, egressKey: "first-key" }, "cloud-a");
  await store.save({ ...candidate, baseUrl: "https://other.example", egressKey: "current-key" }, "cloud-a");
  assert.equal((await store.disconnect()).egressKey, "current-key");
});

test("connection reads never disclose secrets and installations remain isolated", async () => {
  const a = fixture(), b = fixture();
  const saved = await a.store.save(candidate, "cloud-a");
  assert.equal(saved.secret, undefined);
  assert.equal((await a.store.public()).secret, undefined);
  assert.equal((await b.store.public()).configured, false);
  assert.equal((await a.store.read(saved.identity)).secret, candidate.secret);
});
test("same-connection rotation preserves job identity; another server invalidates old jobs", async () => {
  const { store } = fixture();
  const first = await store.save(candidate, "cloud-a");
  const rotated = await store.save({ ...candidate, secret: "replacement" }, "cloud-a");
  assert.equal(first.identity, rotated.identity);
  assert.notEqual(first.revision, rotated.revision);
  assert.equal((await store.read(first.identity)).secret, "replacement");
  const other = await store.save({ ...candidate, baseUrl: "https://other.example" }, "cloud-a");
  assert.notEqual(first.identity, other.identity);
  await assert.rejects(store.read(first.identity), /changed/);
});
test("failed authentication and mismatched cloud IDs preserve saved connection", async () => {
  let failing = false;
  const { store } = fixture(async () => {
    if (failing) throw new Error("authentication failed");
    return { jira_cloud_id: "cloud-a" };
  });
  const before = await store.save(candidate, "cloud-a");
  await assert.rejects(store.save(candidate, "cloud-b"), /different Jira/);
  failing = true;
  await assert.rejects(store.save(candidate, "cloud-a"));
  assert.deepEqual(await store.public(), before);
});
test("disconnect removes credentials and reconnect never resumes previous jobs", async () => {
  const { store, records } = fixture();
  const before = await store.save(candidate, "cloud-a");
  await store.disconnect();
  assert.equal(records.get(CONNECTION_KEY).secret, undefined);
  await assert.rejects(store.read(before.identity));
  const after = await store.save(candidate, "cloud-a");
  assert.notEqual(before.identity, after.identity);
});
test("overlapping saves cannot mix destination and credential", async () => {
  const { store } = fixture();
  const other = { ...candidate, baseUrl: "https://other.example", secret: "other-secret" };
  await Promise.allSettled([store.save(candidate, "cloud-a"), store.save(other, "cloud-a")]);
  const saved = await store.read();
  assert.equal(saved.secret, saved.baseUrl === candidate.baseUrl ? candidate.secret : other.secret);
});
test("save verified before a disconnect cannot resurrect the connection", async () => {
  let release, delayed = false;
  const { store } = fixture(async () => {
    if (delayed) await new Promise(resolve => { release = resolve; });
    return { jira_cloud_id: "cloud-a" };
  });
  await store.save(candidate, "cloud-a");
  delayed = true;
  const saving = store.save(candidate, "cloud-a");
  await new Promise(resolve => setImmediate(resolve));
  await store.disconnect(); release();
  await assert.rejects(saving, /changed/);
});
test("DNS validation rejects every non-public answer, including mixed and mapped addresses", async () => {
  for (const address of ["127.0.0.1", "10.0.0.1", "169.254.169.254", "192.168.1.1", "100.64.0.1", "::1", "fc00::1", "fe80::1", "::ffff:127.0.0.1", "203.0.113.1"]) {
    await assert.rejects(validateDestination(candidate.baseUrl, async () => [{ address: "8.8.8.8" }, { address }]), /public/);
  }
  assert.equal(await validateDestination(candidate.baseUrl, async () => [{ address: "8.8.8.8" }]), candidate.baseUrl);
  await assert.rejects(validateDestination(candidate.baseUrl, async () => []), /public/);
});

test("disconnect cannot race between the revision check and final encrypted write", async () => {
  const { store, storage, records } = fixture();
  await store.save(candidate, "cloud-a");
  const write = storage.setSecret;
  let release, entered;
  const writing = new Promise(resolve => { entered = resolve; });
  storage.setSecret = async (key, ...args) => {
    if (key === CONNECTION_KEY) {
      entered();
      await new Promise(resolve => { release = resolve; });
    }
    return write(key, ...args);
  };
  const save = store.save(candidate, "cloud-a");
  await writing;
  await assert.rejects(store.disconnect(), /Another connection change/);
  release();
  await save;
  storage.setSecret = write;
  await store.disconnect();
  assert.equal((await store.public()).configured, false);
  assert.equal(records.has(CONNECTION_MUTATION_KEY), false);
});

test("abandoned mutation claims fail closed and are never automatically expired", async () => {
  const { store, records } = fixture();
  records.set(CONNECTION_MUTATION_KEY, { owner: "abandoned" });
  await assert.rejects(store.save(candidate, "cloud-a"), /Another connection change/);
  await assert.rejects(store.disconnect(), /Another connection change/);
  assert.equal(records.has(CONNECTION_KEY), false);
});

test("DNS diagnostics contain only allowlisted error codes", async () => {
  const messages = [];
  const original = console.warn;
  console.warn = (...args) => messages.push(args);
  try {
    for (const code of ["ENOTFOUND", "secret-bearing-code"]) {
      await assert.rejects(validateDestination(candidate.baseUrl, async () => {
        throw Object.assign(new Error("secret-bearing-message"), { code });
      }), { message: "TierX destination could not be resolved." });
    }
    await assert.rejects(validateDestination(candidate.baseUrl, async () => {
      throw new TypeError("lookup is not a function");
    }), { message: "TierX destination could not be resolved." });
    assert.deepEqual(messages, [
      ["TierX destination validation failed", { error_type: "ENOTFOUND", error_name: "Error" }],
      ["TierX destination validation failed", { error_type: "DNS_LOOKUP_FAILED", error_name: "Error" }],
      ["TierX destination validation failed", { error_type: "DNS_API_UNAVAILABLE", error_name: "TypeError" }],
    ]);
  } finally {
    console.warn = original;
  }
});
