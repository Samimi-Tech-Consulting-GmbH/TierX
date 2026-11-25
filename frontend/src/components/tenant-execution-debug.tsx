"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { workflowRequest, type WorkflowRun } from "@/lib/workflows";
import { executionDebugHref } from "@/lib/execution-navigation";

export function TenantExecutionDebug({ tenantId }: { tenantId: string }) {
  const [runs, setRuns] = useState<WorkflowRun[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    workflowRequest<{ items: WorkflowRun[] }>(
      `/tenants/${encodeURIComponent(tenantId)}/runs?limit=25`,
      "GET",
      undefined,
      controller.signal,
    )
      .then((value) => {
        if (!controller.signal.aborted) setRuns(value.items);
      })
      .catch(() => {
        if (!controller.signal.aborted)
          setError("Executions could not be loaded.");
      });
    return () => controller.abort();
  }, [tenantId]);
  return (
    <main className="space-y-4 p-6">
      <h1 className="text-2xl font-semibold">Debug</h1>
      <p className="text-sm text-muted-foreground">
        Inspect the 25 most recent executions and their nested steps. This does
        not replay or change a workflow.
      </p>
      {error ? (
        <p role="alert">{error}</p>
      ) : runs === null ? (
        <p role="status">Loading executions…</p>
      ) : runs.length === 0 ? (
        <p>No recorded executions yet.</p>
      ) : (
        <ul className="space-y-2">
          {runs.map((run) => (
            <li key={run.run_id}>
              <Link
                className="flex flex-wrap gap-3 rounded-xl border p-4 hover:border-primary"
                href={executionDebugHref(tenantId, run.run_id)}
              >
                <span className="flex-1 font-mono text-xs">{run.run_id}</span>
                <span>{run.state}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
