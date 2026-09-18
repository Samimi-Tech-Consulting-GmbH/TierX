import assert from "node:assert/strict";
import test from "node:test";

import { ATTACHMENT_DOWNLOAD_HEADERS } from "../src/lib/jira.js";

test("accepts Jira Cloud's stored media type when downloading attachments", () => {
  assert.deepEqual(ATTACHMENT_DOWNLOAD_HEADERS, { Accept: "*/*" });
});
