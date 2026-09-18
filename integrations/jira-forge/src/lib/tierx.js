import api from "@forge/api";
import { kvs } from "@forge/kvs";

import { normalizeBaseUrl } from "./constants.js";

const CONFIG_KEY = "soc-mind:config";
const SECRET_KEY = "soc-mind:integration-secret";

export class TierXRequestError extends Error {
  constructor(message, status) {
    super(message);
    this.name = "TierXRequestError";
    this.status = status;
  }

  get retryable() {
    return this.status === 408 || this.status === 429 || this.status >= 500;
  }
}

export async function getConfig({ includeSecret = false } = {}) {
  const config = await kvs.get(CONFIG_KEY);
  if (!config) {
    throw new Error("TierX is not configured. Ask a Jira administrator to configure the app.");
  }
  const result = { ...config, baseUrl: normalizeBaseUrl(config.baseUrl) };
  if (includeSecret) {
    result.secret = await kvs.getSecret(SECRET_KEY);
    if (!result.secret) throw new Error("TierX integration secret is missing.");
  }
  return result;
}

export async function saveConfig({ baseUrl, integrationId, secret }, cloudId) {
  const candidate = {
    baseUrl: normalizeBaseUrl(baseUrl),
    integrationId: String(integrationId || "").trim(),
    secret: String(secret || "").trim(),
  };
  if (!candidate.integrationId || !candidate.secret) {
    throw new Error("Integration ID and secret are required.");
  }
  const info = await tierxRequest("/api/v1/integrations/jira/connection", {
    config: candidate,
  });
  if (info.jira_cloud_id !== cloudId) {
    throw new Error("The TierX credential is bound to a different Jira site.");
  }
  await kvs.set(CONFIG_KEY, {
    baseUrl: candidate.baseUrl,
    integrationId: candidate.integrationId,
    connectionName: info.name,
    routeCount: info.route_count,
    jiraCloudId: info.jira_cloud_id,
  });
  await kvs.setSecret(SECRET_KEY, candidate.secret);
  return info;
}

export async function publicConfig() {
  const config = await kvs.get(CONFIG_KEY);
  return config
    ? { ...config, configured: Boolean(await kvs.getSecret(SECRET_KEY)) }
    : { baseUrl: "https://tierx.example.com", configured: false };
}

export async function tierxRequest(path, options = {}) {
  const config = options.config || (await getConfig({ includeSecret: true }));
  const response = await api.fetch(`${normalizeBaseUrl(config.baseUrl)}${path}`, {
    method: options.method || "GET",
    headers: {
      Authorization: `Bearer ${config.secret}`,
      "X-TierX-Integration-ID": config.integrationId,
      "X-SOC-Mind-Integration-ID": config.integrationId,
      ...(options.body === undefined ? {} : { "Content-Type": "application/json" }),
      ...(options.headers || {}),
    },
    body:
      options.body === undefined
        ? undefined
        : options.rawBody
          ? options.body
          : JSON.stringify(options.body),
  });
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json")
    ? await response.json()
    : { detail: await response.text() };
  if (!response.ok) {
    const detail = payload?.detail?.message || payload?.detail || `HTTP ${response.status}`;
    throw new TierXRequestError(
      typeof detail === "string" ? detail : JSON.stringify(detail),
      response.status,
    );
  }
  return payload;
}

export function absoluteTierXUrl(config, path) {
  if (!path) return null;
  return `${normalizeBaseUrl(config.baseUrl)}${path.startsWith("/") ? path : `/${path}`}`;
}
