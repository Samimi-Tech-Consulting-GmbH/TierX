"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  Background,
  Controls,
  Handle,
  Position,
  ReactFlow,
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
  type Node,
  type Edge,
  type NodeProps,
  type NodeChange,
  type EdgeChange,
  type Connection,
  type ReactFlowInstance,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useAuth } from "@/lib/auth";
import { UserRole } from "@/lib/types";
import { formatDurationMs } from "@/lib/duration";
import {
  outputPorts,
  workflowRequest,
  type FlowDraft,
  type FlowGraph,
  type FlowNode,
  type WorkflowRun,
} from "@/lib/workflows";

type CanvasNode = Node<{ definition: FlowNode; state?: string }, "workflow">;
function WorkflowNode({ data }: NodeProps<CanvasNode>) {
  const node = data.definition;
  return (
    <div className="min-w-44 rounded border border-input bg-card p-3 text-card-foreground shadow">
      {node.type !== "entry" && (
        <Handle type="target" position={Position.Left} />
      )}
      <strong>{node.label || node.type.replaceAll("_", " ")}</strong>
      <p className="text-xs text-muted-foreground">{node.id}</p>
      {data.state && (
        <p className="text-xs font-semibold" role="status">
          {data.state}
        </p>
      )}
      {outputPorts(node).map((port, i, ports) => (
        <Handle
          key={port}
          id={port}
          type="source"
          position={Position.Right}
          style={{
            top: `${((i + 1) * 100) / (ports.length + 1)}%`,
            background: port === "error" ? "#dc2626" : "#2563eb",
          }}
          title={port}
        />
      ))}
      <p className="mt-1 text-xs">{outputPorts(node).join(" · ")}</p>
    </div>
  );
}
const nodeTypes = { workflow: WorkflowNode };
function canvas(graph: FlowGraph): CanvasNode[] {
  return graph.nodes.map((n) => ({
    id: n.id,
    type: "workflow",
    data: { definition: n },
    position: n.position || { x: 0, y: 0 },
  }));
}

