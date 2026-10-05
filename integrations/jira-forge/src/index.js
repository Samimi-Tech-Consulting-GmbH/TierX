import crypto from "node:crypto";

import api, { route } from "@forge/api";
import { makeResolver } from "@forge/resolver";
import { Queue } from "@forge/events";
import { kvs } from "@forge/kvs";

import { publicConfig, saveConfig, testConnection, disconnect, prepareConnection } from "./lib/tierx.js";

const queue = new Queue({ key: "soc-mind-jira-submit" });

export async function requireJiraAdministrator(accountId, client = api) {
  if (!accountId) throw new Error("Jira administrator context is unavailable.");
  const response = await client
    .asUser(accountId)
    .requestJira(route`/rest/api/3/mypermissions?permissions=ADMINISTER`, {
      headers: { Accept: "application/json" },
    });
  if (!response.ok) throw new Error("Jira administrator permission check failed.");
  const payload = await response.json();
  if (!payload.permissions?.ADMINISTER?.havePermission) {
    throw new Error("Jira administrator permission is required.");
  }
}

export const handler = makeResolver({
  prepareConnection: async ({ payload, context }) => {
    await requireJiraAdministrator(context.accountId);
    return prepareConnection(payload.baseUrl);
  },
  testConnection: async ({ context }) => {
    await requireJiraAdministrator(context.accountId);
    return testConnection(context.cloudId);
  },
  disconnect: async ({ context }) => {
    await requireJiraAdministrator(context.accountId);
    return disconnect();
  },
  getConfig: async ({ context }) => {
    await requireJiraAdministrator(context.accountId);
    return publicConfig();
  },

  saveConfig: async ({ payload, context }) => {
    await requireJiraAdministrator(context.accountId);
    if (!context.cloudId) throw new Error("Jira cloud context is unavailable.");
    return saveConfig(payload, context.cloudId);
  },

  enqueueIssue: async ({ context }) => {
    const issueKey = context.extension?.issue?.key;
    if (!issueKey || !context.accountId || !context.cloudId) {
      throw new Error("Jira issue or user context is unavailable.");
    }
    const config = await publicConfig();
    if (!config.configured) throw new Error("TierX is not configured.");
    const requestId = crypto.randomUUID();
    await kvs.set(`job:${requestId}`, {
      requestId,
      issueKey,
      state: "QUEUED",
      createdAt: new Date().toISOString(),
    });
    await queue.push({
      body: {
        requestId,
        issueKey,
        accountId: context.accountId,
        cloudId: context.cloudId,
        connectionIdentity: config.identity,
      },
      concurrency: { key: "soc-mind-jira-submit", limit: 2 },
    });
    return { requestId, issueKey, state: "QUEUED" };
  },

  getActionStatus: async ({ payload }) => {
    return (await kvs.get(`job:${payload.requestId}`)) || {
      requestId: payload.requestId,
      state: "UNKNOWN",
    };
  },
});
