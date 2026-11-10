"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  ReactFlow,
  Background,
  Controls,
  Handle,
  Position,
  applyNodeChanges,
  applyEdgeChanges,
  type Node,
  type NodeProps,
  type Edge,
  type Connection,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useAuth } from "@/lib/auth";
import { UserRole } from "@/lib/types";
import {
  workflowRequest,
  outputPorts,
  type FlowGraph,
  type FlowNode,
} from "@/lib/workflows";
import {
  NODE_DESIGN,
  NodeGallery,
  NodeFields,
  type AvailableConnector,
} from "@/components/workflow-node-kit";
import {
  Workflow,
  Layers,
  Maximize2,
  Minimize2,
  ChevronRight,
  Plus,
  X,
  Save,
  Upload,
} from "lucide-react";
import { WorkflowConnections } from "@/components/workflow-connections";
import { EditorChrome } from "@/components/dashboard/editor-chrome";
import {
  ResourceLibrary,
  EditorBack,
  TenantSelection,
  studioButton,
  studioPrimary,
} from "@/components/workflow-library";

type Kind = "workflow" | "playbook" | "agent";
interface Definition {
  kind: Kind;
  code: string;
  name: string;
  description: string;
  enabled: boolean;
  tenant_ids: string[];
  configuration: Record<string, unknown>;
  draft_version: number;
  active_revision?: number;
  revision?: number;
}
type StudioNode = Node<
  { definition: FlowNode; state?: string; inspect?: () => void },
  "studio"
>;
const pretty = (value: unknown) => JSON.stringify(value, null, 2);
const blank = (kind: Kind): Record<string, unknown> =>
  kind === "agent"
    ? {
        profile_code: "local-analysis",
        prompt:
          "Investigate supplied evidence only. Return supported findings and uncertainty.",
        output_schema: { type: "object" },
        tools: ["alert_evidence"],
        max_rounds: 5,
        max_calls: 10,
        input_scope: "alert",
      }
    : {
        format_version: "2.0",
        input_capabilities: [kind === "workflow" ? "raw" : "normalization"],
        nodes: [
          { id: "entry", type: "entry", config: {}, position: { x: 0, y: 80 } },
          {
            id: "done",
            type: "complete",
            config: {},
            position: { x: 500, y: 80 },
          },
        ],
        edges: [{ id: "start", source: "entry", target: "done" }],
      };

function Tile({ data, selected }: NodeProps<StudioNode>) {
  const definition = data.definition;
  const ports = [
    ...outputPorts(definition),
    ...(definition.type === "tool_call" ? ["tool"] : []),
  ];
  const subflow = ["agent", "playbook_call", "playbook_selector"].includes(
    definition.type,
  );
  const design = NODE_DESIGN[definition.type];
  const Icon = design?.icon || Workflow;
  return (
    <div
      className={`w-60 rounded-xl border bg-card text-card-foreground shadow-lg transition-shadow ${selected ? "border-primary ring-2 ring-primary/25" : "border-border"}`}
    >
      {definition.type !== "entry" && (
        <Handle type="target" position={Position.Left} />
      )}
      {definition.type === "llm_tools" && (
        <Handle id="tools" type="target" position={Position.Bottom} />
      )}
      <div className="flex items-center gap-3 p-3.5">
        <span
          className="rounded-lg p-2"
          style={{
            color: design?.color,
            background: `${design?.color || "#888888"}18`,
          }}
        >
          <Icon size={20} />
        </span>
        <div className="min-w-0">
          <strong className="block text-sm">
            {definition.label || design?.title || definition.id}
          </strong>
          <span className="text-[10px] text-muted-foreground">
            {design?.title || definition.type}
          </span>
        </div>
        {subflow && <Layers size={15} className="ml-auto text-violet-400" />}
      </div>
      <div className="border-t border-border/50 px-3.5 py-2 text-xs text-muted-foreground">
        {typeof definition.config.definition_code === "string"
          ? `↳ ${definition.config.definition_code}`
          : definition.type === "playbook_selector"
            ? `Fallback: ${definition.config.fallback || "not configured"}`
            : design?.description || definition.id}
      </div>
      {data.state && (
        <p role="status" className="px-3.5 pb-2 text-xs font-semibold">
          {data.state}
        </p>
      )}
      {ports.map((port, i) => (
        <Handle
          key={port}
          id={port}
          type="source"
          position={Position.Right}
          style={{
            top: `${((i + 1) * 100) / (ports.length + 1)}%`,
            background:
              port === "error"
                ? "#dc2626"
                : port === "tool"
                  ? "#9333ea"
                  : "#2563eb",
          }}
          title={port}
        />
      ))}
      <p className="flex justify-end gap-2 border-t border-border/50 px-3 py-1.5 text-[10px] text-muted-foreground">
        {data.inspect && (
          <button
            className="nodrag nopan mr-auto text-primary underline focus-visible:outline-2 focus-visible:outline-primary"
            aria-label={`Inspect step ${definition.label || definition.id}`}
            onClick={(event) => {
              event.stopPropagation();
              data.inspect?.();
            }}
          >
            Inspect
          </button>
        )}
        {ports.join(" · ")}
      </p>
    </div>
  );
}
const nodeTypes = { studio: Tile };

export function subflowReferences(
  node: FlowNode,
): { kind: Kind; code: string; role: string }[] {
  const cfg = node.config,
    result: { kind: Kind; code: string; role: string }[] = [];
  if (
    ["agent", "playbook_call"].includes(node.type) &&
    typeof cfg.definition_code === "string"
  )
    result.push({
      kind: node.type === "agent" ? "agent" : "playbook",
      code: cfg.definition_code,
      role: "Direct call",
    });
  if (node.type === "playbook_selector") {
    if (typeof cfg.fallback === "string")
      result.push({ kind: "playbook", code: cfg.fallback, role: "Fallback" });
    for (const [type, code] of Object.entries(
      (cfg.mappings || {}) as Record<string, string>,
    ))
      result.push({ kind: "playbook", code, role: `Static: ${type}` });
    for (const code of (cfg.candidates || []) as string[])
      result.push({ kind: "playbook", code, role: "Model candidate" });
  }
  for (const tool of (cfg.tools || []) as string[]) {
    const [kind, code] = tool.split(":");
    if ((kind === "agent" || kind === "playbook") && code)
      result.push({ kind, code, role: "Agent capability" });
  }
  return result;
}

