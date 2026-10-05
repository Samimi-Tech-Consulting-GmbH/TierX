import { lookup } from "node:dns/promises";
import ipaddr from "ipaddr.js";
import { normalizeBaseUrl } from "./constants.js";

export async function validateDestination(value, resolve = lookup) {
  const origin = normalizeBaseUrl(value);
  const hostname = new URL(origin).hostname;
  let addresses;
  try { addresses = await resolve(hostname, { all: true, verbatim: true }); }
  catch { throw new Error("TierX destination could not be resolved."); }
  if (!addresses.length || addresses.some(({ address }) => {
    try { return ipaddr.process(address).range() !== "unicast"; } catch { return true; }
  })) throw new Error("TierX destination must resolve only to public addresses.");
  return origin;
}
