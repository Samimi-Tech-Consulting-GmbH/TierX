import api from "@forge/api";
import { kvs } from "@forge/kvs";
import { AsyncLocalStorage } from "node:async_hooks";
import { createHash } from "node:crypto";
import { normalizeBaseUrl } from "./constants.js";
import { validateDestination } from "./destination.js";
import { createConnectionStore, publicConnection } from "./connection-store.js";

const binding = new AsyncLocalStorage();
export const withConnection = (identity, operation) => binding.run(identity || "missing-connection", operation);
export class TierXRequestError extends Error {
  constructor(message, status) { super(message); this.name = "TierXRequestError"; this.status = status; }
  get retryable() { return this.status === 408 || this.status === 429 || this.status >= 500; }
}
const store = createConnectionStore(kvs, candidate =>
  tierxRequest("/api/v1/integrations/jira/connection", { candidate }));
export async function getConfig({ includeSecret = false } = {}) {
  const config = await store.read(binding.getStore());
  return includeSecret ? config : publicConnection(config);
}
export async function saveConfig({ baseUrl, integrationId, secret }, cloudId) {
  const destination = await prepareConnection(baseUrl);
  const candidate = {
    ...destination,
    integrationId: String(integrationId || "").trim(),
    secret: String(secret || "").trim(),
  };
  if (!candidate.integrationId || !candidate.secret) throw new Error("Connection ID and secret are required.");
  return store.save(candidate, cloudId);
}
export async function prepareConnection(baseUrl) {
  const origin = await validateDestination(baseUrl);
  return { baseUrl: origin, egressKey: "tierx-" + createHash("sha256").update(origin).digest("hex").slice(0, 32) };
}
export const publicConfig = () => store.public();
export const disconnect = () => store.disconnect();
export async function testConnection(cloudId) {
  const config = await getConfig();
  return withConnection(config.identity, async () => {
    const info = await tierxRequest("/api/v1/integrations/jira/connection");
    if (info.jira_cloud_id !== cloudId) throw new Error("Connection belongs to a different Jira site.");
    return { ...config, connectionName: info.name, routeCount: info.route_count };
  });
}
export async function tierxRequest(path, options = {}) {
  if (!/^\/api\/v1\/integrations\/jira\/[a-zA-Z0-9/_-]+$/.test(path)) throw new Error("Invalid TierX API path.");
  const config = options.candidate || await store.read(binding.getStore());
  const origin = await validateDestination(config.baseUrl);
  if (!options.candidate) await store.read(config.identity);
  return sendRequest(origin, path, config, options);
}
export async function sendRequest(origin, path, config, options = {}, fetch = api.fetch, timeoutMs = 20000) {
  const controller = new AbortController();
  let timer;
  const deadline = new Promise((_, reject) => {
    timer = setTimeout(() => {
      controller.abort();
      reject(new TierXRequestError("TierX connection timed out.", 408));
    }, timeoutMs);
  });
  try {
    return await Promise.race([
      performRequest(origin, path, config, options, (url, init) => fetch(url, { ...init, signal: controller.signal })),
      deadline,
    ]);
  } finally { clearTimeout(timer); controller.abort(); }
}
async function performRequest(origin, path, config, options, fetch) {
  let response;
  try {
    // Forge enforces administrator-approved egress on every request, including jobs.
    response = await fetch(origin + path, {
      method: options.method || "GET", redirect: "manual",
      headers: {
        Authorization: `Bearer ${config.secret}`,
        "X-TierX-Integration-ID": config.integrationId,
        ...(options.body === undefined ? {} : { "Content-Type": "application/json" }),
      },
      body: options.body === undefined ? undefined : options.rawBody ? options.body : JSON.stringify(options.body),
    });
  } catch { throw new TierXRequestError("TierX connection failed. Check server availability and approved outbound access.", 503); }
  if (response.status >= 300 && response.status < 400) throw new TierXRequestError("TierX redirects are not permitted.", 400);
  // Never reflect arbitrary upstream text into Jira.
  if (!response.ok) throw new TierXRequestError(`TierX returned HTTP ${response.status}.`, response.status);
  if (!(response.headers.get("content-type") || "").includes("application/json")) throw new TierXRequestError("TierX returned an invalid response.", 502);
  try { return await response.json(); }
  catch { throw new TierXRequestError("TierX returned invalid JSON.", 502); }
}
export function absoluteTierXUrl(config, path) {
  if (!path) return null;
  return normalizeBaseUrl(config.baseUrl) + (path.startsWith("/") ? path : `/${path}`);
}
