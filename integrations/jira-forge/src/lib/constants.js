export const ALLOWED_TIERX_URLS = new Set(["https://tierx.example.com"]);
export const MAX_ATTACHMENTS = 20;
export const MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024;
export const MAX_ATTACHMENT_TOTAL_BYTES = 20 * 1024 * 1024;

export function normalizeBaseUrl(value) {
  const candidate = String(value || "").trim().replace(/\/+$/, "");
  if (!ALLOWED_TIERX_URLS.has(candidate)) {
    throw new Error("TierX URL is not allow-listed by this Forge app version.");
  }
  return candidate;
}

export function priorityToSeverity(priorityName) {
  switch (String(priorityName || "").trim().toLowerCase()) {
    case "highest":
    case "blocker":
      return "5";
    case "high":
      return "4";
    case "low":
      return "2";
    case "lowest":
    case "trivial":
      return "1";
    default:
      return "3";
  }
}

export function validateAttachmentManifest(attachments) {
  if (attachments.length > MAX_ATTACHMENTS) {
    throw new Error(`Issue has more than ${MAX_ATTACHMENTS} attachments.`);
  }
  let total = 0;
  for (const item of attachments) {
    const size = Number(item.size || 0);
    if (size > MAX_ATTACHMENT_BYTES) {
      throw new Error(`Attachment ${item.filename} exceeds 5 MiB.`);
    }
    total += size;
  }
  if (total > MAX_ATTACHMENT_TOTAL_BYTES) {
    throw new Error("Issue attachments exceed the 20 MiB total limit.");
  }
  return attachments;
}

export function safeError(error) {
  const text = String(error?.message || error || "Unexpected integration error");
  if (/authorization|bearer |password|secret|token/i.test(text)) {
    return "An upstream request failed; sensitive detail was suppressed.";
  }
  return text.slice(0, 2000);
}
