"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ReactFlow, Background, Controls, Handle, Position, applyNodeChanges, applyEdgeChanges,
  type Node, type NodeProps, type Edge, type Connection } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useAuth } from "@/lib/auth";
import { UserRole } from "@/lib/types";
import { workflowRequest, outputPorts, type FlowGraph, type FlowNode } from "@/lib/workflows";

type Kind = "workflow" | "playbook" | "agent";
interface Definition { kind: Kind; code: string; name: string; description: string; enabled: boolean;
  tenant_ids: string[]; configuration: Record<string, unknown>; draft_version: number; active_revision?: number; revision?: number }
type StudioNode = Node<{ definition: FlowNode; state?: string }, "studio">;
const pretty = (value: unknown) => JSON.stringify(value, null, 2);
const blank = (kind: Kind): Record<string, unknown> => kind === "agent" ? {
  profile_code: "local-analysis", prompt: "Investigate supplied evidence only. Return supported findings and uncertainty.",
  output_schema: { type: "object" }, tools: ["alert_evidence"], max_rounds: 5, max_calls: 10, input_scope: "alert",
} : { format_version: "2.0", input_capabilities: [kind === "workflow" ? "raw" : "normalization"],
  nodes: [{ id: "entry", type: "entry", config: {}, position: { x: 0, y: 80 } },
          { id: "done", type: "complete", config: {}, position: { x: 500, y: 80 } }],
  edges: [{ id: "start", source: "entry", target: "done" }] };

function Tile({ data }: NodeProps<StudioNode>) {
  const definition = data.definition;
  const ports = [...outputPorts(definition), ...(definition.type === "tool_call" ? ["tool"] : [])];
  const subflow = ["agent", "playbook_call", "playbook_selector"].includes(definition.type);
  return <div className={`min-w-44 rounded-xl border-2 bg-card p-3 shadow-sm ${subflow ? "border-violet-500" : "border-border"}`}>
    {definition.type !== "entry" && <Handle type="target" position={Position.Left} />}
    {definition.type === "llm_tools" && <Handle id="tools" type="target" position={Position.Bottom} />}
    <div className="text-xs uppercase text-muted-foreground">{subflow ? "Subflow / agent" : definition.type.replaceAll("_", " ")}</div>
    <strong>{definition.label || definition.id}</strong>
    {typeof definition.config.definition_code === "string" && <p className="text-xs">↳ {definition.config.definition_code}</p>}
    {data.state && <p role="status" className="text-xs font-semibold">{data.state}</p>}
    {ports.map((port, i) => <Handle key={port} id={port} type="source" position={Position.Right}
      style={{ top: `${(i + 1) * 100 / (ports.length + 1)}%`, background: port === "error" ? "#dc2626" : port === "tool" ? "#9333ea" : "#2563eb" }} title={port} />)}
    <p className="text-xs text-muted-foreground">{ports.join(" · ")}</p>
  </div>;
}
const nodeTypes = { studio: Tile };

export function WorkflowCanvas({ graph, onChange, onSelect, states = {} }: {
  graph: FlowGraph; onChange?: (value: FlowGraph) => void; onSelect?: (node: FlowNode) => void; states?: Record<string, string>;
}) {
  const nodes: StudioNode[] = graph.nodes.map((definition, i) => ({ id: definition.id, type: "studio",
    data: { definition, state: states[definition.id] }, position: definition.position || { x: i * 230, y: 60 } }));
  const edges: Edge[] = graph.edges.map(edge => ({ ...edge, style: edge.sourceHandle === "tool" ? { strokeDasharray: "5 4", stroke: "#9333ea" } : undefined }));
  function connect(value: Connection) {
    if (!onChange || !value.source || !value.target) return;
    onChange({ ...graph, edges: [...graph.edges, { id: crypto.randomUUID(), source: value.source, target: value.target,
      sourceHandle: value.sourceHandle || "success", ...(value.targetHandle ? { targetHandle: value.targetHandle } : {}) }] });
  }
  return <div className="h-[550px] min-w-0 rounded-xl border bg-muted/20" aria-label="Workflow canvas">
    <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView nodesDraggable={Boolean(onChange)}
      nodesConnectable={Boolean(onChange)} edgesReconnectable={Boolean(onChange)} onConnect={connect}
      onNodeClick={(_, selected) => onSelect?.(selected.data.definition)}
      onNodesChange={changes => { if (!onChange) return; const next = applyNodeChanges(changes, nodes); const ids = new Set(next.map(n => n.id));
        onChange({ ...graph, nodes: next.map(n => ({ ...n.data.definition, position: n.position })), edges: graph.edges.filter(e => ids.has(e.source) && ids.has(e.target)) }); }}
      onEdgesChange={changes => onChange?.({ ...graph, edges: applyEdgeChanges(changes, edges).map(edge => ({
        id: edge.id, source: edge.source, target: edge.target,
        ...(edge.sourceHandle ? { sourceHandle: edge.sourceHandle } : {}),
        ...(edge.targetHandle ? { targetHandle: edge.targetHandle } : {}),
      })) })}>
      <Background /><Controls />
    </ReactFlow>
  </div>;
}

