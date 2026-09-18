import crypto from "node:crypto";

import api, { route } from "@forge/api";

import { validateAttachmentManifest } from "./constants.js";

// Jira Cloud negotiates the attachment's stored media type. Asking
// specifically for application/octet-stream returns HTTP 406 for JSON/text
// attachments, so accept the representation Jira provides.
export const ATTACHMENT_DOWNLOAD_HEADERS = Object.freeze({ Accept: "*/*" });

async function json(response, operation) {
  if (!response.ok) {
    throw new Error(`${operation} failed with Jira HTTP ${response.status}.`);
  }
  return response.json();
}

export async function readIssueSnapshot({ accountId, issueKey, cloudId }) {
  const requester = api.asUser(accountId);
  const issue = await json(
    await requester.requestJira(
      route`/rest/api/3/issue/${issueKey}?fields=summary,description,attachment,created,updated,project`,
      { headers: { Accept: "application/json" } },
    ),
    "Issue read",
  );
  const myself = await json(
    await requester.requestJira(route`/rest/api/3/myself`, {
      headers: { Accept: "application/json" },
    }),
    "Submitting user read",
  );
  const server = await json(
    await requester.requestJira(route`/rest/api/3/serverInfo`, {
      headers: { Accept: "application/json" },
    }),
    "Jira site read",
  );
  const rawAttachments = issue.fields?.attachment || [];
  const attachments = validateAttachmentManifest(
    rawAttachments.map((item) => ({
      attachment_id: String(item.id),
      filename: item.filename,
      size: Number(item.size || 0),
      media_type: item.mimeType || null,
      created_at: item.created || null,
      author: item.author || null,
    })),
  );
  const updated = issue.fields?.updated;
  const created = issue.fields?.created;
  const projectKey = issue.fields?.project?.key || issue.key?.split("-", 1)[0];
  if (!updated) throw new Error("Jira issue does not expose an updated timestamp.");
  if (!created) throw new Error("Jira issue does not expose a created timestamp.");
  if (!projectKey) throw new Error("Jira issue does not expose a project key.");
  const siteUrl = String(server.baseUrl || "").replace(/\/+$/, "");
  return {
    jira_cloud_id: cloudId,
    jira_site_url: siteUrl,
    issue_id: String(issue.id),
    issue_key: issue.key,
    project_key: projectKey,
    issue_created_at: created,
    issue_updated_at: updated,
    submitted_by: {
      account_id: accountId,
      display_name: myself.displayName || null,
      email_address: myself.emailAddress || null,
    },
    description: issue.fields?.description || null,
    attachments,
  };
}

export async function downloadAttachment(accountId, attachment) {
  const response = await api
    .asUser(accountId)
    .requestJira(
      route`/rest/api/3/attachment/content/${attachment.attachment_id}?redirect=false`,
      { headers: ATTACHMENT_DOWNLOAD_HEADERS },
    );
  if (!response.ok) {
    throw new Error(
      `Attachment ${attachment.filename} download failed with Jira HTTP ${response.status}.`,
    );
  }
  const content = Buffer.from(await response.arrayBuffer());
  if (content.length !== attachment.size) {
    throw new Error(`Attachment ${attachment.filename} changed during submission.`);
  }
  return {
    content,
    sha256: crypto.createHash("sha256").update(content).digest("hex"),
  };
}