export function SubflowPanel({
  node,
  definitions,
  onOpen,
}: {
  node: FlowNode;
  definitions: Definition[];
  onOpen: (row: Definition) => void;
}) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const refs = subflowReferences(node);
  if (!refs.length) return null;
  const unique = [...new Set(refs.map((ref) => `${ref.kind}:${ref.code}`))];
  return (
    <section
      aria-label="Nested playbooks and agents"
      className="space-y-3 rounded-xl border border-violet-500/40 bg-violet-500/5 p-4"
    >
      <h3 className="flex items-center gap-2 font-semibold">
        <Layers size={18} />
        Nested playbooks & agents
      </h3>
      <p className="text-xs text-muted-foreground">
        Reusable subflows execute inside this node. Previews show current
        definitions; each execution pins its published dependency revisions.
      </p>
      {unique.map((identity) => {
        const roles = refs.filter(
            (ref) => `${ref.kind}:${ref.code}` === identity,
          ),
          ref = roles[0],
          target = definitions.find(
            (row) => row.kind === ref.kind && row.code === ref.code,
          );
        const graph = target?.configuration.nodes
          ? (target.configuration as unknown as FlowGraph)
          : null;
        return (
          <div key={identity} className="rounded-lg border bg-card p-3">
            <div className="flex flex-wrap items-center gap-3">
              <Layers className="text-violet-400" size={18} />
              <div className="flex-1">
                <strong>{target?.name || ref.code}</strong>
                <p className="text-xs text-muted-foreground">
                  {roles.map((row) => row.role).join(" · ")} ·{" "}
                  {target?.active_revision
                    ? `published r${target.active_revision}`
                    : "not published"}
                </p>
              </div>
              {target ? (
                <>
                  <button
                    className="rounded border px-3 py-2 text-xs"
                    onClick={() =>
                      setExpanded(expanded === identity ? null : identity)
                    }
                  >
                    {expanded === identity ? "Collapse" : "Preview subflow"}
                  </button>
                  <button
                    className="flex items-center gap-1 rounded bg-violet-500/15 px-3 py-2 text-xs"
                    onClick={() => onOpen(target)}
                  >
                    Open {ref.kind}
                    <ChevronRight size={14} />
                  </button>
                </>
              ) : (
                <p role="alert">Referenced definition unavailable</p>
              )}
            </div>
            {expanded === identity && target && (
              <div className="mt-3 border-t pt-3">
                {graph ? (
                  <WorkflowCanvas graph={graph} />
                ) : (
                  <div className="space-y-2 text-sm">
                    <p>
                      Bounded agent · profile{" "}
                      {String(
                        target.configuration.profile_code || "not configured",
                      )}
                    </p>
                    <p>
                      Tools:{" "}
                      {((target.configuration.tools || []) as string[]).join(
                        ", ",
                      ) || "none"}
                    </p>
                    <p className="whitespace-pre-wrap">
                      {String(target.configuration.prompt || "")}
                    </p>
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}
    </section>
  );
}

export function GraphJsonEditor({
  graph,
  readOnly,
  onApply,
}: {
  graph: FlowGraph;
  readOnly: boolean;
  onApply: (value: FlowGraph) => void;
}) {
  const serialized = pretty(graph);
  const [base, setBase] = useState(serialized),
    [text, setText] = useState(serialized),
    [error, setError] = useState("");
  if (base !== serialized && text === base) {
    setBase(serialized);
    setText(serialized);
  }
  const stale = base !== serialized;
  return (
    <details>
      <summary>Whole graph JSON / import</summary>
      <textarea
        className="min-h-64 w-full rounded border bg-background p-2 font-mono text-sm"
        aria-label="Graph JSON"
        value={text}
        readOnly={readOnly}
        onChange={(event) => setText(event.target.value)}
      />
      {stale && (
        <p role="alert">
          The graph changed while editing JSON. Reload the current graph before
          applying an import.
        </p>
      )}
      {error && <p role="alert">{error}</p>}
      <button
        disabled={readOnly || stale}
        onClick={() => {
          try {
            const value = JSON.parse(text);
            if (!isFlowGraph(value)) throw new Error("Invalid graph");
            onApply(value);
            setBase(pretty(value));
            setText(pretty(value));
            setError("");
          } catch {
            setError("Invalid graph JSON; current graph was preserved.");
          }
        }}
      >
        Apply JSON import
      </button>{" "}
      <button
        onClick={() => {
          setBase(serialized);
          setText(serialized);
          setError("");
        }}
      >
        Reload current graph
      </button>
    </details>
  );
}

export function WorkflowCanvas({
  graph,
  onChange,
  onSelect,
  selectedId,
  fill = false,
  states = {},
}: {
  graph: FlowGraph;
  onChange?: (value: FlowGraph) => void;
  onSelect?: (node: FlowNode) => void;
  selectedId?: string | null;
  fill?: boolean;
  states?: Record<string, string>;
}) {
  const nodes: StudioNode[] = graph.nodes.map((definition, i) => ({
    id: definition.id,
    type: "studio",
    data: {
      definition,
      state: states[definition.id],
      ...(onSelect ? { inspect: () => onSelect(definition) } : {}),
    },
    selected: definition.id === selectedId,
    position: definition.position || { x: i * 300, y: 60 },
  }));
  const edges: Edge[] = graph.edges.map((edge) => ({
    ...edge,
    style:
      edge.sourceHandle === "tool"
        ? { strokeDasharray: "5 4", stroke: "#9333ea" }
        : undefined,
  }));
  function connect(value: Connection) {
    if (!onChange || !value.source || !value.target) return;
    onChange({
      ...graph,
      edges: [
        ...graph.edges,
        {
          id: crypto.randomUUID(),
          source: value.source,
          target: value.target,
          sourceHandle: value.sourceHandle || "success",
          ...(value.targetHandle ? { targetHandle: value.targetHandle } : {}),
        },
      ],
    });
  }
  return (
    <div
      className={`${fill ? "h-full min-h-0" : "h-[550px]"} min-w-0 rounded-xl border bg-muted/20`}
      aria-label="Workflow canvas"
    >
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        nodesDraggable={Boolean(onChange)}
        nodesConnectable={Boolean(onChange)}
        edgesReconnectable={Boolean(onChange)}
        onConnect={connect}
        onNodeClick={(_, selected) => onSelect?.(selected.data.definition)}
        onNodesChange={(changes) => {
          if (!onChange) return;
          const edits = changes.filter(
            (change) => change.type === "position" || change.type === "remove",
          );
          if (!edits.length) return;
          const next = applyNodeChanges(edits, nodes);
          const ids = new Set(next.map((n) => n.id));
          onChange({
            ...graph,
            nodes: next.map((n) => ({
              ...n.data.definition,
              position: n.position,
            })),
            edges: graph.edges.filter(
              (e) => ids.has(e.source) && ids.has(e.target),
            ),
          });
        }}
        onEdgesChange={(changes) => {
          const edits = changes.filter((change) => change.type !== "select");
          if (!edits.length) return;
          onChange?.({
            ...graph,
            edges: applyEdgeChanges(edits, edges).map((edge) => ({
              id: edge.id,
              source: edge.source,
              target: edge.target,
              ...(edge.sourceHandle ? { sourceHandle: edge.sourceHandle } : {}),
              ...(edge.targetHandle ? { targetHandle: edge.targetHandle } : {}),
            })),
          });
        }}
      >
        <Background />
        <Controls className="!border-border !shadow-lg [&>button]:!border-border [&>button]:!bg-card [&>button]:!text-foreground [&_svg]:!fill-current" />
      </ReactFlow>
    </div>
  );
}

export function isFlowGraph(value: unknown): value is FlowGraph {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const graph = value as Partial<FlowGraph>;
  return (
    Array.isArray(graph.nodes) &&
    Array.isArray(graph.edges) &&
    graph.nodes.every(
      (n) =>
        n &&
        typeof n.id === "string" &&
        typeof n.type === "string" &&
        n.config &&
        typeof n.config === "object" &&
        !Array.isArray(n.config),
    ) &&
    graph.edges.every(
      (e) =>
        e &&
        typeof e.id === "string" &&
        typeof e.source === "string" &&
        typeof e.target === "string",
    )
  );
}
const libraryCopy = {
  workflow: {
    title: "Workflows",
    description:
      "Choose how alerts enter TierX, which investigations run, and where results go.",
  },
  playbook: {
    title: "Playbooks",
    description:
      "Reusable investigation flows you can call from workflows or agents.",
  },
  agent: {
    title: "Agents",
    description:
      "Specialist investigators with a model, instructions, approved tools, and clear limits.",
  },
};
type StudioTab = "editor" | "settings" | "entry" | "history" | "versions";
type RunRow = {
  run_id: string;
  alert_id: string;
  state: string;
  created_at: string;
  definition_ref?: string;
};

export function WorkflowStudio({
  initialKind = "workflow",
}: {
  initialKind?: Kind;
}) {
  const { user } = useAuth();
  const editorRoot = useRef<HTMLElement>(null);
  const [items, setItems] = useState<Definition[]>([]),
    [catalog, setCatalog] = useState<string[]>([]),
    [templates, setTemplates] = useState<Definition[]>([]);
  const [draft, setDraft] = useState<Definition | null>(null),
    [selected, setSelected] = useState<string | null>(null);
  const [agentJson, setAgentJson] = useState("{}"),
    [nodeJson, setNodeJson] = useState("{}"),
    [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false),
    [loading, setLoading] = useState(true),
    [wide, setWide] = useState(false);
  const [palette, setPalette] = useState(false),
    [showTemplates, setShowTemplates] = useState(false),
    [tab, setTab] = useState<StudioTab>("editor");
  const [profiles, setProfiles] = useState<
      { profile_code: string; model: string }[]
    >([]),
    [connectors, setConnectors] = useState<AvailableConnector[]>([]);
  const [versions, setVersions] = useState<Definition[]>([]),
    [readOnly, setReadOnly] = useState(false),
    [breadcrumbs, setBreadcrumbs] = useState<Definition[]>([]);
  const [entryTenant, setEntryTenant] = useState(""),
    [jiraConnections, setJiraConnections] = useState("");
  const [credential, setCredential] = useState<{
    token: string;
    path: string;
    jira_path: string;
  } | null>(null);
  const [runTenant, setRunTenant] = useState(""),
    [runRows, setRunRows] = useState<RunRow[]>([]),
    [runsLoaded, setRunsLoaded] = useState(false);
  useEffect(() => {
    if (!wide) return;
    const previous = document.activeElement;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    editorRoot.current
      ?.querySelector<HTMLButtonElement>("[data-collapse-canvas]")
      ?.focus();
    return () => {
      document.body.style.overflow = overflow;
      if (previous instanceof HTMLElement) previous.focus();
    };
  }, [wide]);
  const load = useCallback(async () => {
    const result = await workflowRequest<{
      items: Definition[];
      node_types: string[];
      templates: Definition[];
    }>("/admin/workflow-definitions");
    setItems(result.items);
    setCatalog(
      result.node_types.filter(
        (type) =>
          !["playbook", "knowledge_base", "enrichment_action"].includes(type),
      ),
    );
    setTemplates(result.templates || []);
  }, []);
  useEffect(() => {
    if (user?.role !== UserRole.PLATFORM_ADMIN) return;
    load()
      .catch((e) => setMessage(e.message))
      .finally(() => setLoading(false));
  }, [user?.role, load]);
  useEffect(() => {
    if (user?.role !== UserRole.PLATFORM_ADMIN) return;
    let active = true;
    Promise.all([
      workflowRequest<{ items: typeof profiles }>("/admin/llm-profiles"),
      workflowRequest<{ items: AvailableConnector[] }>("/admin/connectors"),
    ])
      .then(([p, c]) => {
        if (active) {
          setProfiles(p.items);
          setConnectors(c.items);
        }
      })
      .catch(() => {
        if (active)
          setMessage(
            "Model/tool catalogues unavailable. Existing settings are preserved.",
          );
      });
    return () => {
      active = false;
    };
  }, [user?.role]);
  const saved = items.find(
    (row) => row.kind === draft?.kind && row.code === draft?.code,
  );
  function comparable(
    row: Definition,
    configuration: unknown = row.configuration,
  ) {
    return pretty({
      code: row.code,
      name: row.name,
      description: row.description || "",
      enabled: row.enabled,
      tenant_ids: row.tenant_ids,
      configuration,
    });
  }
  let configuration = draft?.configuration,
    invalidAgent = false;
  if (draft?.kind === "agent") {
    try {
      configuration = JSON.parse(agentJson);
      if (
        !configuration ||
        typeof configuration !== "object" ||
        Array.isArray(configuration)
      )
        throw new Error("Agent configuration must be an object");
    } catch {
      invalidAgent = true;
    }
  }
  const unsaved = Boolean(
    draft &&
      !readOnly &&
      (!saved ||
        invalidAgent ||
        comparable(draft, configuration) !== comparable(saved)),
  );
  useEffect(() => {
    if (!unsaved) return;
    const guard = (event: BeforeUnloadEvent) => {
      event.preventDefault();
    };
    window.addEventListener("beforeunload", guard);
    return () => window.removeEventListener("beforeunload", guard);
  }, [unsaved]);
  function open(row: Definition, nested = false) {
    if (!nested && unsaved && !confirm("Discard unsaved changes?")) return;
    if (nested && draft) {
      if (invalidAgent) {
        setMessage(
          "Fix the agent JSON before opening a subflow. Your changes are preserved.",
        );
        return;
      }
      setBreadcrumbs((old) => [
        ...old,
        { ...structuredClone(draft), configuration: configuration! },
      ]);
    } else setBreadcrumbs([]);
    setDraft(structuredClone(row));
    setAgentJson(pretty(row.configuration));
    setSelected(null);
    setCredential(null);
    setVersions([]);
    setReadOnly(false);
    setWide(false);
    setPalette(false);
    setTab("editor");
    setMessage("");
    setEntryTenant(row.tenant_ids[0] || "");
    setRunTenant(row.tenant_ids[0] || "");
    setRunRows([]);
    setRunsLoaded(false);
  }
  function back() {
    if (
      unsaved &&
      !confirm("Discard unsaved changes and return to the library?")
    )
      return;
    setDraft(null);
    setBreadcrumbs([]);
    setWide(false);
    setCredential(null);
    setMessage("");
  }
  async function action(task: () => Promise<void>) {
    setBusy(true);
    setMessage("");
    try {
      await task();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }
  async function save() {
    if (!draft) return;
    const cfg =
      draft.kind === "agent" ? JSON.parse(agentJson) : draft.configuration;
    const row = await workflowRequest<Definition>(
      "/admin/workflow-definitions/" +
        draft.kind +
        "/" +
        encodeURIComponent(draft.code),
      "PUT",
      {
        name: draft.name,
        description: draft.description,
        enabled: draft.enabled,
        tenant_ids: draft.tenant_ids,
        configuration: cfg,
        expected_version: draft.draft_version,
      },
    );
    setDraft(row);
    setAgentJson(pretty(row.configuration));
    await load();
    setMessage(
      "Draft saved. Publish when you are ready to use it for new runs.",
    );
  }
  function newDefinition(template?: Definition) {
    const kind = initialKind;
    open({
      kind,
      code: template
        ? `${template.code.slice(0, 54)}-${crypto.randomUUID().slice(0, 8)}`
        : "",
      name: template?.name || "",
      description: template?.description || "",
      tenant_ids: [],
      enabled: true,
      configuration: structuredClone(template?.configuration || blank(kind)),
      draft_version: 0,
    });
    setTab("settings");
  }
  if (user?.role !== UserRole.PLATFORM_ADMIN)
    return <p className="p-6">Platform administrator access required.</p>;
  const copy = libraryCopy[initialKind];
  if (!draft)
    return (
      <ResourceLibrary
        title={copy.title}
        description={copy.description}
        createLabel={"Create " + initialKind}
        onCreate={() => newDefinition()}
        loading={loading}
        error={message}
        items={items
          .filter((row) => row.kind === initialKind)
          .map((row) => ({
            id: row.code,
            name: row.name,
            description: row.description,
            metadata:
              (row.kind === "agent"
                ? "Model: " +
                  String(row.configuration.profile_code || "Not selected")
                : (Array.isArray(row.configuration.nodes)
                    ? row.configuration.nodes.length
                    : 0) + " steps") +
              " · " +
              row.tenant_ids.length +
              " authorized tenants",
            status: !row.enabled
              ? "Disabled"
              : row.active_revision
                ? "Published v" + row.active_revision
                : "Draft",
            onOpen: () => open(row),
          }))}
      >
        <section className="rounded-xl border bg-card p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="font-medium">Start with a template</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Create your own editable copy. Nothing is published
                automatically.
              </p>
            </div>
            <button
              className={studioButton}
              aria-expanded={showTemplates}
              onClick={() => setShowTemplates(!showTemplates)}
            >
              {showTemplates ? "Hide templates" : "Browse templates"}
            </button>
          </div>
          {showTemplates && (
            <div className="mt-4 grid gap-3 md:grid-cols-3">
              {templates
                .filter((t) => t.kind === initialKind)
                .map((t) => (
                  <button
                    className="rounded-lg border p-4 text-left text-sm hover:border-primary"
                    key={t.code}
                    onClick={() => newDefinition(t)}
                  >
                    <strong>{t.name}</strong>
                    <p className="mt-2 text-muted-foreground">
                      {t.description || "Customize this template."}
                    </p>
                  </button>
                ))}
            </div>
          )}
        </section>
      </ResourceLibrary>
    );
  const graph =
    draft.kind !== "agent" && isFlowGraph(draft.configuration)
      ? draft.configuration
      : null;
  const node = graph?.nodes.find((n) => n.id === selected);
  const field =
    "mt-1 block min-h-10 w-full rounded-lg border bg-background px-3 py-2 text-sm";
  const setGraph = (value: FlowGraph) =>
    setDraft({
      ...draft,
      configuration: value as unknown as Record<string, unknown>,
    });
  const tabs: { key: StudioTab; label: string }[] = [
    { key: "editor", label: draft.kind === "agent" ? "Agent setup" : "Editor" },
    { key: "settings", label: "Settings" },
    ...(draft.kind === "workflow"
      ? [{ key: "entry" as const, label: "Ingestion" }]
      : []),
    { key: "history", label: "Executions" },
    { key: "versions", label: "Versions" },
  ];
  return (
    <main
      ref={editorRoot}
      role={wide ? "dialog" : undefined}
      aria-modal={wide ? true : undefined}
      aria-label={wide ? "Expanded workflow editor" : undefined}
      className={
        wide
          ? "fixed inset-0 z-[60] flex min-h-0 flex-col gap-3 bg-background p-3"
          : "flex h-full min-h-0 flex-col gap-3 p-3"
      }
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.stopPropagation();
          if (selected) setSelected(null);
          else if (palette) setPalette(false);
          else setWide(false);
        }
        if (wide && event.key === "Tab") {
          const all = Array.from(
            event.currentTarget.querySelectorAll<HTMLElement>(
              'button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),a[href],[tabindex="0"]',
            ),
          ).filter((el) => el.offsetParent !== null);
          const first = all[0],
            last = all.at(-1);
          if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last?.focus();
          } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first?.focus();
          }
        }
      }}
    >
      <EditorChrome local={wide}>
        <div className="w-full space-y-1">
          <div className="flex flex-wrap items-center gap-3">
            <EditorBack
              onClick={back}
              label={"Back to " + copy.title.toLowerCase()}
            />
            <div className="min-w-0 flex-1">
              <h1
                className="truncate text-base font-semibold sm:text-lg"
                title={draft.name}
              >
                {draft.name || "New " + draft.kind}
              </h1>
            </div>
            <span className="rounded-full bg-muted px-2.5 py-1 text-xs">
              {readOnly
                ? "Read-only v" + draft.revision
                : unsaved
                  ? "Unsaved changes"
                  : draft.active_revision
                    ? "Published v" + draft.active_revision
                    : "Draft"}
            </span>
            <div className="flex flex-wrap gap-2">
              <button
                className={studioButton}
                disabled={
                  busy || readOnly || invalidAgent || !draft.code || !draft.name
                }
                onClick={() => action(save)}
              >
                <Save size={15} />
                {busy ? "Working…" : "Save draft"}
              </button>
              <button
                className={studioPrimary}
                disabled={busy || readOnly || !draft.draft_version || unsaved}
                title={
                  unsaved
                    ? "Save your draft before publishing"
                    : "Activate an immutable version for new runs"
                }
                onClick={() => {
                  if (
                    !confirm(
                      "Publish this version for new runs? Existing runs keep their pinned versions.",
                    )
                  )
                    return;
                  action(async () => {
                    const result = await workflowRequest<{ revision: number }>(
                      "/admin/workflow-definitions/" +
                        draft.kind +
                        "/" +
                        draft.code +
                        "/publish",
                      "POST",
                    );
                    await load();
                    setDraft({ ...draft, active_revision: result.revision });
                    setMessage(
                      "Published v" +
                        result.revision +
                        ". New runs use this version.",
                    );
                  });
                }}
              >
                <Upload size={15} />
                Publish
              </button>
            </div>
          </div>
          {breadcrumbs.length > 0 && (
            <nav
              aria-label="Subflow breadcrumbs"
              className="flex flex-wrap gap-2 text-sm"
            >
              {breadcrumbs.map((row, index) => (
                <button
                  key={index}
                  className="inline-flex items-center gap-1 text-muted-foreground hover:text-primary"
                  onClick={() => {
                    if (
                      unsaved &&
                      !confirm("Discard changes to this child definition?")
                    )
                      return;
                    const parents = breadcrumbs.slice(0, index);
                    setDraft(null);
                    open(row, true);
                    setBreadcrumbs(parents);
                  }}
                >
                  {row.name}
                  <ChevronRight size={14} />
                </button>
              ))}
              <span>{draft.name}</span>
            </nav>
          )}
        </div>
      </EditorChrome>
      {message && (
        <p role="status" className="rounded-lg border bg-card p-3 text-sm">
          {message}
        </p>
      )}
      <nav
        aria-label="Definition sections"
        className="flex shrink-0 gap-1 overflow-x-auto border-b"
      >
        {tabs.map((t) => (
          <button
            key={t.key}
            className={
              "whitespace-nowrap border-b-2 px-4 py-3 text-sm " +
              (tab === t.key
                ? "border-primary font-medium text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground")
            }
            aria-current={tab === t.key ? "page" : undefined}
            onClick={() => {
              setTab(t.key);
              setCredential(null);
            }}
          >
            {t.label}
          </button>
        ))}
      </nav>
      {tab === "settings" && (
        <section className="mx-auto w-full max-w-3xl min-h-0 flex-1 space-y-6 overflow-y-auto pb-6">
          <div className="rounded-xl border bg-card p-5">
            <h2 className="mb-4 text-lg font-semibold">
              About this {draft.kind}
            </h2>
            <div className="space-y-4">
              <label className="block text-sm">
                Name
                <input
                  className={field}
                  value={draft.name}
                  disabled={readOnly}
                  placeholder="A clear, recognizable name"
                  onChange={(e) => {
                    const name = e.target.value;
                    setDraft({
                      ...draft,
                      name,
                      ...(!draft.draft_version &&
                      (!draft.code ||
                        draft.code ===
                          draft.name
                            .toLowerCase()
                            .replace(/[^a-z0-9]+/g, "-")
                            .replace(/^-|-$/g, "")
                            .slice(0, 64))
                        ? {
                            code: name
                              .toLowerCase()
                              .replace(/[^a-z0-9]+/g, "-")
                              .replace(/^-|-$/g, "")
                              .slice(0, 64),
                          }
                        : {}),
                    });
                  }}
                />
              </label>
              <label className="block text-sm">
                Description
                <textarea
                  className={field + " min-h-24"}
                  value={draft.description}
                  disabled={readOnly}
                  placeholder="When should this be used?"
                  onChange={(e) =>
                    setDraft({ ...draft, description: e.target.value })
                  }
                />
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={draft.enabled}
                  disabled={readOnly}
                  onChange={(e) =>
                    setDraft({ ...draft, enabled: e.target.checked })
                  }
                />
                Enabled for authorized tenants
              </label>
              <p className="text-xs text-muted-foreground">
                Disabling takes effect when saved. Publishing controls the
                version used by new runs.
              </p>
            </div>
          </div>
          <TenantSelection
            multiple
            value={draft.tenant_ids}
            onChange={(tenant_ids) => setDraft({ ...draft, tenant_ids })}
            disabled={readOnly}
          />
          <details className="rounded-xl border p-5">
            <summary className="cursor-pointer text-sm font-medium">
              Advanced identifier
            </summary>
            <label className="mt-4 block text-sm">
              Code
              <input
                className={field + " font-mono"}
                value={draft.code}
                disabled={readOnly || draft.draft_version > 0}
                onChange={(e) => setDraft({ ...draft, code: e.target.value })}
              />
            </label>
            <p className="mt-2 text-xs text-muted-foreground">
              Stable internal reference; cannot be changed after the first save.
            </p>
          </details>
          {draft.draft_version > 0 && !readOnly && (
            <details className="rounded-xl border border-destructive/30 p-5">
              <summary className="cursor-pointer text-sm text-destructive">
                Delete {draft.kind}
              </summary>
              <p className="my-3 text-sm text-muted-foreground">
                Blocks new calls. Historical executions remain available.
              </p>
              <button
                className={studioButton + " text-destructive"}
                disabled={busy}
                onClick={() => {
                  if (
                    confirm(
                      "Delete this definition? Historical executions remain.",
                    )
                  )
                    action(async () => {
                      await workflowRequest(
                        "/admin/workflow-definitions/" +
                          draft.kind +
                          "/" +
                          draft.code,
                        "DELETE",
                      );
                      setDraft(null);
                      await load();
                    });
                }}
              >
                Confirm deletion
              </button>
            </details>
          )}
        </section>
      )}
      {tab === "editor" && graph && (
        <section className="flex min-h-0 flex-1 flex-col gap-3">
          <div className="flex shrink-0 flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              {!readOnly && (
                <button
                  className={studioButton}
                  aria-expanded={palette}
                  onClick={() => setPalette(!palette)}
                >
                  <Plus size={16} />
                  {palette ? "Hide steps" : "Add step"}
                </button>
              )}
              <span className="text-xs text-muted-foreground">
                {graph.nodes.length} steps · select a node to configure it
              </span>
            </div>
            <button
              data-collapse-canvas={wide ? true : undefined}
              className={studioButton}
              onClick={() => {
                setPalette(false);
                setWide(!wide);
              }}
            >
              {wide ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
              <span>{wide ? "Close expanded canvas" : "Expand canvas"}</span>
            </button>
          </div>
          <div className="relative min-h-0 flex-1 overflow-hidden rounded-xl">
            {palette && !readOnly && (
              <aside
                className="absolute inset-y-3 left-3 z-20 w-[280px] max-w-[90%] overflow-auto rounded-xl shadow-2xl"
                aria-label="Add steps"
              >
                <NodeGallery
                  catalog={catalog}
                  hasEntry={graph.nodes.some((n) => n.type === "entry")}
                  onAdd={(type) => {
                    const id = type + "-" + crypto.randomUUID().slice(0, 8);
                    setGraph({
                      ...graph,
                      nodes: [
                        ...graph.nodes,
                        {
                          id,
                          type,
                          config: {},
                          position: { x: graph.nodes.length * 100, y: 200 },
                        },
                      ],
                    });
                    setSelected(id);
                    setNodeJson("{}");
                    setPalette(false);
                  }}
                />
              </aside>
            )}
            <div className="absolute inset-0">
              <WorkflowCanvas
                fill
                graph={graph}
                selectedId={selected}
                onChange={readOnly ? undefined : setGraph}
                onSelect={(n) => {
                  setSelected(n.id);
                  setNodeJson(pretty(n.config));
                  setPalette(false);
                }}
              />
            </div>
            {node && (
              <aside
                aria-label="Step settings"
                className="absolute inset-y-3 right-3 z-20 space-y-4 overflow-auto rounded-xl border bg-card p-4 shadow-2xl"
                style={{ width: "min(380px, calc(100% - 24px))" }}
              >
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-xs text-muted-foreground">
                      Step settings
                    </p>
                    <h2 className="mt-1 font-semibold">
                      {node.label || NODE_DESIGN[node.type]?.title || node.id}
                    </h2>
                  </div>
                  <button
                    className={studioButton}
                    aria-label="Close step settings"
                    onClick={() => setSelected(null)}
                  >
                    <X size={16} />
                  </button>
                </div>
                <fieldset disabled={readOnly} className="space-y-3">
                  <label className="block text-sm">
                    Step name
                    <input
                      className={field}
                      value={node.label || ""}
                      placeholder={NODE_DESIGN[node.type]?.title || node.type}
                      onChange={(e) =>
                        setGraph({
                          ...graph,
                          nodes: graph.nodes.map((n) =>
                            n.id === node.id
                              ? { ...n, label: e.target.value }
                              : n,
                          ),
                        })
                      }
                    />
                  </label>
                  <NodeFields
                    node={node}
                    value={node.config}
                    profiles={profiles}
                    connectors={connectors}
                    definitions={items}
                    onChange={(config) => {
                      setGraph({
                        ...graph,
                        nodes: graph.nodes.map((n) =>
                          n.id === node.id ? { ...n, config } : n,
                        ),
                      });
                      setNodeJson(pretty(config));
                    }}
                  />
                </fieldset>
                <SubflowPanel
                  key={node.id}
                  node={node}
                  definitions={items}
                  onOpen={(target) => open(target, true)}
                />
                <details>
                  <summary className="text-sm">Advanced step JSON</summary>
                  <textarea
                    className={field + " min-h-48 font-mono text-xs"}
                    aria-label="Node configuration"
                    value={nodeJson}
                    readOnly={readOnly}
                    onChange={(e) => setNodeJson(e.target.value)}
                  />
                  <button
                    className={studioButton + " mt-2"}
                    disabled={readOnly}
                    onClick={() => {
                      try {
                        const config = JSON.parse(nodeJson);
                        if (
                          !config ||
                          typeof config !== "object" ||
                          Array.isArray(config)
                        )
                          throw Error();
                        setGraph({
                          ...graph,
                          nodes: graph.nodes.map((n) =>
                            n.id === node.id ? { ...n, config } : n,
                          ),
                        });
                        setMessage(
                          "Step settings applied. Save the draft to keep them.",
                        );
                      } catch {
                        setMessage("Step configuration must be a JSON object.");
                      }
                    }}
                  >
                    Apply JSON
                  </button>
                </details>
              </aside>
            )}
            <details
              className="absolute bottom-3 left-14 z-10 max-h-[70%] overflow-auto rounded-lg border bg-card p-3 shadow-lg"
              style={{ width: "min(720px, calc(100% - 80px))" }}
            >
              <summary className="cursor-pointer text-sm font-medium">
                Canvas tools
              </summary>
              <div className="mt-3">
                {" "}
                {!readOnly && (
                  <WorkflowConnections graph={graph} onChange={setGraph} />
                )}
                <details className="mt-4 rounded-lg border p-3">
                  <summary className="cursor-pointer text-sm text-muted-foreground">
                    Advanced graph import
                  </summary>
                  <GraphJsonEditor
                    graph={graph}
                    readOnly={readOnly}
                    key={
                      draft.kind +
                      ":" +
                      draft.code +
                      ":" +
                      draft.draft_version +
                      ":" +
                      readOnly
                    }
                    onApply={setGraph}
                  />
                </details>
              </div>
            </details>
          </div>
        </section>
      )}
      {tab === "editor" && draft.kind === "agent" && (
        <section className="mx-auto w-full max-w-5xl min-h-0 flex-1 space-y-5 overflow-y-auto pb-6">
          <div className="rounded-xl border bg-card p-5">
            <h2 className="text-lg font-semibold">Investigation behavior</h2>
            <p className="mb-5 mt-1 text-sm text-muted-foreground">
              Choose a model, give clear instructions, and allow only the tools
              this specialist needs.
            </p>
            {invalidAgent ? (
              <p role="alert">Fix the advanced JSON to continue editing.</p>
            ) : (
              <fieldset disabled={readOnly}>
                <NodeFields
                  node={{
                    id: "agent",
                    type: "llm_tools",
                    config: configuration!,
                  }}
                  value={configuration!}
                  profiles={profiles}
                  connectors={connectors}
                  definitions={items}
                  onChange={(cfg) => setAgentJson(pretty(cfg))}
                />
              </fieldset>
            )}
          </div>
          {!invalidAgent && (
            <SubflowPanel
              node={{ id: "agent", type: "llm_tools", config: configuration! }}
              definitions={items}
              onOpen={(target) => open(target, true)}
            />
          )}
          <details className="rounded-xl border p-4">
            <summary className="text-sm">Advanced agent JSON</summary>
            <textarea
              aria-label="Agent configuration"
              className={field + " min-h-96 font-mono text-xs"}
              value={agentJson}
              readOnly={readOnly}
              onChange={(e) => setAgentJson(e.target.value)}
            />
          </details>
        </section>
      )}
      {tab === "entry" && (
        <section className="mx-auto w-full max-w-3xl min-h-0 flex-1 space-y-5 overflow-y-auto rounded-xl border bg-card p-5">
          <h2 className="text-lg font-semibold">Connect an alert source</h2>
          <p className="text-sm text-muted-foreground">
            Each tenant uses a fixed ingestion URL and a separate entry
            credential. Your login password is not an ingestion credential.
          </p>
          {!draft.active_revision ? (
            <p>Publish this workflow before creating an ingestion endpoint.</p>
          ) : (
            <>
              <TenantSelection
                label="Ingestion tenant"
                value={entryTenant ? [entryTenant] : []}
                onChange={(ids) => {
                  setEntryTenant(ids[0] || "");
                  setCredential(null);
                }}
              />
              {entryTenant && !draft.tenant_ids.includes(entryTenant) ? (
                <p role="alert">
                  This tenant is not authorized. Add it in Settings and save
                  before continuing.
                </p>
              ) : (
                entryTenant && (
                  <>
                    <p className="text-xs text-muted-foreground">
                      Fixed REST entry
                    </p>
                    <code className="block break-all rounded-lg bg-muted p-3 text-xs">
                      /api/v2/workflows/{draft.code}/tenants/{entryTenant}
                      /ingest
                    </code>
                    <details>
                      <summary className="text-sm">
                        Jira connection restrictions
                      </summary>
                      <label className="mt-3 block text-sm">
                        Allowed connection IDs
                        <input
                          className={field}
                          placeholder="Comma-separated connection IDs"
                          value={jiraConnections}
                          onChange={(e) => setJiraConnections(e.target.value)}
                        />
                      </label>
                    </details>
                    <button
                      className={studioButton}
                      disabled={busy || readOnly || unsaved}
                      onClick={() => {
                        if (
                          confirm(
                            "Generate or rotate the entry token? Any previous token stops working immediately.",
                          )
                        )
                          action(async () =>
                            setCredential(
                              await workflowRequest(
                                "/admin/workflow-definitions/workflow/" +
                                  draft.code +
                                  "/entry-credentials",
                                "POST",
                                {
                                  tenant_id: entryTenant,
                                  jira_connection_ids: jiraConnections
                                    .split(",")
                                    .map((s) => s.trim())
                                    .filter(Boolean),
                                },
                              ),
                            ),
                          );
                      }}
                    >
                      Generate / rotate entry token
                    </button>
                  </>
                )
              )}
              {credential && (
                <section className="space-y-3 rounded-lg border border-amber-500/40 p-4">
                  <h3 className="font-medium">Copy this token now</h3>
                  <p className="text-sm text-muted-foreground">
                    Shown once and held only in page memory. Do not share
                    screenshots containing it.
                  </p>
                  <code className="block break-all text-xs">
                    {credential.token}
                  </code>
                  <div className="flex gap-2">
                    <button
                      className={studioButton}
                      onClick={() =>
                        navigator.clipboard.writeText(credential.token)
                      }
                    >
                      Copy token
                    </button>
                    <button
                      className={studioButton}
                      onClick={() => setCredential(null)}
                    >
                      Hide token
                    </button>
                  </div>
                  <p className="break-all text-xs">
                    Jira workflow URL: {credential.jira_path}
                  </p>
                </section>
              )}
            </>
          )}
        </section>
      )}
      {tab === "history" && (
        <section className="mx-auto w-full max-w-5xl min-h-0 flex-1 space-y-5 overflow-y-auto pb-6">
          <div>
            <h2 className="text-lg font-semibold">Execution history</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Inspect recorded runs of this {draft.kind}, including its pinned
              version and step results.
            </p>
          </div>
          <div className="max-w-md">
            <TenantSelection
              label="Execution tenant"
              value={runTenant ? [runTenant] : []}
              onChange={(ids) => {
                setRunTenant(ids[0] || "");
                setRunsLoaded(false);
                setRunRows([]);
              }}
            />
          </div>
          <button
            className={studioButton}
            disabled={busy || !runTenant || !draft.draft_version}
            onClick={() =>
              action(async () => {
                const result = await workflowRequest<{ items: RunRow[] }>(
                  "/tenants/" + encodeURIComponent(runTenant) + "/runs",
                );
                setRunRows(
                  result.items.filter((row) =>
                    row.definition_ref?.startsWith(
                      draft.kind + ":" + draft.code + "@",
                    ),
                  ),
                );
                setRunsLoaded(true);
              })
            }
          >
            {busy ? "Loading…" : "Load executions"}
          </button>
          {runsLoaded && !runRows.length && (
            <p className="rounded-xl border border-dashed p-10 text-center text-sm text-muted-foreground">
              No recorded executions for this definition in the returned recent
              runs.
            </p>
          )}
          {runRows.map((row) => (
            <Link
              className="flex flex-wrap items-center gap-3 rounded-xl border bg-card p-4 text-sm hover:border-primary"
              key={row.run_id}
              href={
                "/dashboard/admin/workflows/runs/" +
                encodeURIComponent(runTenant) +
                "/" +
                row.run_id
              }
            >
              <span className="flex-1 font-mono text-xs">{row.alert_id}</span>
              <span>{row.state}</span>
              <span className="text-muted-foreground">
                {new Date(row.created_at).toLocaleString()}
              </span>
              <ChevronRight size={16} />
            </Link>
          ))}
        </section>
      )}
      {tab === "versions" && (
        <section className="mx-auto w-full max-w-3xl min-h-0 flex-1 space-y-4 overflow-y-auto pb-6">
          <h2 className="text-lg font-semibold">Published versions</h2>
          <p className="text-sm text-muted-foreground">
            Publishing creates an immutable version. Historical runs continue
            using their original version.
          </p>
          <button
            className={studioButton}
            disabled={busy || !draft.draft_version}
            onClick={() =>
              action(async () => {
                const result = await workflowRequest<{ items: Definition[] }>(
                  "/admin/workflow-definitions/" +
                    draft.kind +
                    "/" +
                    draft.code +
                    "/revisions",
                );
                setVersions(result.items);
                setMessage(
                  result.items.length ? "" : "No published versions yet.",
                );
              })
            }
          >
            Load versions
          </button>
          {versions.map((row) => (
            <button
              key={row.revision}
              className="flex w-full items-center justify-between rounded-lg border p-4 text-left text-sm"
              onClick={() => {
                if (
                  unsaved &&
                  !confirm("Discard unsaved changes to inspect this version?")
                )
                  return;
                setDraft({ ...row, draft_version: row.revision! });
                setAgentJson(pretty(row.configuration));
                setReadOnly(true);
                setTab("editor");
              }}
            >
              Version {row.revision}
              <span className="text-muted-foreground">Inspect read-only →</span>
            </button>
          ))}
        </section>
      )}
      {readOnly && (
        <p
          role="status"
          className="rounded-lg border border-amber-500/30 p-3 text-sm"
        >
          Historical version — read only. Return to the library to edit the
          current draft.
        </p>
      )}
    </main>
  );
}
