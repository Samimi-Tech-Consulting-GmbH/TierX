"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { listWorkflowDebugExecutions } from "@/lib/api";
import { workflowRequest } from "@/lib/workflows";
import type { WorkflowExecutionPage } from "@/lib/workflow-debug-index";
import { executionDebugHref } from "@/lib/execution-navigation";
import { formatLocaleDateTime } from "@/lib/datetime";
import { TablePaginationFooter } from "@/components/dashboard/pagination";

const CONTROL = "h-10 rounded-md border bg-background px-3 text-sm";
export function WorkflowExecutionIndex({ tenantId, platformAdmin = false }: { tenantId?: string; platformAdmin?: boolean }) {
  const [search, setSearch] = useState("");
  const [filters, setFilters] = useState({ q: "", state: "", since: "", page: 0, size: 25 });
  const [refresh, setRefresh] = useState(0);
  const [result, setResult] = useState<{ key: string; data?: WorkflowExecutionPage; error?: string }>();
  useEffect(() => {
    const timer = setTimeout(() => setFilters(value => value.q === search.trim() ? value : ({ ...value, q: search.trim(), page: 0 })), 250);
    return () => clearTimeout(timer);
  }, [search]);
  const params = new URLSearchParams({ skip: String(filters.page * filters.size), limit: String(filters.size) });
  if (platformAdmin && tenantId) params.set("tenant_id", tenantId);
  if (filters.q) params.set("q", filters.q);
  if (filters.state) params.set("state", filters.state);
  if (filters.since) params.set("since_hours", filters.since);
  const query = params.toString();
  const key = `${platformAdmin}:${tenantId}:${query}:${refresh}`;
  useEffect(() => {
    const controller = new AbortController();
    const request = platformAdmin
      ? listWorkflowDebugExecutions(query, controller.signal)
      : workflowRequest<WorkflowExecutionPage>(`/tenants/${encodeURIComponent(tenantId || "")}/debug/executions?${query}`, "GET", undefined, controller.signal);
    request.then(data => {
      if (!controller.signal.aborted) setResult({ key, data });
    }).catch(() => {
      if (!controller.signal.aborted) setResult({ key, error: "Executions could not be loaded. Refresh to try again." });
    });
    return () => controller.abort();
  }, [key, platformAdmin, query, tenantId]);
  const current = result?.key === key ? result : undefined;
  const data = current?.data;
  return <main className="space-y-6">
    <header className="flex flex-wrap items-start justify-between gap-4">
      <div><h1 className="text-3xl font-bold tracking-tight">Debug</h1>
        <p className="mt-2 text-sm text-muted-foreground">Recorded workflow executions, newest first. Open one to inspect every node and nested playbook, agent and tool call.</p></div>
      <button type="button" className={CONTROL} onClick={() => setRefresh(value => value + 1)} disabled={!current}>Refresh</button>
    </header>
    <div className="flex flex-wrap items-end gap-3">
      <label className="flex min-w-64 flex-1 flex-col gap-1 text-sm">Search alerts, runs or workflows
        <input className={CONTROL} value={search} onChange={event => setSearch(event.target.value)} placeholder="Alert ID, run ID or workflow" /></label>
      <label className="flex flex-col gap-1 text-sm">Status
        <select className={CONTROL} value={filters.state} onChange={event => setFilters(value => ({ ...value, state: event.target.value, page: 0 }))}>
          <option value="">All statuses</option>{["PENDING", "RUNNING", "SUCCEEDED", "SUCCEEDED_WITH_WARNINGS", "FAILED", "CANCELLED"].map(state => <option key={state}>{state}</option>)}
        </select></label>
      <label className="flex flex-col gap-1 text-sm">Time range
        <select className={CONTROL} value={filters.since} onChange={event => setFilters(value => ({ ...value, since: event.target.value, page: 0 }))}>
          <option value="">All retained executions</option><option value="24">Last 24 hours</option><option value="168">Last 7 days</option><option value="720">Last 30 days</option>
        </select></label>
    </div>
    {!current ? <p role="status">Loading executions…</p> : current.error ? <p role="alert">{current.error}</p> : data && <>
      <p className="text-sm text-muted-foreground">{data.total} workflow executions · one row per root run; nested runs are shown inside it.</p>
      {data.items.length === 0 ? <p>{filters.q || filters.state || filters.since ? "No executions match these filters." : "No recorded workflow executions yet."}</p> : <div className="overflow-x-auto rounded-xl border">
        <table className="w-full text-left text-sm"><thead className="border-b bg-muted/30"><tr>{["Alert / execution", ...(platformAdmin ? ["Tenant"] : []), "Workflow version", "Status", "Started", "Application release"].map(label => <th key={label} className="p-4 font-medium">{label}</th>)}</tr></thead>
          <tbody>{data.items.map(run => <tr key={`${run.tenant_id}:${run.run_id}`} className="border-b last:border-0 hover:bg-muted/20">
            <td className="p-4"><Link className="font-mono text-xs text-primary underline-offset-4 hover:underline" href={executionDebugHref(run.tenant_id, run.run_id, platformAdmin)}>{run.alert_id || run.run_id}</Link><div className="mt-1 text-xs text-muted-foreground">{run.alert_type || "Workflow execution"} · {run.run_id}</div></td>
            {platformAdmin && <td className="p-4">{run.tenant_name}</td>}
            <td className="p-4">{run.definition_ref || run.definition_code || "—"}{!run.definition_ref && run.revision !== undefined && ` · v${run.revision}`}</td>
            <td className="p-4">{run.state.replaceAll("_", " ")}</td>
            <td className="whitespace-nowrap p-4">{run.created_at ? formatLocaleDateTime(run.created_at) : "—"}</td>
            <td className="p-4">{run.release_version || "Not recorded"}<div className="font-mono text-xs text-muted-foreground">{run.release_sha?.slice(0, 12)}</div></td>
          </tr>)}</tbody></table>
      </div>}
      <TablePaginationFooter page={filters.page} pageSize={filters.size} total={data.total} onPageChange={page => setFilters(value => ({ ...value, page }))} onPageSizeChange={size => setFilters(value => ({ ...value, size, page: 0 }))} />
    </>}
    {platformAdmin && <Link className="inline-block text-sm text-muted-foreground underline" href="/dashboard/admin/debug/history">Historical processing traces (pre-workflow)</Link>}
  </main>;
}
