export const TERMINAL_UI_STATES = new Set([
  "PROCESSING", "CLUSTERED", "ANALYZED", "FAILED", "CANCELLED",
]);

export function permissionCleanupMessage(disconnected) {
  return (disconnected ? "Disconnected. Saved credentials are removed, but outbound permissions remain authorized. " : "Connection saved. Previous outbound permissions may remain authorized. ") +
    "Review TierX in Atlassian Administration → Connected Apps and manually remove unused destinations. Check the current connection before removing a permission; another administrator may have changed it.";
}

export function watchSubmission(invoke, onJob, onError, schedule = setTimeout, unschedule = clearTimeout) {
  let stopped = false, timer;
  const stop = () => { stopped = true; if (timer) unschedule(timer); };
  const fail = () => {
    if (!stopped) onError("Unable to observe submission status. You may close this dialog; processing continues and Jira comments report the outcome.");
    stop();
  };
  const poll = async requestId => {
    try {
      const current = await invoke("getActionStatus", { requestId });
      if (stopped) return;
      if (!current || current.state === "UNKNOWN") { fail(); return; }
      onJob(current);
      if (TERMINAL_UI_STATES.has(current.state)) { stop(); return; }
      timer = schedule(() => poll(requestId), 2000);
    } catch { fail(); }
  };
  Promise.resolve().then(() => invoke("enqueueIssue")).then(queued => {
    if (stopped) return;
    onJob(queued);
    timer = schedule(() => poll(queued.requestId), 2000);
  }).catch(fail);
  return stop;
}
