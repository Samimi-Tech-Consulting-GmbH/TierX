import api from "@forge/api";
import ipaddr from "ipaddr.js";
import { normalizeBaseUrl } from "./constants.js";

// Native getaddrinfo is not usable in the observed Forge runtime. Resolve via
// the supported HTTPS proxy, without sending installation or alert data.
export async function resolvePublicDns(hostname, fetch = api.fetch, timeoutMs = 5000) {
  const controller = new AbortController();
  let timer;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => { controller.abort(); reject(new Error("DNS timeout")); }, timeoutMs);
  });
  try {
    return await Promise.race([Promise.all([1, 28].map(async type => {
      const url = new URL("https://cloudflare-dns.com/dns-query");
      url.searchParams.set("name", hostname);
      url.searchParams.set("type", String(type));
      const response = await fetch(url.toString(), {
        method: "GET", redirect: "manual", signal: controller.signal,
        headers: { Accept: "application/dns-json" },
      });
      if (!response.ok || !(response.headers.get("content-type") || "").includes("application/dns-json")) {
        throw new Error("DNS response rejected");
      }
      const text = await response.text();
      if (text.length > 65536) throw new Error("DNS response oversized");
      const data = JSON.parse(text);
      if (data.Status !== 0 || data.TC === true ||
          !Array.isArray(data.Question) || data.Question.length !== 1 ||
          data.Question[0].type !== type ||
          String(data.Question[0].name).replace(/\.$/, "").toLowerCase() !== hostname.toLowerCase() ||
          (data.Answer !== undefined && !Array.isArray(data.Answer))) throw new Error("DNS response invalid");
      return (data.Answer || []).filter(answer => answer.type === 1 || answer.type === 28)
        .map(answer => ({ address: answer.data }));
    })).then(results => results.flat()), timeout]);
  } finally { clearTimeout(timer); controller.abort(); }
}

export async function validateDestination(value, resolve = resolvePublicDns) {
  const origin = normalizeBaseUrl(value);
  const hostname = new URL(origin).hostname;
  let addresses;
  try {
    // Literal IPs need no resolver and are still checked against public ranges.
    addresses = ipaddr.isValid(hostname) ? [{ address: hostname }] : await resolve(hostname);
  }
  catch (error) {
    const code = ["ENOTFOUND", "EAI_AGAIN", "ETIMEOUT", "ECONNREFUSED", "EPERM", "EACCES"].includes(error?.code)
      ? error.code : "DNS_LOOKUP_FAILED";
    const unavailable = /not (?:supported|implemented)|is not a function/i.test(String(error?.message || ""));
    console.warn("TierX destination validation failed", {
      error_type: unavailable ? "DNS_API_UNAVAILABLE" : code,
      error_name: ["Error", "TypeError", "ReferenceError"].includes(error?.name) ? error.name : "Error",
    });
    throw new Error("TierX destination could not be resolved.");
  }
  if (!addresses.length || addresses.some(({ address }) => {
    try { return ipaddr.process(address).range() !== "unicast"; } catch { return true; }
  })) throw new Error("TierX destination must resolve only to public addresses.");
  return origin;
}
