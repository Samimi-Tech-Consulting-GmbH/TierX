"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { WorkflowExecutionMap } from "@/components/workflow-execution-map";
import {
  loadExecution,
  newExecutionCache,
  permanentReadError,
  type Execution,
} from "@/lib/workflow-execution";
import { workflowRequest } from "@/lib/workflows";
import { formatDurationMs } from "@/lib/duration";
import { formatLocaleDateTime } from "@/lib/datetime";
import { useAuth } from "@/lib/auth";
import { UserRole } from "@/lib/types";
import { studioButton } from "@/components/workflow-library";
import { executionDebugHome } from "@/lib/execution-navigation";

export function WorkflowRunView({
  tenantId,
  runId,
}: {
  tenantId: string;
  runId: string;
}) {
  const { user } = useAuth();
  const key = `${tenantId}:${runId}`;
  const cache = useRef({ key: "", revision: -1, value: newExecutionCache() });
  const loadedKey = useRef("");
  const [loaded, setLoaded] = useState<{
      key: string;
      execution: Execution;
    } | null>(null),
    [error, setError] = useState("");
  const [paused, setPaused] = useState(false),
    [revision, setRevision] = useState(0),
    [refreshedAt, setRefreshedAt] = useState(0);
  const execution = loaded?.key === key ? loaded.execution : null,
    run = execution?.root;
  useEffect(() => {
    const manualOrNew =
      cache.current.key !== key || cache.current.revision !== revision;
    if (manualOrNew)
      cache.current = { key, revision, value: newExecutionCache() };
    if (paused && loadedKey.current === key && !manualOrNew) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    let failures = 0;
    async function refresh() {
      try {
        const value = await loadExecution(
          tenantId,
          runId,
          controller.signal,
          cache.current.value,
        );
        if (controller.signal.aborted) return;
        setLoaded({ key, execution: value });
        loadedKey.current = key;
        failures = 0;
        setRefreshedAt(Date.now());
        setError("");
        if (
          !paused &&
          (value.retryable ||
            value.runs.some((run) =>
              ["PENDING", "RUNNING"].includes(run.state),
            ))
        )
          timer = setTimeout(refresh, 5000);
      } catch (reason) {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : "Refresh failed");
          if (!paused && !permanentReadError(reason))
            timer = setTimeout(
              refresh,
              Math.min(30000, 5000 * 2 ** failures++),
            );
        }
      }
    }
    void refresh();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [key, tenantId, runId, paused, revision]);
  async function cancel() {
    if (
      !run ||
      !confirm(
        "Cancel this workflow and its subflows? Already dispatched external requests cannot be recalled.",
      )
    )
      return;
    try {
      await workflowRequest(
        `/tenants/${encodeURIComponent(tenantId)}/runs/${encodeURIComponent(run.run_id)}/cancel`,
        "POST",
      );
      setRevision((value) => value + 1);
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Cancellation failed",
      );
    }
  }
  if (!run || !execution)
    return (
      <section className="p-6">
        <p role="status">{error || "Loading complete execution…"}</p>
        {error && (
          <button
            className={studioButton}
            onClick={() => setRevision((value) => value + 1)}
          >
            Retry execution
          </button>
        )}
      </section>
    );
  const elapsed = Math.max(
    0,
    (run.completed_at ? new Date(run.completed_at).getTime() : refreshedAt) -
      new Date(run.created_at).getTime(),
  );
  return (
    <main className="space-y-4 p-4 md:p-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-2">
          <Link
            className="mr-4 text-sm text-muted-foreground hover:text-primary"
            href={executionDebugHome(
              tenantId,
              user?.role === UserRole.PLATFORM_ADMIN,
            )}
          >
            ← Back to Debug
          </Link>
          <Link
            className="text-sm text-muted-foreground hover:text-primary"
            href={`/dashboard/${tenantId}/alerts/${run.alert_id}`}
          >
            ← Back to alert
          </Link>
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-2xl font-semibold">Execution debug</h1>
            <span
              className={`rounded-full px-3 py-1 text-xs font-medium ${run.state === "SUCCEEDED" ? "bg-emerald-500/15 text-emerald-400" : run.state === "FAILED" ? "bg-red-500/15 text-red-400" : "bg-muted"}`}
            >
              {run.state}
            </span>
          </div>
          <p className="text-sm text-muted-foreground">
            elapsed {formatDurationMs(elapsed)} · ingested{" "}
            {formatLocaleDateTime(run.created_at)}
          </p>
        </div>
        <nav className="flex flex-wrap gap-2" aria-label="Execution controls">
          <button
            className={studioButton}
            onClick={() => setRevision((value) => value + 1)}
          >
            Refresh execution
          </button>
          {execution.runs.some((run) =>
            ["PENDING", "RUNNING"].includes(run.state),
          ) && (
            <button
              className={studioButton}
              onClick={() => setPaused((value) => !value)}
            >
              {paused ? "Resume watching" : "Pause watching"}
            </button>
          )}
          {user?.role === UserRole.PLATFORM_ADMIN &&
            ["PENDING", "RUNNING"].includes(run.state) && (
              <button
                className={studioButton + " text-destructive"}
                onClick={cancel}
              >
                Cancel execution
              </button>
            )}
          <button
            className={studioButton}
            onClick={async () => {
              try {
                await navigator.clipboard.writeText(
                  JSON.stringify(
                    {
                      root_run_id: run.run_id,
                      alert_id: run.alert_id,
                      workflow_version: run.workflow_version,
                      complete: execution.issues.length === 0,
                      issues: execution.issues,
                      runs: execution.runs.map((value) => ({
                        run_id: value.run_id,
                        parent_run_id: value.parent_run_id,
                        parent_job_id: value.parent_job_id,
                        definition: value.definition_ref,
                        state: value.state,
                        version: value.release_version,
                        sha: value.release_sha,
                        stages: value.nodes?.map(
                          ({
                            node_id,
                            definition_ref,
                            state,
                            port,
                            attempt_count,
                            release_version,
                            release_sha,
                            node_elapsed_ms,
                            execution_duration_ms,
                            error,
                          }) => ({
                            node_id,
                            definition_ref,
                            state,
                            port,
                            attempt_count,
                            release_version,
                            release_sha,
                            node_elapsed_ms,
                            execution_duration_ms,
                            error,
                          }),
                        ),
                      })),
                    },
                    null,
                    2,
                  ),
                );
              } catch {
                setError("Could not copy the execution summary.");
              }
            }}
          >
            Copy safe summary
          </button>
        </nav>
      </header>
      <section
        className="rounded-xl border bg-card px-4 py-3"
        aria-label="Pinned workflow version"
      >
        <strong className="text-sm">
          Flow version:{" "}
          {run.workflow_version?.definition_ref ||
            run.definition_ref ||
            "Unavailable"}
        </strong>
        <p className="text-xs text-muted-foreground">
          Recorded execution, not the current editable draft · application{" "}
          {run.release_version} · {run.release_sha?.slice(0, 8)}
        </p>
        {runId !== run.run_id && (
          <p className="text-xs text-violet-300">
            Showing the whole root execution, including the requested nested run{" "}
            {runId}.
          </p>
        )}
        <details>
          <summary className="cursor-pointer text-xs text-muted-foreground">
            Technical identifiers
          </summary>
          <p className="break-all font-mono text-xs">
            Root run: {run.run_id} · Checksum:{" "}
            {run.workflow_version?.checksum || "Unavailable"}
          </p>
        </details>
      </section>
      {error && (
        <p role="alert">{error} Previously loaded execution may be stale.</p>
      )}
      <WorkflowExecutionMap key={key} execution={execution} />
      <p className="text-xs text-muted-foreground">
        Analysis and verdict belong to the initiating alert. Notifications run
        only when explicitly configured. This is a read-only view of recorded
        execution; it does not replay steps or trigger tools.
      </p>
    </main>
  );
}