export function WorkflowStudio() {
  const { user } = useAuth();
  const [items, setItems] = useState<Definition[]>([]), [catalog, setCatalog] = useState<string[]>([]);
  const [templates, setTemplates] = useState<Definition[]>([]);
  const [kind, setKind] = useState<Kind>("workflow"), [draft, setDraft] = useState<Definition | null>(null);
  const [selected, setSelected] = useState<string | null>(null), [nodeJson, setNodeJson] = useState("{}");
  const [agentJson, setAgentJson] = useState("{}"), [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false), [nodeKind, setNodeKind] = useState("llm_analysis");
  const [versions, setVersions] = useState<Definition[]>([]), [readOnly, setReadOnly] = useState(false);
  const [breadcrumbs, setBreadcrumbs] = useState<Definition[]>([]);
  const [entryTenant, setEntryTenant] = useState(""), [jiraConnections, setJiraConnections] = useState("");
  const [credential, setCredential] = useState<{ token: string; path: string; jira_path: string } | null>(null);
  const [runTenant, setRunTenant] = useState(""), [runRows, setRunRows] = useState<{ run_id: string; alert_id: string; state: string; created_at: string }[]>([]);
  const load = useCallback(async () => { const result = await workflowRequest<{ items: Definition[]; node_types: string[]; templates: Definition[] }>("/admin/workflow-definitions"); setItems(result.items); setCatalog(result.node_types.filter(kind => !["playbook", "knowledge_base", "enrichment_action"].includes(kind))); setTemplates(result.templates || []); }, []);
  useEffect(() => { if (user?.role === UserRole.PLATFORM_ADMIN) load().catch(error => setMessage(error.message)); }, [user?.role, load]);
  function open(row: Definition, nested = false) {
    if (nested && draft) setBreadcrumbs(previous => [...previous, structuredClone(draft)]);
    else setBreadcrumbs([]);
    setKind(row.kind); setDraft(structuredClone(row)); setAgentJson(pretty(row.configuration));
    setSelected(null); setCredential(null); setVersions([]); setReadOnly(false);
    setEntryTenant(row.tenant_ids[0] || "");
  }
  async function action(operation: () => Promise<void>) { setBusy(true); setMessage(""); try { await operation(); } catch (error) { setMessage(error instanceof Error ? error.message : "Request failed"); } finally { setBusy(false); } }
  async function save() {
    if (!draft) return;
    const configuration = draft.kind === "agent" ? JSON.parse(agentJson) : draft.configuration;
    const row = await workflowRequest<Definition>(`/admin/workflow-definitions/${draft.kind}/${encodeURIComponent(draft.code)}`, "PUT", {
      name: draft.name, description: draft.description, enabled: draft.enabled, tenant_ids: draft.tenant_ids,
      configuration, expected_version: draft.draft_version });
    setDraft(row); setMessage("Draft saved. Publish to activate it for new requests."); await load();
  }
  if (user?.role !== UserRole.PLATFORM_ADMIN) return <p className="p-6">Workflow management requires platform administrator access.</p>;
  const graph = draft?.kind !== "agent" && draft?.configuration.nodes ? draft.configuration as unknown as FlowGraph : null;
  const saved = items.find(row => row.kind === draft?.kind && row.code === draft?.code);
  const unsaved = Boolean(draft && (!saved || pretty({ ...draft, configuration: draft.kind === "agent" ? agentJson : draft.configuration }) !== pretty({ ...saved, configuration: saved.kind === "agent" ? pretty(saved.configuration) : saved.configuration })));
  const field = "rounded border bg-background p-2 text-sm";
  return <main className="space-y-5 p-4 md:p-6">
    <header><h1 className="text-2xl font-semibold">Workflow Studio</h1><p className="text-sm text-muted-foreground">Shared workflows, nested playbooks and bounded agents. Publishing activates the revision for new runs; existing runs remain pinned.</p></header>
    <nav className="flex flex-wrap gap-3" aria-label="Definition libraries">{(["workflow", "playbook", "agent"] as Kind[]).map(value => <button key={value} className={field} aria-pressed={kind === value} onClick={() => setKind(value)}>{value}s</button>)}
      <Link className={field} href="/dashboard/admin/settings/connectors">REST / MCP tools</Link><Link className={field} href="/dashboard/admin/settings/llm-profiles">Model profiles</Link></nav>
    {message && <p role="status" className="rounded border p-3">{message}</p>}
    <div className="grid gap-4 lg:grid-cols-[240px_minmax(0,1fr)]">
      <aside className="space-y-2"><button className={field} onClick={() => open({ kind, code: "", name: "", description: "", tenant_ids: [], enabled: true, configuration: blank(kind), draft_version: 0 })}>New {kind}</button>
        <details><summary>Editable templates</summary>{templates.filter(row => row.kind === kind).map(row => <button key={row.code} className="block rounded border p-2 text-left text-sm" onClick={() => open({ ...row, draft_version: 0, tenant_ids: [], enabled: true })}>{row.name}</button>)}</details>
        {items.filter(row => row.kind === kind).map(row => <button key={row.code} className="block w-full rounded border p-3 text-left" onClick={() => open(row)}><strong>{row.name}</strong><span className="block text-xs">{row.code} · active {row.active_revision || "unpublished"}</span></button>)}
      </aside>
      {draft && <section className="min-w-0 space-y-3">
        <nav aria-label="Subflow breadcrumbs" className="flex gap-2">{breadcrumbs.map((row, index) => <button key={index} className="underline" onClick={() => { open(row); setBreadcrumbs(breadcrumbs.slice(0, index)); }}>{row.name} →</button>)}<span>{draft.name || "New definition"}</span></nav>
        <div className="grid gap-2 md:grid-cols-2"><label>Immutable code<input className={`${field} block w-full`} value={draft.code} disabled={readOnly || draft.draft_version > 0} onChange={event => setDraft({ ...draft, code: event.target.value })} /></label>
          <label>Name<input className={`${field} block w-full`} value={draft.name} disabled={readOnly} onChange={event => setDraft({ ...draft, name: event.target.value })} /></label>
          <label>Authorized tenant IDs (comma-separated)<input className={`${field} block w-full`} value={draft.tenant_ids.join(",")} disabled={readOnly} onChange={event => setDraft({ ...draft, tenant_ids: event.target.value.split(",").map(s => s.trim()).filter(Boolean) })} /></label>
          <label>Description<input className={`${field} block w-full`} value={draft.description} disabled={readOnly} onChange={event => setDraft({ ...draft, description: event.target.value })} /></label></div>
        <label><input type="checkbox" checked={draft.enabled} disabled={readOnly} onChange={event => setDraft({ ...draft, enabled: event.target.checked })} /> Enabled (revocation takes effect immediately when saved)</label>
        {graph ? <><div className="flex flex-wrap gap-2"><select aria-label="Node type" className={field} value={nodeKind} disabled={readOnly} onChange={e => setNodeKind(e.target.value)}>{catalog.map(value => <option key={value}>{value}</option>)}</select>
          <button className={field} disabled={readOnly} onClick={() => { const id = `${nodeKind}-${crypto.randomUUID().slice(0, 8)}`; setDraft({ ...draft, configuration: { ...graph, nodes: [...graph.nodes, { id, type: nodeKind, config: {}, position: { x: graph.nodes.length * 100, y: 250 } }] } }); }}>Add node</button></div>
          <WorkflowCanvas graph={graph} onChange={readOnly ? undefined : value => setDraft({ ...draft, configuration: value as unknown as Record<string, unknown> })}
            onSelect={value => { setSelected(value.id); setNodeJson(pretty(value.config)); }} />
          {selected && <div className="space-y-2 rounded border p-3"><h3 className="font-semibold">{selected} configuration</h3><p className="text-xs">Configure registered codes and typed inputs; never paste credentials here.</p>
            <textarea className={`${field} min-h-40 w-full font-mono`} aria-label="Node configuration" value={nodeJson} readOnly={readOnly} onChange={event => setNodeJson(event.target.value)} />
            <button className={field} disabled={readOnly} onClick={() => { try { const config = JSON.parse(nodeJson); setDraft({ ...draft, configuration: { ...graph, nodes: graph.nodes.map(n => n.id === selected ? { ...n, config } : n) } }); setMessage("Node configuration applied to draft."); } catch { setMessage("Node configuration must be valid JSON."); } }}>Apply node settings</button>
            {(() => { const n = graph.nodes.find(n => n.id === selected); const code = n?.config.definition_code; const target = items.find(row => row.code === code && row.kind === (n?.type === "agent" ? "agent" : "playbook")); return target && <button className={`${field} ml-2`} onClick={() => open(target, true)}>Open {target.kind} subflow</button>; })()}</div>}
          <details><summary>Whole graph JSON / import</summary><textarea className={`${field} min-h-64 w-full font-mono`} aria-label="Graph JSON" defaultValue={pretty(graph)} key={`${draft.code}:${draft.draft_version}:${readOnly}`} readOnly={readOnly}
            onBlur={event => { if (readOnly) return; try { setDraft({ ...draft, configuration: JSON.parse(event.target.value) }); } catch { setMessage("Invalid graph JSON; current graph was preserved."); } }} /></details>
        </> : <label>Agent configuration (prompt, model profile, schemas, tool allowlist and budgets)<textarea aria-label="Agent configuration" className={`${field} block min-h-96 w-full font-mono`} value={agentJson} readOnly={readOnly} onChange={event => setAgentJson(event.target.value)} /></label>}
        <div className="flex flex-wrap gap-2"><button className={field} disabled={busy || readOnly} onClick={() => action(save)}>Save draft</button>
          <button className={field} disabled={busy || readOnly || !draft.draft_version || unsaved} onClick={() => action(async () => { const result = await workflowRequest<{ revision: number }>(`/admin/workflow-definitions/${draft.kind}/${draft.code}/publish`, "POST"); setDraft({ ...draft, active_revision: result.revision }); setMessage("Published and activated for new runs."); await load(); })}>Publish and activate</button>
          <button className={field} disabled={busy || !draft.draft_version} onClick={() => action(async () => { const result = await workflowRequest<{ items: Definition[] }>(`/admin/workflow-definitions/${draft.kind}/${draft.code}/revisions`); setVersions(result.items); })}>Version history</button>
          <button className={field} disabled={busy || !draft.draft_version} onClick={() => { if (confirm("Delete this definition? New calls will be rejected; historical runs remain.")) action(async () => { await workflowRequest(`/admin/workflow-definitions/${draft.kind}/${draft.code}`, "DELETE"); setDraft(null); await load(); }); }}>Delete</button></div>
        {versions.map(row => <button key={row.revision} className={`${field} mr-2`} onClick={() => { setDraft({ ...row, draft_version: row.revision! }); setAgentJson(pretty(row.configuration)); setReadOnly(true); }}>Inspect immutable revision {row.revision}</button>)}
        {readOnly && <p>Historical revision — read only. Open the definition from the library to edit its current draft.</p>}
        {draft.kind === "workflow" && draft.active_revision && <section className="space-y-2 rounded border p-4"><h2 className="font-semibold">Workflow entry</h2>
          <label>Tenant<select className={`${field} ml-2`} value={entryTenant} onChange={event => { setEntryTenant(event.target.value); setCredential(null); }}>{draft.tenant_ids.map(id => <option key={id}>{id}</option>)}</select></label>
          <label className="block">Allowed Jira connection IDs (comma-separated)<input className={`${field} ml-2`} value={jiraConnections} onChange={event => setJiraConnections(event.target.value)} /></label>
          <button className={field} disabled={busy || !entryTenant} onClick={() => action(async () => { setCredential(await workflowRequest(`/admin/workflow-definitions/workflow/${draft.code}/entry-credentials`, "POST", { tenant_id: entryTenant, jira_connection_ids: jiraConnections.split(",").map(s => s.trim()).filter(Boolean) })); })}>Generate / rotate entry credential</button>
          {credential && <div className="space-y-2"><p>Copy once. Kept in page memory only; rotation immediately invalidates the previous token.</p><code className="block break-all">{credential.token}</code><button className={field} onClick={() => navigator.clipboard.writeText(credential.token)}>Copy token</button><p>REST: <code>{credential.path}</code></p><p>Jira workflow URL: <code>{credential.jira_path}</code></p><button className={field} onClick={() => setCredential(null)}>Hide credential</button></div>}
        </section>}
      </section>}
    </div>
    <section className="space-y-2 rounded border p-4"><h2 className="font-semibold">Execution history</h2><label>Tenant ID<input className={`${field} ml-2`} value={runTenant} onChange={event => setRunTenant(event.target.value)} /></label>
      <button className={`${field} ml-2`} disabled={busy || !runTenant} onClick={() => action(async () => { const rows = await workflowRequest<{ items: typeof runRows }>(`/tenants/${encodeURIComponent(runTenant)}/runs`); setRunRows(rows.items); })}>Load runs</button>
      {runRows.map(row => <Link className="block rounded border p-2" key={row.run_id} href={`/dashboard/admin/workflows/runs/${encodeURIComponent(runTenant)}/${row.run_id}`}>{row.alert_id} · {row.state} · {new Date(row.created_at).toLocaleString()}</Link>)}
    </section>
  </main>;
}
