import assert from "node:assert/strict";
import crypto from "node:crypto";
import test from "node:test";

import {
  RawAlertValidationError,
  resolveRawAlert,
} from "../src/lib/embedded-alert.js";

const alert = {
  search_name: "Endpoint malware",
  result: {
    _time: "2026-08-19T00:00:00Z",
    rule_id: "JIRA-ALERT-1",
    src_ip: "203.0.113.10",
  },
};

function description(value) {
  return {
    type: "doc",
    version: 1,
    content: [
      {
        type: "codeBlock",
        attrs: { language: "json" },
        content: [{ type: "text", text: value }],
      },
    ],
  };
}

function snapshot({ descriptionValue = null, attachments = [] } = {}) {
  return {
    description: descriptionValue,
    attachments,
  };
}

function loader(values) {
  return async (attachment) => {
    const content = Buffer.from(values[attachment.attachment_id], "utf8");
    return {
      content,
      sha256: crypto.createHash("sha256").update(content).digest("hex"),
    };
  };
}

test("extracts raw source JSON from a Jira description code block", async () => {
  const result = await resolveRawAlert(
    snapshot({ descriptionValue: description(JSON.stringify(alert)) }),
    loader({}),
  );
  assert.deepEqual(result.alert, alert);
  assert.equal(result.source.kind, "DESCRIPTION");
  assert.match(result.source.sha256, /^[a-f0-9]{64}$/);
});

test("extracts an alert from a JSON or text attachment", async () => {
  const attachment = {
    attachment_id: "att-1",
    filename: "splunk-alert.txt",
    media_type: "text/plain",
    size: JSON.stringify(alert).length,
  };
  const result = await resolveRawAlert(
    snapshot({ attachments: [attachment] }),
    loader({ "att-1": JSON.stringify(alert) }),
  );
  assert.deepEqual(result.alert, alert);
  assert.equal(result.source.kind, "ATTACHMENT");
  assert.equal(result.source.attachment_id, "att-1");
  assert.ok(result.downloaded.has("att-1"));
});

test("rejects the same alert when supplied in both description and attachment", async () => {
  const encoded = JSON.stringify(alert);
  await assert.rejects(
    resolveRawAlert(
      snapshot({
        descriptionValue: description(encoded),
        attachments: [
          {
            attachment_id: "att-1",
            filename: "alert.json",
            media_type: "application/json",
            size: encoded.length,
          },
        ],
      }),
      loader({ "att-1": encoded }),
    ),
    /multiple raw alert objects/,
  );
});

test("rejects multiple different raw alerts", async () => {
  const second = { ...alert, result: { ...alert.result, rule_id: "DIFFERENT" } };
  await assert.rejects(
    resolveRawAlert(
      snapshot({
        descriptionValue: description(JSON.stringify(alert)),
        attachments: [
          {
            attachment_id: "att-1",
            filename: "other.json",
            size: JSON.stringify(second).length,
          },
        ],
      }),
      loader({ "att-1": JSON.stringify(second) }),
    ),
    /multiple raw alert objects/,
  );
});

test("rejects the legacy TierX envelope", async () => {
  const wrapper = {
    tenant_id: "tenant-1",
    source_system: "SPLUNK",
    alert_type: "splunk.notable.endpoint_malware",
    timestamp: "2026-08-19T00:00:00Z",
    raw_payload: alert,
  };
  await assert.rejects(
    resolveRawAlert(
      snapshot({ descriptionValue: description(JSON.stringify(wrapper)) }),
      loader({}),
    ),
    (error) =>
      error instanceof RawAlertValidationError &&
      /old TierX envelope/.test(error.message),
  );
});
