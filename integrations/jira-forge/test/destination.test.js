import assert from "node:assert/strict";
import test from "node:test";
import { resolvePublicDns, validateDestination } from "../src/lib/destination.js";

const answer = (url, addresses = []) => {
  const query = new URL(url);
  const type = Number(query.searchParams.get("type"));
  return new Response(JSON.stringify({ Status: 0, TC: false,
    Question: [{ name: query.searchParams.get("name") + ".", type }],
    Answer: addresses.map(data => ({ type, data })),
  }), { headers: { "content-type": "application/dns-json" } });
};
test("Forge DNS uses HTTPS A and AAAA only, no credentials, and no redirects", async () => {
  const calls = [];
  const resolve = hostname => resolvePublicDns(hostname, async (url, init) => {
    calls.push({ url, init });
    return answer(url, new URL(url).searchParams.get("type") === "1" ? ["8.8.8.8"] : []);
  });
  assert.equal(await validateDestination("https://customer.example", resolve), "https://customer.example");
  assert.equal(calls.length, 2);
  assert.deepEqual(calls.map(c => new URL(c.url).searchParams.get("type")), ["1", "28"]);
  for (const call of calls) {
    assert.equal(new URL(call.url).origin, "https://cloudflare-dns.com");
    assert.equal(call.init.redirect, "manual");
    assert.deepEqual(call.init.headers, { Accept: "application/dns-json" });
  }
});
test("private, mapped private, reserved, mixed and empty answers fail closed", async () => {
  for (const values of [[], ["127.0.0.1"], ["10.0.0.1"], ["169.254.169.254"],
    ["::1"], ["::ffff:10.0.0.1"], ["8.8.8.8", "192.168.1.1"], ["bad-ip"]]) {
    await assert.rejects(validateDestination("https://customer.example", async () => values.map(address => ({ address }))), /public addresses/);
  }
  await assert.rejects(validateDestination("https://127.0.0.1"), /public addresses/);
});
test("resolver failure, redirects, malformed answers and partial family failure fail closed", async () => {
  for (const fetch of [
    async () => { throw new Error("private-upstream-detail"); },
    async () => new Response("", { status: 302 }),
    async () => new Response("{}", { headers: { "content-type": "application/dns-json" } }),
    async url => new URL(url).searchParams.get("type") === "1" ? answer(url, ["8.8.8.8"]) : new Response("", { status: 503 }),
    async () => new Response("x".repeat(65537), { headers: { "content-type": "application/dns-json" } }),
  ]) {
    await assert.rejects(validateDestination("https://customer.example", host => resolvePublicDns(host, fetch)),
      { message: "TierX destination could not be resolved." });
  }
});
test("DNS deadline aborts requests and never bypasses validation", async () => {
  let signal;
  await assert.rejects(resolvePublicDns("customer.example", async (_, init) => {
    signal = init.signal;
    return new Promise(() => {});
  }, 10), /DNS timeout/);
  assert.equal(signal.aborted, true);
});
