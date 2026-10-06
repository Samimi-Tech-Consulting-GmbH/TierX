import { kvs, WhereConditions } from "@forge/kvs";

import { addAppComment, commentMarker, failureComment, finalComment } from "./lib/comments.js";
import { getConfig, tierxRequest, withConnection, TierXRequestError } from "./lib/tierx.js";
import { ConnectionChangedError } from "./lib/connection-store.js";

const POLL_CURSOR_KEY = "soc-mind:pending-poll-cursor";

export function safePollFailure(error) {
  if (error instanceof TierXRequestError) {
    return { error_type: "TIERX_REQUEST_FAILED", http_status:
      Number.isInteger(error.status) && error.status >= 100 && error.status <= 599
        ? error.status : null, retryable: Boolean(error.retryable) };
  }
  // Known local validation messages only; never persist arbitrary upstream text.
  if (error?.message === "TierX destination could not be resolved.") {
    return { error_type: "DESTINATION_DNS_FAILURE" };
  }
  if (error?.message === "TierX destination must resolve only to public addresses.") {
    return { error_type: "DESTINATION_NOT_PUBLIC" };
  }
  return { error_type: "POLLING_FAILURE" };
}

function pendingQuery(storage, cursor) {
  let query = storage
    .query()
    .where("key", WhereConditions.beginsWith("pending:"))
    .limit(100);
  if (cursor) query = query.cursor(cursor);
  return query;
}

export async function getPendingPage(storage = kvs) {
  const cursor = await storage.get(POLL_CURSOR_KEY);
  let page;
  try {
    page = await pendingQuery(storage, cursor).getMany();
  } catch (error) {
    if (!cursor) throw error;
    // A cursor can become invalid after pending keys are deleted. Restarting
    // from the first page preserves progress without failing the trigger.
    await storage.delete(POLL_CURSOR_KEY);
    page = await pendingQuery(storage, null).getMany();
  }
  if (page.nextCursor) {
    await storage.set(POLL_CURSOR_KEY, page.nextCursor);
  } else {
    await storage.delete(POLL_CURSOR_KEY);
  }
  return page;
}

async function recordComment(submissionId, kind, commentId) {
  return tierxRequest(`/api/v1/integrations/jira/submissions/${submissionId}/comments`, {
    method: "POST",
    body: { kind, jira_comment_id: String(commentId) },
  });
}

async function terminalComment(submission, config) {
  const kind = submission.state === "ANALYZED" ? "FINAL" : "ERROR";
  if (submission.comments?.[kind]) return submission;
  const body =
    kind === "FINAL"
      ? finalComment(submission, config)
      : failureComment(submission, config);
  const comment = await addAppComment(
    submission.issue_key,
    body,
    commentMarker(submission, kind),
  );
  return recordComment(submission.submission_id, kind, comment.id);
}

export async function refreshPendingSubmission(pending, request = tierxRequest) {
  let submission = await request(
    `/api/v1/integrations/jira/submissions/${pending.submissionId}`,
  );
  if (submission.state === "FINALIZING") {
    submission = await request(
      `/api/v1/integrations/jira/submissions/${pending.submissionId}/finalize`,
      { method: "POST", body: {} },
    );
  }
  return submission;
}

export async function handler() {
  const page = await getPendingPage();
  for (const item of page.results) {
    const pending = item.value;
    await withConnection(pending.connectionIdentity, async () => {
    try {
      const config = await getConfig();
      let submission = await refreshPendingSubmission(pending);
      await kvs.set(`job:${pending.requestId}`, {
        requestId: pending.requestId,
        issueKey: pending.issueKey,
        submissionId: submission.submission_id,
        alertId: submission.alert_id,
        state: submission.state,
        tracePath: submission.trace_path,
      });
      if (submission.state === "ANALYZED" || submission.state === "FAILED") {
        submission = await terminalComment(submission, config);
        await kvs.delete(item.key);
      }
    } catch (error) {
      if (error instanceof ConnectionChangedError) {
        await kvs.set(`job:${pending.requestId}`, { requestId: pending.requestId, issueKey: pending.issueKey, state: "CANCELLED", failure: { error_detail: error.message } });
        await kvs.delete(item.key);
        return;
      }
      // Scheduled triggers do not retry automatically. Keeping the pending key
      // makes the next five-minute invocation retry without resubmitting Jira.
      await kvs.set(`poll-error:${pending.submissionId}`, {
        at: new Date().toISOString(),
        message: "TierX polling failed. Check the connection and outbound permissions.",
        ...safePollFailure(error),
      });
    }
    });
  }
}
