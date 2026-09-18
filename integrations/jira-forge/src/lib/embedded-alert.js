import crypto from "node:crypto";

export const MAX_EMBEDDED_ALERT_BYTES = 1024 * 1024;

export class RawAlertValidationError extends Error {
  constructor(message) {
    super(message);
    this.name = "RawAlertValidationError";
  }
}

function stableJson(value) {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${stableJson(value[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

function sha256(value) {
  return crypto.createHash("sha256").update(value).digest("hex");
}

function adfNodeText(node) {
  if (!node || typeof node !== "object") return "";
  if (node.type === "text") return String(node.text || "");
  if (node.type === "hardBreak") return "\n";
  const content = Array.isArray(node.content)
    ? node.content.map(adfNodeText).join("")
    : "";
  if (["paragraph", "heading", "codeBlock", "listItem"].includes(node.type)) {
    return `${content}\n`;
  }
  return content;
}

function collectCodeBlocks(node, values = []) {
  if (!node || typeof node !== "object") return values;
  if (node.type === "codeBlock") {
    const text = adfNodeText(node).trim();
    if (text) values.push(text);
    return values;
  }
  for (const child of node.content || []) collectCodeBlocks(child, values);
  return values;
}

function descriptionTexts(description) {
  if (!description) return [];
  if (typeof description === "string") {
    const trimmed = description.trim();
    return trimmed ? [trimmed] : [];
  }
  const blocks = collectCodeBlocks(description);
  if (blocks.length) return blocks;
  const flattened = adfNodeText(description).trim();
  return flattened ? [flattened] : [];
}

function parseRawAlert(text, label) {
  if (Buffer.byteLength(String(text), "utf8") > MAX_EMBEDDED_ALERT_BYTES) {
    throw new Error(`${label} exceeds the 1 MiB embedded-alert limit.`);
  }
  let payload;
  try {
    payload = JSON.parse(String(text).replace(/^\uFEFF/, "").trim());
  } catch {
    throw new Error(`${label} does not contain valid JSON.`);
  }
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    throw new Error(`${label} must contain one JSON object.`);
  }
  const wrapperFields = [
    "tenant_id",
    "source_system",
    "alert_type",
    "timestamp",
    "raw_payload",
  ];
  if (wrapperFields.every((field) => Object.hasOwn(payload, field))) {
    throw new Error(
      `${label} contains the old TierX envelope. Put only its raw_payload object in Jira.`,
    );
  }
  return payload;
}

function isAlertAttachment(attachment) {
  const filename = String(attachment.filename || "").toLowerCase();
  const mediaType = String(attachment.media_type || "")
    .toLowerCase()
    .split(";", 1)[0];
  return (
    filename.endsWith(".json") ||
    filename.endsWith(".txt") ||
    mediaType === "application/json" ||
    mediaType === "text/plain"
  );
}

export async function resolveRawAlert(snapshot, loadAttachment) {
  const candidates = [];
  const failures = [];
  const downloaded = new Map();

  for (const [index, text] of descriptionTexts(snapshot.description).entries()) {
    const label = `Description JSON block ${index + 1}`;
    try {
      const alert = parseRawAlert(text, label);
      candidates.push({
        alert,
        source: {
          kind: "DESCRIPTION",
          sha256: sha256(stableJson(alert)),
        },
      });
    } catch (error) {
      failures.push(error.message);
    }
  }

  for (const attachment of snapshot.attachments || []) {
    if (!isAlertAttachment(attachment)) continue;
    const label = `Attachment ${attachment.filename}`;
    if (Number(attachment.size || 0) > MAX_EMBEDDED_ALERT_BYTES) {
      failures.push(`${label} exceeds the 1 MiB embedded-alert limit.`);
      continue;
    }
    try {
      const file = await loadAttachment(attachment);
      downloaded.set(attachment.attachment_id, file);
      const text = new TextDecoder("utf-8", { fatal: true }).decode(file.content);
      const alert = parseRawAlert(text, label);
      candidates.push({
        alert,
        source: {
          kind: "ATTACHMENT",
          attachment_id: attachment.attachment_id,
          filename: attachment.filename,
          sha256: file.sha256,
        },
      });
    } catch (error) {
      failures.push(`${label} could not be used: ${error.message}`);
    }
  }

  if (candidates.length > 1) {
    throw new RawAlertValidationError(
      "The Jira issue contains multiple raw alert objects. " +
        "Keep exactly one alert in the description or one .json/.txt attachment.",
    );
  }
  if (!candidates.length) {
    const detail = failures.length ? ` ${failures.join(" ")}` : "";
    throw new RawAlertValidationError(
      "No valid raw alert JSON object was found. Put the source alert object in " +
        `the description or one .json/.txt attachment.${detail}`,
    );
  }
  const selected = candidates[0];
  return { ...selected, downloaded };
}
