import assert from "node:assert/strict";
import test from "node:test";

import {
  MAX_ATTACHMENT_BYTES,
  normalizeBaseUrl,
  priorityToSeverity,
  safeError,
  validateAttachmentManifest,
} from "../src/lib/constants.js";

test("customer HTTPS origins are accepted without paths or credentials", () => {
  assert.equal(normalizeBaseUrl("https://tierx.example.com/"), "https://tierx.example.com");
  assert.equal(normalizeBaseUrl("https://customer.example"), "https://customer.example");
  for (const url of ["http://customer.example", "https://customer.example/api", "https://x:y@customer.example", "https://customer.example?x=1", "https://customer.example#x", "https://customer.example:8443", "https://localhost", "https://host.internal"]) {
    assert.throws(() => normalizeBaseUrl(url));
  }
});

test("Jira priorities map deterministically to pipeline severity", () => {
  assert.equal(priorityToSeverity("Blocker"), "5");
  assert.equal(priorityToSeverity("Highest"), "5");
  assert.equal(priorityToSeverity("High"), "4");
  assert.equal(priorityToSeverity("Medium"), "3");
  assert.equal(priorityToSeverity("custom"), "3");
  assert.equal(priorityToSeverity("Low"), "2");
  assert.equal(priorityToSeverity("Trivial"), "1");
});

test("attachment count, per-file size, and total size are enforced", () => {
  assert.equal(
    validateAttachmentManifest([{ filename: "ok", size: MAX_ATTACHMENT_BYTES }]).length,
    1,
  );
  assert.throws(
    () => validateAttachmentManifest([{ filename: "large", size: MAX_ATTACHMENT_BYTES + 1 }]),
    /exceeds 5 MiB/,
  );
  assert.throws(
    () =>
      validateAttachmentManifest(
        Array.from({ length: 5 }, (_, index) => ({
          filename: `file-${index}`,
          size: MAX_ATTACHMENT_BYTES,
        })),
      ),
    /20 MiB total/,
  );
});

test("credential-like errors are suppressed", () => {
  assert.match(safeError(new Error("Bearer top-secret")), /suppressed/);
  assert.equal(safeError(new Error("Jira returned 403")), "Jira returned 403");
});
