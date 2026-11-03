"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { WorkflowCanvas } from "@/components/workflow-studio";
import { workflowRequest, type WorkflowRun } from "@/lib/workflows";
import { formatDurationMs } from "@/lib/duration";
import { formatLocaleDateTime } from "@/lib/datetime";
import { useAuth } from "@/lib/auth";
import { UserRole } from "@/lib/types";

type Run = WorkflowRun & { tenant_id: string; definition_ref?: string; root_run_id?: string; parent_run_id?: string;
  children?: { run_id: string; definition_ref: string; state: string }[]; tool_calls?: unknown[]; model_calls?: unknown[] };
export function WorkflowRunView({ tenantId, runId }: { tenantId: string; runId: string }) {
  const { user } = useAuth();
  const [run, setRun] = useState<Run | null>(null), [error, setError] = useState("");
  const [paused, setPaused] = useState(false), [selected, setSelected] = useState<string | null>(null);
  const [refreshedAt, setRefreshedAt] = useState(0);
  const prefix = `/tenants/${encodeURIComponent(tenantId)}/runs/${encodeURIComponent(runId)}`;
  const href = (id: string) => `/dashboard/${tenantId}/workflows/runs/${id}`;
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function refresh() {
      try {
        const value = await workflowRequest<Run>(prefix, "GET", undefined, controller.signal);
        setRun(value); setRefreshedAt(Date.now()); setError("");
        if (!paused && ["PENDING", "RUNNING"].includes(value.state)) timer = setTimeout(refresh, 5000);
      } catch (reason) { if (!controller.signal.aborted) { setError(reason instanceof Error ? reason.message : "Refresh failed"); if (!paused) timer = setTimeout(refresh, 5000); } }
    }
    refresh();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [prefix, paused]);
  async function cancel() {
    if (!confirm("Cancel this workflow and its subflows? Already dispatched external requests cannot be recalled.")) return;
    try { await workflowRequest(prefix + "/cancel", "POST"); setRun(previous => previous ? { ...previous, state: "CANCELLED" } : previous); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Cancellation failed"); }
  }
  if (!run) return <p className="p-6" role="status">{error || "Loading execution…"}</p>;
  const jobs = run.nodes || [], job = jobs.find(value => value.node_id === selected);
  const elapsed = Math.max(0, (run.completed_at ? new Date(run.completed_at).getTime() : refreshedAt) - new Date(run.created_at).getTime());
  return <main className="space-y-5 p-4 md:p-6">
    <header><h1 className="text-2xl font-semibold">Workflow execution</h1><p className="break-all font-mono text-sm">{run.definition_ref} · {run.run_id}</p>
      <p>{run.state} · elapsed {formatDurationMs(elapsed)} · ingested {formatLocaleDateTime(run.created_at)}</p>
      <p>v{run.release_version} · {run.release_sha.slice(0, 8)}</p></header>
    {error && <p role="alert">{error}</p>}
    <nav className="flex flex-wrap gap-4">
      <Link href={`/dashboard/${tenantId}/alerts/${run.alert_id}`}>Initiating alert</Link>
      {run.parent_run_id && <Link href={href(run.parent_run_id)}>↑ Parent workflow</Link>}
      {run.root_run_id && run.root_run_id !== run.run_id && <Link href={href(run.root_run_id)}>Root workflow</Link>}
      <button onClick={() => setPaused(value => !value)}>{paused ? "Resume watching" : "Pause watching"}</button>
      {user?.role === UserRole.PLATFORM_ADMIN && ["PENDING", "RUNNING"].includes(run.state) && <button onClick={cancel}>Cancel execution</button>}
      <button onClick={() => navigator.clipboard.writeText(JSON.stringify({ run_id: run.run_id, alert_id: run.alert_id, definition: run.definition_ref,
        state: run.state, version: run.release_version, sha: run.release_sha, stages: jobs.map(({ node_id, state, duration_ms, error }) => ({ node_id, state, duration_ms, error })) }, null, 2))}>Copy safe summary</button>
    </nav>
    {run.graph && <WorkflowCanvas graph={run.graph} states={Object.fromEntries(jobs.map(value => [value.node_id, value.state]))} onSelect={node => setSelected(node.id)} />}
    <section><h2 className="font-semibold">Nested playbooks and agents</h2>{run.children?.length ? run.children.map(child => <p key={child.run_id}><Link className="underline" href={href(child.run_id)}>{child.definition_ref}</Link> · {child.state}</p>) : <p>No child execution recorded.</p>}</section>
    <section><h2 className="font-semibold">Recorded steps</h2>{jobs.map(value => <details key={value.job_id} className="my-2 rounded border p-3" open={selected === value.node_id}>
      <summary>{value.node_id} · {value.state}{value.wait_reason ? ` · ${value.wait_reason}` : ""} · {value.duration_ms == null ? "not completed" : formatDurationMs(value.duration_ms)}</summary>
      <pre className="max-h-96 overflow-auto whitespace-pre-wrap text-xs">{JSON.stringify(value, null, 2)}</pre></details>)}</section>
    {job && <p role="status">Selected: {job.node_id} · {job.state}</p>}
    <details><summary>Model calls and tool delivery metadata</summary><pre className="overflow-auto whitespace-pre-wrap text-xs">{JSON.stringify({ models: run.model_calls, tools: run.tool_calls }, null, 2)}</pre></details>
    <p className="text-sm text-muted-foreground">Analysis and verdict belong to the initiating alert. External notifications run only when explicitly configured. Human-response waiting is not implemented.</p>
  </main>;
}
