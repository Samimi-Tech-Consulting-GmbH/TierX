import api, { route } from "@forge/api";

function text(value) {
  return { type: "text", text: String(value) };
}

function paragraph(...content) {
  return { type: "paragraph", content };
}

function link(label, href) {
  return { type: "text", text: label, marks: [{ type: "link", attrs: { href } }] };
}

function bulletList(items) {
  return {
    type: "bulletList",
    content: items.map((item) => ({
      type: "listItem",
      content: [paragraph(text(item))],
    })),
  };
}

function document(content) {
  return { type: "doc", version: 1, content };
}

export function commentMarker(submission, kind) {
  return `TierX reference: ${kind}/${submission.submission_id}`;
}

export function acknowledgementComment(submission, config, submittedBy) {
  return document([
    paragraph(text("TierX submission accepted")),
    paragraph(text(`Alert UUID: ${submission.alert_id}`)),
    paragraph(
      text(
        `Routed alert: ${submission.source_system || "UNKNOWN"} / ${
          submission.alert_type || "UNKNOWN"
        }`,
      ),
    ),
    paragraph(text(`Issue revision: ${submission.issue_updated_at}`)),
    paragraph(text(`Submitted by: ${submittedBy || "unknown Jira user"}`)),
    paragraph(link("Open processing trace", `${config.baseUrl}${submission.trace_path}`)),
    paragraph(text(commentMarker(submission, "ACKNOWLEDGEMENT"))),
  ]);
}

export function finalComment(submission, config) {
  const result = submission.result || {};
  const content = [
    paragraph(text("TierX analysis completed")),
    paragraph(text(result.headline || "Analysis completed without a headline.")),
    paragraph(text(result.narrative || "No narrative was returned.")),
    paragraph(text(`Confidence: ${result.confidence || "UNKNOWN"}`)),
  ];
  if (Array.isArray(result.recommended_actions) && result.recommended_actions.length) {
    content.push(paragraph(text("Recommended actions:")));
    content.push(bulletList(result.recommended_actions));
  }
  const resultPath = submission.cluster_path || submission.alert_path;
  content.push(paragraph(link("Open result in TierX", `${config.baseUrl}${resultPath}`)));
  content.push(paragraph(text(commentMarker(submission, "FINAL"))));
  return document(content);
}

export function failureComment(submission, config) {
  const failure = submission.failure || {};
  return document([
    paragraph(text("TierX processing failed")),
    paragraph(text(`Stage: ${failure.failed_stage || "UNKNOWN"}`)),
    paragraph(text(`Type: ${failure.error_type || "PROCESSING_FAILED"}`)),
    paragraph(text(failure.error_detail || "No safe error detail was returned.")),
    paragraph(link("Open processing trace", `${config.baseUrl}${submission.trace_path}`)),
    paragraph(text(commentMarker(submission, "ERROR"))),
  ]);
}

export function inputFailureComment(requestId, detail) {
  return document([
    paragraph(text("TierX submission rejected")),
    paragraph(
      text(
        "TierX could not route or validate one raw alert JSON object from this issue.",
      ),
    ),
    paragraph(text(detail)),
    paragraph(
      text(
        "Put the unwrapped source alert JSON in the description or one .json/.txt " +
          "attachment. Tenant, source system, and alert type come from the TierX project route.",
      ),
    ),
    paragraph(text(`TierX reference: INPUT/${requestId}`)),
  ]);
}

async function findExistingComment(issueKey, marker) {
  let startAt = 0;
  while (true) {
    const response = await api
      .asApp()
      .requestJira(
        route`/rest/api/3/issue/${issueKey}/comment?startAt=${startAt}&maxResults=100`,
        { headers: { Accept: "application/json" } },
      );
    if (!response.ok) return null;
    const page = await response.json();
    const found = (page.comments || []).find((comment) =>
      JSON.stringify(comment.body || {}).includes(marker),
    );
    if (found) return found;
    startAt += (page.comments || []).length;
    if (!page.comments?.length || startAt >= Number(page.total || 0)) return null;
  }
}

export async function addAppComment(issueKey, body, marker) {
  const existing = await findExistingComment(issueKey, marker);
  if (existing) return existing;
  const response = await api.asApp().requestJira(route`/rest/api/3/issue/${issueKey}/comment`, {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify({ body }),
  });
  if (!response.ok) {
    throw new Error(`Jira comment creation failed with HTTP ${response.status}.`);
  }
  return response.json();
}
