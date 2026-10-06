import { lookup } from "node:dns/promises";
import ipaddr from "ipaddr.js";
import { normalizeBaseUrl } from "./constants.js";

export async function validateDestination(value, resolve = lookup) {
  const origin = normalizeBaseUrl(value);
  const hostname = new URL(origin).hostname;
  let addresses;
  try { addresses = await resolve(hostname, { all: true, verbatim: true }); }
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