export function WorkflowBuilder({ tenantId }: { tenantId: string }) {
  const { user } = useAuth();
  const [wideCanvas, setWideCanvas] = useState(false);
  const canManage =
    user?.role === UserRole.PLATFORM_ADMIN ||
    user?.role === UserRole.TENANT_ADMIN;
  const prefix = `/tenants/${encodeURIComponent(tenantId)}`;
  const [flows, setFlows] = useState<FlowDraft[]>([]),
    [draft, setDraft] = useState<FlowDraft | null>(null);
  const [nodes, setNodes] = useState<CanvasNode[]>([]),
    [edges, setEdges] = useState<Edge[]>([]);
  const [catalog, setCatalog] = useState<string[]>([]),
    [template, setTemplate] = useState<FlowGraph | null>(null);
  const [templates, setTemplates] = useState<
    { name: string; graph: FlowGraph }[]
  >([]);
  const [templateName, setTemplateName] = useState("Parity pipeline");
  const [profiles, setProfiles] = useState<
    { profile_code: string; model: string }[]
  >([]);
  const [bindingSource, setBindingSource] = useState("");
  const [bindingType, setBindingType] = useState("");
  const flowInstance = useRef<ReactFlowInstance<CanvasNode, Edge> | null>(null);
  const [selected, setSelected] = useState<string | null>(null),
    [config, setConfig] = useState("{}");
  const [name, setName] = useState("Experimental workflow"),
    [kind, setKind] = useState("decision");
  const [message, setMessage] = useState(""),
    [busy, setBusy] = useState(false);
  const [runs, setRuns] = useState<WorkflowRun[]>([]),
    [watchId, setWatchId] = useState<string | null>(null),
    [run, setRun] = useState<WorkflowRun | null>(null);
  const [refreshedAt, setRefreshedAt] = useState(0);
  const editable = canManage && !run && !watchId;
  const [payload, setPayload] = useState(
    JSON.stringify(
      {
        alert_type: "splunk.notable.endpoint_malware",
        source_system: "SPLUNK",
        raw_payload: {
          result: {
            host: "example-endpoint",
            src: "192.0.2.10",
            severity: "5",
            rule_id: "v2-example",
            _time: new Date().toISOString(),
          },
        },
      },
      null,
      2,
    ),
  );
  const load = useCallback(async () => {
    const [items, registry, history, availableProfiles] = await Promise.all([
      workflowRequest<{ items: FlowDraft[] }>(`${prefix}/flows`),
      workflowRequest<{
        node_types: string[];
        default_graph: FlowGraph;
        examples?: { name: string; graph: FlowGraph }[];
      }>(`${prefix}/workflow-catalog`),
      workflowRequest<{ items: WorkflowRun[] }>(`${prefix}/runs`),
      workflowRequest<{ items: { profile_code: string; model: string }[] }>(
        `${prefix}/llm-profiles`,
      ),
    ]);
    setFlows(items.items);
    setCatalog(registry.node_types);
    setTemplate(registry.default_graph);
    setTemplates(
      registry.examples || [
        { name: "Parity pipeline", graph: registry.default_graph },
      ],
    );
    setProfiles(availableProfiles.items || []);
    setRuns(history.items);
  }, [prefix]);
  useEffect(() => {
    let active = true;
    load().catch((error) => {
      if (active) setMessage(error.message);
    });
    return () => {
      active = false;
    };
  }, [load]);
  useEffect(() => {
    if (!watchId) return;
    const controller = new AbortController();
    let polling = true;
    const refresh = async () => {
      try {
        const result = await workflowRequest<WorkflowRun>(
          `${prefix}/runs/${watchId}`,
          "GET",
          undefined,
          controller.signal,
        );
        if (polling) {
          setRun(result);
          setDraft(null);
          setRefreshedAt(Date.now());
          if (result.graph) {
            setNodes(canvas(result.graph));
            setEdges(result.graph.edges);
          }
          if (
            [
              "SUCCEEDED",
              "SUCCEEDED_WITH_WARNINGS",
              "FAILED",
              "CANCELLED",
            ].includes(result.state)
          )
            setWatchId(null);
        }
      } catch (error) {
        if (polling && !controller.signal.aborted)
          setMessage(error instanceof Error ? error.message : "Refresh failed");
      }
    };
    void refresh();
    const timer = setInterval(() => void refresh(), 5000);
    return () => {
      polling = false;
      controller.abort();
      clearInterval(timer);
    };
  }, [prefix, watchId]);
  const graph = (): FlowGraph => ({
    format_version: "1.0",
    nodes: nodes.map((n) => ({ ...n.data.definition, position: n.position })),
    edges: edges.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      sourceHandle: e.sourceHandle || "success",
    })),
    viewport: flowInstance.current?.getViewport(),
  });
  function open(flow: FlowDraft) {
    setDraft(flow);
    setName(flow.name);
    setNodes(canvas(flow.graph));
    setEdges(flow.graph.edges);
    if (flow.graph.viewport)
      void flowInstance.current?.setViewport(flow.graph.viewport);
    else void flowInstance.current?.fitView();
    setSelected(null);
    setRun(null);
    setWatchId(null);
  }
  async function action(task: () => Promise<void>) {
    setBusy(true);
    setMessage("");
    try {
      await task();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Operation failed");
    } finally {
      setBusy(false);
    }
  }
  async function save() {
    const result = await workflowRequest<FlowDraft>(
      draft ? `${prefix}/flows/${draft.flow_id}` : `${prefix}/flows`,
      draft ? "PUT" : "POST",
      {
        name,
        graph: graph(),
        ...(draft ? { expected_version: draft.draft_version } : {}),
      },
    );
    open(result);
    await load();
    setMessage("Draft saved. Publish separately to use an ingestion binding.");
    return result;
  }
  function addNode() {
    const id = `${kind}-${crypto.randomUUID().slice(0, 8)}`;
    const initial =
      kind === "decision"
        ? { path: "alert.normalized_payload.source.ip", operator: "exists" }
        : kind === "fork"
          ? { branches: ["first", "second"], join_id: "" }
          : kind === "join"
            ? { fork_id: "" }
            : kind.startsWith("llm_")
              ? { profile_code: "local-analysis" }
              : {};
    setNodes((current) => [
      ...current,
      {
        id,
        type: "workflow",
        position: { x: 100, y: 200 },
        data: { definition: { id, type: kind, config: initial } },
      },
    ]);
  }
  const visible: CanvasNode[] = nodes.map((n) => ({
    ...n,
    data: {
      ...n.data,
      state: run?.nodes?.filter((j) => j.node_id === n.id).at(-1)?.state,
    },
  }));
  return (
    <main className="space-y-4 p-4">
      <header>
        <h1 className="text-2xl font-bold">Ingestion V2 · Experimental</h1>
        <p className="text-sm text-muted-foreground">
          Isolated alert workflows. Existing ingestion is unchanged. LLM outputs
          are not guaranteed deterministic.
        </p>
      </header>
      {message && (
        <p role="status" className="rounded border p-3">
          {message}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <select
          aria-label="Select workflow"
          className="rounded border bg-background p-2"
          value={draft?.flow_id || ""}
          onChange={(e) => {
            const flow = flows.find((f) => f.flow_id === e.target.value);
            if (flow) open(flow);
          }}
        >
          <option value="">Select workflow</option>
          {flows.map((f) => (
            <option key={f.flow_id} value={f.flow_id}>
              {f.name} · draft {f.draft_version}
            </option>
          ))}
        </select>
        {editable && (
          <>
            <select
              aria-label="Workflow template"
              className="rounded border bg-background p-2"
              value={templateName}
              onChange={(e) => setTemplateName(e.target.value)}
            >
              {templates.map((t) => (
                <option key={t.name}>{t.name}</option>
              ))}
            </select>
            <button
              className="rounded border p-2"
              onClick={() => {
                const chosen =
                  templates.find((t) => t.name === templateName)?.graph ||
                  template;
                if (chosen) {
                  setDraft(null);
                  setName(templateName);
                  setNodes(canvas(chosen));
                  setEdges(chosen.edges);
                  setSelected(null);
                  setRun(null);
                  setWatchId(null);
                }
              }}
            >
              New from template
            </button>
            <input
              aria-label="Workflow name"
              className="rounded border bg-background p-2"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            <button
              disabled={busy || !nodes.length}
              className="rounded border p-2"
              onClick={() =>
                void action(async () => {
                  await save();
                })
              }
            >
              Save draft
            </button>
            <button
              disabled={busy || !nodes.length}
              className="rounded border p-2"
              onClick={() =>
                void action(async () => {
                  await workflowRequest(`${prefix}/flows/validate`, "POST", {
                    graph: graph(),
                  });
                  setMessage("Graph and resource validation passed.");
                })
              }
            >
              Validate
            </button>
            <button
              disabled={busy || !draft}
              className="rounded border p-2"
              onClick={() =>
                void action(async () => {
                  const saved = await save();
                  await workflowRequest(
                    `${prefix}/flows/${saved.flow_id}/publish`,
                    "POST",
                  );
                  setMessage(
                    `Published immutable revision ${saved.draft_version}.`,
                  );
                })
              }
            >
              Publish revision
            </button>
            <button
              disabled={busy || !draft}
              className="rounded border p-2"
              onClick={() =>
                void action(async () => {
                  if (!draft) return;
                  await workflowRequest(`${prefix}/flow-bindings`, "PUT", {
                    flow_id: draft.flow_id,
                    revision: draft.draft_version,
                  });
                  setMessage("Default V2 binding selected. V1 is unaffected.");
                })
              }
            >
              Set default binding
            </button>
            <button
              className="rounded border p-2"
              onClick={() => {
                const blob = new Blob(
                  [JSON.stringify({ name, graph: graph() }, null, 2)],
                  { type: "application/json" },
                );
                const url = URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = url;
                a.download = "workflow.tierx-flow.json";
                a.click();
                URL.revokeObjectURL(url);
              }}
            >
              Export JSON
            </button>
            <label className="rounded border p-2">
              Import JSON
              <input
                className="sr-only"
                type="file"
                accept=".json"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (!file) return;
                  void action(async () => {
                    if (file.size > 1024 * 1024)
                      throw new Error("Import exceeds 1 MiB");
                    const data = JSON.parse(await file.text());
                    const result = await workflowRequest<FlowDraft>(
                      `${prefix}/flows/import`,
                      "POST",
                      data,
                    );
                    open(result);
                    await load();
                    setMessage(
                      "Imported as a draft; validate resources before publication.",
                    );
                  });
                  e.target.value = "";
                }}
              />
            </label>
            {user?.role === UserRole.PLATFORM_ADMIN && (
              <Link
                className="rounded border p-2"
                href="/dashboard/admin/settings/llm-profiles"
              >
                LLM profiles
              </Link>
            )}
          </>
        )}
      </div>
      {run && (
        <p className="rounded border p-2 text-sm">
          Read-only execution snapshot. Select a workflow above to return to
          draft editing.
        </p>
      )}
      {editable && draft && (
        <section className="flex flex-wrap items-center gap-2 rounded border p-3">
          <span>Exact binding override:</span>
          <input
            aria-label="Binding source system"
            placeholder="SPLUNK"
            className="rounded border bg-background p-2"
            value={bindingSource}
            onChange={(e) => setBindingSource(e.target.value)}
          />
          <input
            aria-label="Binding alert type"
            placeholder="Alert type"
            className="rounded border bg-background p-2"
            value={bindingType}
            onChange={(e) => setBindingType(e.target.value)}
          />
          <button
            disabled={busy || !bindingSource.trim() || !bindingType.trim()}
            className="rounded border p-2"
            onClick={() =>
              void action(async () => {
                await workflowRequest(`${prefix}/flow-bindings`, "PUT", {
                  flow_id: draft.flow_id,
                  revision: draft.draft_version,
                  source_system: bindingSource.trim(),
                  alert_type: bindingType.trim(),
                });
                setMessage(
                  "Exact override saved for this published revision; it takes precedence over the default binding.",
                );
              })
            }
          >
            Set exact override
          </button>
        </section>
      )}
      <button
        className="rounded border p-2"
        onClick={() => setWideCanvas((value) => !value)}
      >
        {wideCanvas ? "Show configuration beside canvas" : "Expand canvas"}
      </button>
      <div
        className={
          wideCanvas ? "grid gap-4" : "grid gap-4 lg:grid-cols-[1fr_320px]"
        }
      >
        <div className="h-[560px] rounded border" aria-label="Workflow canvas">
          <ReactFlow<CanvasNode, Edge>
            nodes={visible}
            edges={edges}
            nodeTypes={nodeTypes}
            onInit={(instance) => {
              flowInstance.current = instance;
            }}
            fitView
            minZoom={0.1}
            colorMode="dark"
            nodesDraggable={editable}
            nodesConnectable={editable}
            onNodesChange={(changes: NodeChange<CanvasNode>[]) =>
              setNodes((current) => applyNodeChanges(changes, current))
            }
            onEdgesChange={(changes: EdgeChange[]) =>
              setEdges((current) => applyEdgeChanges(changes, current))
            }
            onConnect={(connection: Connection) => {
              if (editable) setEdges((current) => addEdge(connection, current));
            }}
            onNodeClick={(_, n) => {
              setSelected(n.id);
              setConfig(JSON.stringify(n.data.definition.config, null, 2));
            }}
            deleteKeyCode={editable ? "Delete" : null}
          >
            <Background />
            <Controls />
          </ReactFlow>
        </div>
        <aside className="space-y-3 rounded border p-3">
          <h2 className="font-semibold">Node configuration</h2>
          {editable && (
            <div className="flex gap-2">
              <select
                aria-label="Node type"
                className="w-full rounded border bg-background"
                value={kind}
                onChange={(e) => setKind(e.target.value)}
              >
                {catalog.map((k) => (
                  <option key={k}>{k}</option>
                ))}
              </select>
              <button className="rounded border p-2" onClick={addNode}>
                Add
              </button>
            </div>
          )}
          {selected ? (
            <>
              <p>{selected}</p>
              {editable &&
                nodes
                  .find((n) => n.id === selected)
                  ?.data.definition.type.startsWith("llm_") && (
                  <select
                    aria-label="LLM profile for selected node"
                    className="w-full rounded border bg-background p-2"
                    defaultValue=""
                    onChange={(e) => {
                      try {
                        setConfig(
                          JSON.stringify(
                            {
                              ...JSON.parse(config),
                              profile_code: e.target.value,
                            },
                            null,
                            2,
                          ),
                        );
                      } catch {
                        setMessage(
                          "Fix the configuration JSON before selecting a profile.",
                        );
                      }
                    }}
                  >
                    <option value="" disabled>
                      Select an authorized profile
                    </option>
                    {profiles.map((p) => (
                      <option key={p.profile_code} value={p.profile_code}>
                        {p.profile_code} · {p.model}
                      </option>
                    ))}
                  </select>
                )}
              <textarea
                aria-label="Node configuration JSON"
                className="h-72 w-full rounded border bg-background p-2 font-mono text-xs"
                readOnly={!editable}
                value={config}
                onChange={(e) => setConfig(e.target.value)}
              />
              {editable && (
                <button
                  className="rounded border p-2"
                  onClick={() => {
                    try {
                      const value = JSON.parse(config);
                      if (
                        !value ||
                        Array.isArray(value) ||
                        typeof value !== "object"
                      )
                        throw new Error("Object required");
                      setNodes((current) =>
                        current.map((n) =>
                          n.id === selected
                            ? {
                                ...n,
                                data: {
                                  ...n.data,
                                  definition: {
                                    ...n.data.definition,
                                    config: value,
                                  },
                                },
                              }
                            : n,
                        ),
                      );
                      setMessage(
                        "Node configuration applied locally; save and validate the draft.",
                      );
                    } catch {
                      setMessage("Configuration must be a JSON object.");
                    }
                  }}
                >
                  Apply configuration
                </button>
              )}
            </>
          ) : (
            <p>
              Select a node. Red handles are failure/catch routes. Fork handles
              use configured branch names.
            </p>
          )}
        </aside>
      </div>
      {editable && (
        <section className="space-y-2 rounded border p-4">
          <h2 className="font-semibold">Test the saved draft</h2>
          <textarea
            aria-label="Test alert JSON"
            className="h-48 w-full rounded border bg-background p-2 font-mono text-xs"
            value={payload}
            onChange={(e) => setPayload(e.target.value)}
          />
          <button
            disabled={busy || !draft}
            className="rounded bg-primary p-2 text-primary-foreground"
            onClick={() =>
              void action(async () => {
                if (!draft) return;
                const accepted = await workflowRequest<WorkflowRun>(
                  `${prefix}/ingest`,
                  "POST",
                  {
                    ...JSON.parse(payload),
                    flow_id: draft.flow_id,
                    draft_version: draft.draft_version,
                  },
                );
                setWatchId(accepted.run_id);
                setRun(null);
                setMessage(
                  `Queued ${accepted.alert_id}. Processing continues independently.`,
                );
                await load();
              })
            }
          >
            Submit alert
          </button>
        </section>
      )}
      <section className="rounded border p-4">
        <h2 className="font-semibold">Execution history</h2>
        <button
          className="my-2 rounded border p-2"
          onClick={() => void action(load)}
        >
          Refresh history
        </button>
        <div className="flex flex-wrap gap-2">
          {runs.map((r) => (
            <button
              key={r.run_id}
              className="rounded border p-2 text-left text-xs"
              onClick={() => {
                setWatchId(r.run_id);
                setRun(null);
              }}
            >
              {r.alert_id}
              <br />
              {r.state} · {new Date(r.created_at).toLocaleString()}
            </button>
          ))}
        </div>
        {run && (
          <div className="mt-3 space-y-2">
            <p>
              {run.alert_id} · {run.state} · v{run.release_version} ·{" "}
              {run.release_sha.slice(0, 7)} ·{" "}
              {watchId ? "Watching every 5 seconds" : "Watching stopped"}
            </p>
            <p>
              Wall-clock elapsed:{" "}
              {formatDurationMs(
                (run.completed_at
                  ? new Date(run.completed_at).getTime()
                  : refreshedAt) -
                  new Date(run.started_at || run.created_at).getTime(),
              )}
            </p>
            {watchId && (
              <button
                className="rounded border p-2"
                onClick={() => setWatchId(null)}
              >
                Stop watching (processing continues)
              </button>
            )}
            {run.alert?.cluster_id && (
              <Link
                className="underline"
                href={`/dashboard/${encodeURIComponent(tenantId)}/ingestion-v2/clusters/${encodeURIComponent(run.alert.cluster_id)}`}
              >
                V2 cluster and analysis: {run.alert.cluster_id}
              </Link>
            )}
            {run.nodes?.map((job) => (
              <details key={job.job_id} className="rounded border p-2">
                <summary>
                  {job.node_id} · {job.state} {job.wait_reason} ·{" "}
                  {job.duration_ms !== undefined
                    ? formatDurationMs(job.duration_ms)
                    : ""}
                </summary>
                <pre className="max-h-80 overflow-auto text-xs">
                  {JSON.stringify(
                    {
                      input_references: job.ancestors,
                      output: job.output,
                      error: job.error,
                      reclaimed_at: job.reclaimed_at,
                    },
                    null,
                    2,
                  )}
                </pre>
              </details>
            ))}
          </div>
        )}
      </section>
    </main>
  );
}
