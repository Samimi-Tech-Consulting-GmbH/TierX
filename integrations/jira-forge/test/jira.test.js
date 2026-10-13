import assert from "node:assert/strict";
import test from "node:test";

import { ATTACHMENT_DOWNLOAD_HEADERS, requireIssueViewer } from "../src/lib/jira.js";

test("accepts Jira Cloud's stored media type when downloading attachments", () => {
  assert.deepEqual(ATTACHMENT_DOWNLOAD_HEADERS, { Accept: "*/*" });
});

test("any issue viewer can read status without administrator privileges", async () => {
  let user;
  await requireIssueViewer("another-viewer", "TEST-1", { asUser: account => {
    user = account;
    return { requestJira: async () => ({ ok: true }) };
  } });
  assert.equal(user, "another-viewer");
});
test("issue status fails closed for missing identity and denied issue access", async () => {
  await assert.rejects(requireIssueViewer(null, "TEST-1"), /issue access/);
  for (const status of [401, 403, 404, 500]) {
    await assert.rejects(requireIssueViewer("viewer", "TEST-1", {
      asUser: () => ({ requestJira: async () => ({ ok: false, status }) }),
    }), { message: "Jira issue access is required." });
  }
});
