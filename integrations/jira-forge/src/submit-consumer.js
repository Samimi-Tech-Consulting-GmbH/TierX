import { InvocationError, InvocationErrorCode } from "@forge/events";
import { kvs } from "@forge/kvs";

import {
  acknowledgementComment,
  addAppComment,
  commentMarker,
  failureComment,
  finalComment,
  inputFailureComment,
} from "./lib/comments.js";
import { safeError } from "./lib/constants.js";
import {
  RawAlertValidationError,
  resolveRawAlert,
} from "./lib/embedded-alert.js";
import { downloadAttachment, readIssueSnapshot } from "./lib/jira.js";
import { getConfig, TierXRequestError, tierxRequest, withConnection } from "./lib/tierx.js";
import { ConnectionChangedError, cancelConnectionJob } from "./lib/connection-store.js";

async function reportComment(submissionId, kind, commentId) {
  return tierxRequest(`/api/v1/integrations/jira/submissions/${submissionId}/comments`, {
    method: "POST",
    body: { kind, jira_comment_id: String(commentId) },
  });
}

async function postOnce(submission, kind, body) {
  if (submission.comments?.[kind]) return submission;
  const comment = await addAppComment(
    submission.issue_key,
    body,
    commentMarker(submission, kind),
  );
  return reportComment(submission.submission_id, kind, comment.id);
}

export async function handler(event) {
  return withConnection(event.body.connectionIdentity, () => consume(event));
}
async function consume(event) {
  const { requestId, issueKey, accountId, cloudId } = event.body;
  let submission = null;
  let resolvedAlert = null;
  try {
    await kvs.set(`job:${requestId}`, { requestId, issueKey, state: "READING_ISSUE" });
    const config = await getConfig();
    const snapshot = await readIssueSnapshot({ accountId, issueKey, cloudId });
    await kvs.set(`job:${requestId}`, { requestId, issueKey, state: "READING_ALERT" });
    resolvedAlert = await resolveRawAlert(
      snapshot,
      (attachment) => downloadAttachment(accountId, attachment),
    );
    const submissionRequest = {
      jira_cloud_id: snapshot.jira_cloud_id,
      jira_site_url: snapshot.jira_site_url,
      issue_id: snapshot.issue_id,
      issue_key: snapshot.issue_key,
      project_key: snapshot.project_key,
      issue_created_at: snapshot.issue_created_at,
      issue_updated_at: snapshot.issue_updated_at,
      submitted_by: snapshot.submitted_by,
      raw_alert: resolvedAlert.alert,
      raw_alert_source: resolvedAlert.source,
    };
    await kvs.set(`job:${requestId}`, { requestId, issueKey, state: "CREATING_SUBMISSION" });
    submission = await tierxRequest("/api/v1/integrations/jira/submissions", {
      method: "POST",
      body: submissionRequest,
    });

    try {
      submission = await postOnce(
        submission,
        "ACKNOWLEDGEMENT",
        acknowledgementComment(
          submission,
          config,
          snapshot.submitted_by.display_name || snapshot.submitted_by.account_id,
        ),
      );
    } catch (commentError) {
      await kvs.set(`job:${requestId}:comment-warning`, safeError(commentError));
    }

    submission = await tierxRequest(
      `/api/v1/integrations/jira/submissions/${submission.submission_id}/finalize`,
      { method: "POST", body: {} },
    );
    if (submission.state === "FAILED") {
      try {
        submission = await postOnce(
          submission,
          "ERROR",
          failureComment(submission, config),
        );
      } catch (commentError) {
        await kvs.set(`job:${requestId}:comment-warning`, safeError(commentError));
      }
      await kvs.set(`job:${requestId}`, {
        requestId,
        issueKey,
        submissionId: submission.submission_id,
        alertId: submission.alert_id,
        state: "FAILED",
        failure: submission.failure,
      });
      return;
    }
    if (submission.state === "ANALYZED") {
      submission = await postOnce(submission, "FINAL", finalComment(submission, config));
    } else {
      await kvs.set(`pending:${submission.submission_id}`, {
        connectionIdentity: config.identity,
        submissionId: submission.submission_id,
        issueKey,
        requestId,
      });
    }
    await kvs.set(`job:${requestId}`, {
      requestId,
      issueKey,
      submissionId: submission.submission_id,
      alertId: submission.alert_id,
      state: submission.state,
      tracePath: submission.trace_path,
    });
  } catch (error) {
    if (error instanceof ConnectionChangedError) {
      await cancelConnectionJob(kvs, { requestId, issueKey });
      return;
    }
    const retryCount = Number(event.retryContext?.retryCount || 0);
    const deterministicRequestFailure =
      error instanceof TierXRequestError && !error.retryable;
    if (
      !(error instanceof RawAlertValidationError) &&
      !(error instanceof ConnectionChangedError) &&
      !deterministicRequestFailure &&
      retryCount < 2
    ) {
      return new InvocationError({
        retryAfter: 30 * (retryCount + 1),
        retryReason: InvocationErrorCode.FUNCTION_RETRY_REQUEST,
        retryData: { requestId, issueKey },
      });
    }
    const detail = safeError(error);
    if (submission?.submission_id) {
      try {
        submission = await tierxRequest(
          `/api/v1/integrations/jira/submissions/${submission.submission_id}/fail`,
          {
            method: "POST",
            body: {
              failed_stage: "JIRA_TRANSFER",
              error_type: error?.name || "JIRA_TRANSFER_FAILED",
              error_detail: detail,
            },
          },
        );
        const config = await getConfig();
        await postOnce(submission, "ERROR", failureComment(submission, config));
      } catch {
        // The job record remains the durable operator-visible failure if comment reporting also fails.
      }
    } else if (
      error instanceof RawAlertValidationError ||
      deterministicRequestFailure
    ) {
      try {
        await addAppComment(
          issueKey,
          inputFailureComment(requestId, detail),
          `TierX reference: INPUT/${requestId}`,
        );
      } catch {
        // The local job state still explains a deterministic input failure when
        // Jira comment permission is unavailable.
      }
    }
    await kvs.set(`job:${requestId}`, {
      requestId,
      issueKey,
      submissionId: submission?.submission_id,
      alertId: submission?.alert_id,
      state: "FAILED",
      failure: { failed_stage: "JIRA_TRANSFER", error_detail: detail },
    });
  }
}
