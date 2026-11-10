"use client";

import { useState } from "react";
import {
  Webhook,
  ShieldCheck,
  Shuffle,
  Fingerprint,
  BookOpen,
  Database,
  Plug,
  Network,
  BrainCircuit,
  Bot,
  GitBranch,
  Split,
  Merge,
  LifeBuoy,
  CheckCircle2,
  ArchiveX,
  Search,
  Plus,
  type LucideIcon,
} from "lucide-react";
import type { FlowNode } from "@/lib/workflows";

type Definition = {
  title: string;
  description: string;
  group: string;
  icon: LucideIcon;
  color: string;
};
export const NODE_DESIGN: Record<string, Definition> = {
  playbook_call: {
    title: "Playbook subflow",
    description: "Run a reusable investigation flow",
    group: "Gather context",
    icon: BookOpen,
    color: "#a78bfa",
  },
  playbook_selector: {
    title: "Select playbook",
    description: "Static or model selection with an explicit fallback",
    group: "Gather context",
    icon: GitBranch,
    color: "#a78bfa",
  },
  agent: {
    title: "Specialist agent",
    description: "Delegate to a bounded reusable agent",
    group: "Investigate",
    icon: Bot,
    color: "#fbbf24",
  },
  kb_deterministic: {
    title: "Deterministic knowledge",
    description: "Exact entities, CIDRs and lexical evidence",
    group: "Gather context",
    icon: Database,
    color: "#a78bfa",
  },
  kb_semantic: {
    title: "Semantic knowledge",
    description: "Retrieve related document evidence",
    group: "Gather context",
    icon: Search,
    color: "#a78bfa",
  },
  persist_analysis: {
    title: "Save analysis",
    description: "Persist the initiating alert's result",
    group: "Finish",
    icon: ArchiveX,
    color: "#34d399",
  },
  notify_jira: {
    title: "Notify Jira",
    description: "Deliver the chosen result to the originating issue",
    group: "Finish",
    icon: Webhook,
    color: "#38bdf8",
  },
  webhook: {
    title: "Webhook output",
    description: "Deliver structured output through an approved connector",
    group: "Finish",
    icon: Webhook,
    color: "#38bdf8",
  },
  entry: {
    title: "Alert entry",
    description: "Receive an alert and start this flow",
    group: "Receive & prepare",
    icon: Webhook,
    color: "#38bdf8",
  },
  validation: {
    title: "Validate",
    description: "Check required fields and schema",
    group: "Receive & prepare",
    icon: ShieldCheck,
    color: "#38bdf8",
  },
  normalization: {
    title: "Normalize",
    description: "Map source fields into a common shape",
    group: "Receive & prepare",
    icon: Shuffle,
    color: "#38bdf8",
  },
  fingerprint: {
    title: "Deduplicate",
    description: "Identify repeated alerts",
    group: "Receive & prepare",
    icon: Fingerprint,
    color: "#38bdf8",
  },
  playbook: {
    title: "Resolve playbook",
    description: "Select investigation instructions",
    group: "Gather context",
    icon: BookOpen,
    color: "#a78bfa",
  },
  knowledge_base: {
    title: "Knowledge enrichment",
    description: "Retrieve tenant documents and CIDR context",
    group: "Gather context",
    icon: Database,
    color: "#a78bfa",
  },
  enrichment_action: {
    title: "Registered action",
    description: "Call an existing context provider",
    group: "Gather context",
    icon: Plug,
    color: "#a78bfa",
  },
  tool_call: {
    title: "Tool call",
    description: "Call an approved REST or MCP tool",
    group: "Gather context",
    icon: Plug,
    color: "#a78bfa",
  },
  correlation: {
    title: "Correlate & cluster",
    description: "Group alerts with shared evidence",
    group: "Investigate",
    icon: Network,
    color: "#fbbf24",
  },
  llm_analysis: {
    title: "Analyze",
    description: "Produce a validated analysis result",
    group: "Investigate",
    icon: BrainCircuit,
    color: "#fbbf24",
  },
  llm_tools: {
    title: "Agent",
    description: "Investigate with a bounded set of tools",
    group: "Investigate",
    icon: Bot,
    color: "#fbbf24",
  },
  decision: {
    title: "Condition",
    description: "Route using a typed comparison",
    group: "Control flow",
    icon: GitBranch,
    color: "#34d399",
  },
  fork: {
    title: "Parallel branches",
    description: "Start independent paths",
    group: "Control flow",
    icon: Split,
    color: "#34d399",
  },
  join: {
    title: "Join branches",
    description: "Collect every branch in order",
    group: "Control flow",
    icon: Merge,
    color: "#34d399",
  },
  catch: {
    title: "Catch & fallback",
    description: "Handle a failure explicitly",
    group: "Control flow",
    icon: LifeBuoy,
    color: "#fb923c",
  },
  complete: {
    title: "Output",
    description: "Validate the result and finish",
    group: "Finish",
    icon: CheckCircle2,
    color: "#34d399",
  },
  dead_letter: {
    title: "Dead letter",
    description: "Retain a failed alert for inspection",
    group: "Finish",
    icon: ArchiveX,
    color: "#fb7185",
  },
};

export function NodeGallery({
  catalog,
  onAdd,
  hasEntry,
}: {
  catalog: string[];
  onAdd: (type: string) => void;
  hasEntry: boolean;
}) {
  const [search, setSearch] = useState("");
  const items = catalog.filter((type) => {
    const item = NODE_DESIGN[type];
    return (
      item &&
      `${item.title} ${item.description}`
        .toLowerCase()
        .includes(search.toLowerCase())
    );
  });
  return (
    <aside
      className="rounded-xl border border-border/70 bg-card"
      aria-label="Node gallery"
    >
      <div className="border-b border-border/60 p-4">
        <h2 className="text-sm font-semibold">Add a step</h2>
        <p className="mt-1 text-xs text-muted-foreground">
          Click a node, then connect its ports.
        </p>
        <label className="mt-3 flex items-center gap-2 rounded-lg border border-border bg-background px-2.5">
          <Search size={14} className="text-muted-foreground" />
          <input
            aria-label="Search nodes"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Find a node…"
            className="min-w-0 w-full bg-transparent py-2 text-xs outline-none"
          />
        </label>
      </div>
      <div className="max-h-[240px] overflow-y-auto p-2 md:max-h-[590px]">
        {[
          "Receive & prepare",
          "Gather context",
          "Investigate",
          "Control flow",
          "Finish",
        ]
          .filter((group) =>
            items.some((type) => NODE_DESIGN[type].group === group),
          )
          .map((group) => (
            <section key={group} className="mb-3">
              <h3 className="px-2 pb-1 pt-3 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
                {group}
              </h3>
              {Object.keys(NODE_DESIGN)
                .filter(
                  (type) =>
                    items.includes(type) && NODE_DESIGN[type].group === group,
                )
                .map((type) => {
                  const item = NODE_DESIGN[type];
                  const Icon = item.icon;
                  return (
                    <button
                      key={type}
                      disabled={type === "entry" && hasEntry}
                      onClick={() => onAdd(type)}
                      aria-label={`Add ${item.title}`}
                      className="group flex w-full items-center gap-2.5 rounded-lg p-2.5 text-left transition-colors hover:bg-accent focus-visible:outline-2 focus-visible:outline-primary disabled:opacity-35"
                    >
                      <span
                        className="rounded-lg p-2"
                        style={{
                          background: `${item.color}14`,
                          color: item.color,
                        }}
                      >
                        <Icon size={17} />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block text-xs font-medium">
                          {item.title}
                        </span>
                        <span className="mt-0.5 block text-[10px] leading-4 text-muted-foreground">
                          {item.description}
                        </span>
                      </span>
                      <Plus
                        size={13}
                        className="shrink-0 text-muted-foreground opacity-0 group-hover:opacity-100"
                      />
                    </button>
                  );
                })}
            </section>
          ))}
        {!items.length && (
          <p className="p-3 text-xs text-muted-foreground">
            No matching nodes.
          </p>
        )}
      </div>
    </aside>
  );
}

const inputClass =
  "w-full rounded-lg border border-input bg-background px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-primary";
export type AvailableConnector = {
  connector_code: string;
  name: string;
  tools: {
    name: string;
    input_schema: { properties?: Record<string, unknown> };
  }[];
};
export function NodeFields({
  node,
  value,
  onChange,
  profiles,
  connectors = [],
  definitions = [],
}: {
  node: FlowNode;
  value: Record<string, unknown>;
  onChange: (value: Record<string, unknown>) => void;
  profiles: { profile_code: string; model: string }[];
  connectors?: AvailableConnector[];
  definitions?: { kind: string; code: string; name: string }[];
}) {
  const set = (key: string, item: unknown) =>
    onChange({ ...value, [key]: item });
  const text = (key: string, label: string, placeholder = "") => (
    <label
      key={key}
      className="block space-y-1.5 text-xs text-muted-foreground"
    >
      {label}
      <input
        className={inputClass}
        value={String(value[key] ?? "")}
        placeholder={placeholder}
        onChange={(e) => {
          if (!e.target.value) {
            const next = { ...value };
            delete next[key];
            onChange(next);
          } else set(key, e.target.value);
        }}
      />
    </label>
  );
  const number = (
    key: string,
    label: string,
    fallback: number,
    min: number,
    max: number,
  ) => (
    <label
      key={key}
      className="block space-y-1.5 text-xs text-muted-foreground"
    >
      {label}
      <input
        type="number"
        step={key === "threshold" ? 0.01 : 1}
        min={min}
        max={max}
        className={inputClass}
        value={Number(value[key] ?? fallback)}
        onChange={(e) => set(key, e.target.valueAsNumber)}
      />
    </label>
  );
  const list = (key: string, label: string) => (
    <label
      key={key}
      className="block space-y-1.5 text-xs text-muted-foreground"
    >
      {label}
      <textarea
        className={inputClass}
        rows={3}
        value={
          Array.isArray(value[key]) ? (value[key] as string[]).join("\n") : ""
        }
        onChange={(e) => set(key, e.target.value.split("\n").filter(Boolean))}
      />
      <span className="block text-[10px]">One value per line.</span>
    </label>
  );
  return (
    <div className="space-y-4">
      {["agent", "playbook_call"].includes(node.type) && (
        <>
          <label className="block space-y-1.5 text-xs">
            {node.type === "agent" ? "Agent" : "Playbook"}
            <select
              className={inputClass}
              value={String(value.definition_code || "")}
              onChange={(e) => set("definition_code", e.target.value)}
            >
              <option value="">Select a published definition</option>
              {definitions
                .filter(
                  (item) =>
                    item.kind ===
                    (node.type === "agent" ? "agent" : "playbook"),
                )
                .map((item) => (
                  <option key={item.code} value={item.code}>
                    {item.name}
                  </option>
                ))}
            </select>
          </label>
          {value.revision
            ? number("revision", "Pinned revision", 1, 1, 100000)
            : null}
        </>
      )}
      {node.type === "playbook_selector" && (
        <>
          <label className="block space-y-1.5 text-xs">
            Selection mode
            <select
              className={inputClass}
              value={String(value.mode || "static")}
              onChange={(e) => set("mode", e.target.value)}
            >
              <option value="static">Static mapping</option>
              <option value="model">Static first, then model</option>
            </select>
          </label>
          <MappingFields
            legend="Static routing · alert type → playbook code"
            targetLabel="Alert type"
            sourceLabel="Playbook code"
            value={(value.mappings || {}) as Record<string, string>}
            onChange={(mapping) => set("mappings", mapping)}
          />
          <label className="block space-y-1.5 text-xs">
            Fallback playbook
            <select
              className={inputClass}
              value={String(value.fallback || "")}
              onChange={(e) => set("fallback", e.target.value)}
            >
              <option value="">Select required fallback</option>
              {definitions
                .filter((item) => item.kind === "playbook")
                .map((item) => (
                  <option key={item.code} value={item.code}>
                    {item.name}
                  </option>
                ))}
            </select>
          </label>
          {value.mode === "model" && (
            <>
              {text("profile_code", "Routing model profile")}
              {list("candidates", "Candidate playbook codes")}
              {number("threshold", "Minimum selection confidence", 0.7, 0, 1)}
            </>
          )}
        </>
      )}
      {["kb_deterministic", "kb_semantic"].includes(node.type) &&
        number("top_k", "Maximum retrieved chunks", 5, 1, 20)}
      {node.type === "persist_analysis" &&
        text("input_path", "Analysis result path", "nodes.analysis.output")}
      {node.type === "notify_jira" &&
        text(
          "input_path",
          "Result to notify (optional)",
          "alert.alert_analysis",
        )}
      {node.type === "webhook" && (
        <>
          {text("connector_code", "Approved connector code")}
          {text("tool_name", "Approved tool")}
          {text("input_path", "Output path", "alert.alert_analysis")}
        </>
      )}
      {node.type === "entry" && (
        <>
          <p className="rounded-lg bg-sky-500/10 p-3 text-xs leading-5 text-muted-foreground">
            The entry receives an authenticated alert. Connect its success port
            to the first processing step.
          </p>
          <label className="block space-y-1.5 text-xs text-muted-foreground">
            Input mode
            <select
              className={inputClass}
              value={String(value.input_mode || "envelope")}
              onChange={(e) => set("input_mode", e.target.value)}
            >
              <option value="envelope">Alert envelope</option>
              <option value="raw">Raw provider JSON</option>
            </select>
          </label>
          {value.input_mode === "raw" && (
            <>
              {text("source_system", "Source system", "SPLUNK")}
              {text(
                "alert_type",
                "Alert type",
                "splunk.notable.endpoint_malware",
              )}
              {text(
                "timestamp_path",
                "Original timestamp path",
                "result._time",
              )}
            </>
          )}
        </>
      )}
      {["validation", "normalization"].includes(node.type) && (
        <>
          {text(
            "schema_id",
            "Schema ID (optional)",
            "Use the alert type’s active schema",
          )}
          {value.schema_id
            ? number("schema_version", "Schema revision", 1, 1, 100000)
            : null}
          {node.type === "validation" &&
            list("critical_fields", "Required normalized field names")}
          <MappingFields
            value={(value.field_mapping || {}) as Record<string, string>}
            onChange={(mapping) => set("field_mapping", mapping)}
          />
        </>
      )}
      {node.type === "fingerprint" && (
        <>
          {list("fields", "Fingerprint field paths")}
          {number("window_hours", "Duplicate window (hours)", 24, 1, 168)}
        </>
      )}
      {node.type === "playbook" && (
        <>
          {text("playbook_id", "Playbook ID", "Resolve from alert type")}
          {value.playbook_id
            ? number("version", "Playbook revision", 1, 1, 100000)
            : null}
        </>
      )}
      {node.type === "knowledge_base" && (
        <>
          <div className="rounded-lg border border-border p-3 text-xs">
            <div className="font-medium">Deterministic evidence</div>
            <p className="mt-1 text-muted-foreground">
              Exact entities, CIDR containment, and lexical matching.
            </p>
          </div>
          <label className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              className="mt-1"
              checked={value.retrieval_mode === "hybrid"}
              onChange={(e) =>
                set(
                  "retrieval_mode",
                  e.target.checked ? "hybrid" : "deterministic",
                )
              }
            />
            <span>
              Include semantic evidence
              <span className="mt-1 block text-xs text-muted-foreground">
                Mem0 + Qdrant. Deterministic evidence remains available when
                semantic retrieval is unavailable.
              </span>
            </span>
          </label>
          {number("top_k", "Maximum retrieved chunks", 5, 1, 20)}
        </>
      )}
      {node.type === "enrichment_action" &&
        text("action_code", "Registered action code")}
      {node.type === "tool_call" && (
        <>
          <label className="block space-y-1.5 text-xs text-muted-foreground">
            Connector
            <select
              className={inputClass}
              value={String(value.connector_code || "")}
              onChange={(e) =>
                onChange({
                  ...value,
                  connector_code: e.target.value,
                  tool_name: "",
                })
              }
            >
              <option value="">Select an authorized connector</option>
              {connectors.map((c) => (
                <option key={c.connector_code} value={c.connector_code}>
                  {c.name}
                </option>
              ))}
            </select>
          </label>
          <label className="block space-y-1.5 text-xs text-muted-foreground">
            Tool
            <select
              className={inputClass}
              value={String(value.tool_name || "")}
              onChange={(e) => set("tool_name", e.target.value)}
            >
              <option value="">Select an approved tool</option>
              {connectors
                .find((c) => c.connector_code === value.connector_code)
                ?.tools.map((t) => (
                  <option key={t.name}>{t.name}</option>
                ))}
            </select>
          </label>
          <MappingFields
            value={(value.argument_paths || {}) as Record<string, string>}
            onChange={(mapping) => set("argument_paths", mapping)}
          />
          <p className="text-xs text-muted-foreground">
            Map argument names to normalized alert paths. When connected to an
            agent, the agent supplies validated arguments.
          </p>
        </>
      )}
      {node.type === "correlation" && (
        <>
          {text("group", "Correlation group (empty = tenant shared pool)")}
          {number("lookback_hours", "Lookback (hours)", 24, 1, 24)}
          {number("grouping_hours", "Grouping window (hours)", 24, 1, 24)}
        </>
      )}
      {node.type.startsWith("llm_") && (
        <>
          <label className="block space-y-1.5 text-xs text-muted-foreground">
            LLM profile
            <select
              className={inputClass}
              value={String(value.profile_code || "")}
              onChange={(e) => set("profile_code", e.target.value)}
            >
              <option value="">Select a tested profile</option>
              {profiles.map((p) => (
                <option key={p.profile_code} value={p.profile_code}>
                  {p.profile_code} · {p.model}
                </option>
              ))}
            </select>
          </label>
          <label className="block space-y-1.5 text-xs text-muted-foreground">
            Instructions
            <textarea
              rows={5}
              className={inputClass}
              value={String(value.prompt || "")}
              onChange={(e) => set("prompt", e.target.value)}
              placeholder="Use only supplied evidence. Explain uncertainty."
            />
          </label>
          {node.type === "llm_tools" && (
            <>
              <fieldset className="space-y-3 rounded-lg border p-3">
                <legend className="px-1 text-xs font-medium">
                  Approved capabilities
                </legend>
                <p className="text-xs text-muted-foreground">
                  Select up to ten tools or reusable investigators. The agent
                  cannot call anything outside this list.
                </p>
                {[
                  { code: "alert_evidence", name: "Current alert evidence" },
                  {
                    code: "cluster_evidence",
                    name: "Related cluster evidence",
                  },
                  { code: "knowledge_base", name: "Search tenant knowledge" },
                  ...connectors.flatMap((c) =>
                    c.tools.map((t) => ({
                      code: `connector:${c.connector_code}:${t.name}`,
                      name: `${c.name} · ${t.name}`,
                    })),
                  ),
                  ...definitions
                    .filter((d) => ["agent", "playbook"].includes(d.kind))
                    .map((d) => ({
                      code: `${d.kind}:${d.code}`,
                      name: `${d.kind === "agent" ? "Agent" : "Playbook"} · ${d.name}`,
                    })),
                  ...((value.tools || []) as string[])
                    .filter(
                      (code) =>
                        ![
                          "alert_evidence",
                          "cluster_evidence",
                          "knowledge_base",
                        ].includes(code) &&
                        !connectors.some((c) =>
                          c.tools.some(
                            (t) =>
                              code ===
                              `connector:${c.connector_code}:${t.name}`,
                          ),
                        ) &&
                        !definitions.some(
                          (d) => code === `${d.kind}:${d.code}`,
                        ),
                    )
                    .map((code) => ({
                      code,
                      name: `Unavailable capability · ${code}`,
                    })),
                ].map((tool) => {
                  const chosen = (value.tools || []) as string[];
                  return (
                    <label
                      key={tool.code}
                      className="flex items-start gap-2 text-xs"
                    >
                      <input
                        type="checkbox"
                        className="mt-0.5"
                        checked={chosen.includes(tool.code)}
                        disabled={
                          !chosen.includes(tool.code) && chosen.length >= 10
                        }
                        onChange={(e) =>
                          set(
                            "tools",
                            e.target.checked
                              ? [...chosen, tool.code]
                              : chosen.filter((code) => code !== tool.code),
                          )
                        }
                      />
                      <span>{tool.name}</span>
                    </label>
                  );
                })}
              </fieldset>
              {number("max_rounds", "Maximum model rounds", 5, 1, 5)}
              {number("max_calls", "Maximum tool calls", 10, 1, 10)}
            </>
          )}
        </>
      )}
      {node.type === "decision" && (
        <>
          {text(
            "path",
            "Input field path",
            "alert.normalized_payload.source.ip",
          )}
          <label className="block space-y-1.5 text-xs text-muted-foreground">
            Comparison
            <select
              className={inputClass}
              value={String(value.operator || "exists")}
              onChange={(e) => set("operator", e.target.value)}
            >
              {Object.entries({
                exists: "Exists",
                eq: "Equals",
                ne: "Does not equal",
                in: "Is in list",
                contains: "Contains",
                gt: "Greater than",
                gte: "Greater than or equal",
                lt: "Less than",
                lte: "Less than or equal",
                cidr_contains: "IP is inside CIDR",
              }).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          {value.operator !== "exists" && (
            <TypedValue
              value={value.value}
              onChange={(item) => set("value", item)}
            />
          )}
        </>
      )}
      {node.type === "fork" && (
        <>
          {list("branches", "Branch names (ordered)")}
          {text("join_id", "Paired join node ID")}
        </>
      )}
      {node.type === "join" && text("fork_id", "Paired fork node ID")}
      {["complete", "dead_letter"].includes(node.type) && (
        <p className="text-xs leading-5 text-muted-foreground">
          This is a terminal node. It has no outgoing execution connections.
        </p>
      )}
      {node.type === "complete" &&
        text(
          "output_path",
          "Structured result path (optional)",
          "nodes.agent.output.result",
        )}
      {node.type === "catch" && (
        <p className="text-xs leading-5 text-muted-foreground">
          Set the replacement and its output schema in advanced configuration.
          The original failure is retained.
        </p>
      )}
      {["llm_analysis", "llm_tools", "complete"].includes(node.type) && (
        <OutputSchemaFields
          value={value.output_schema as Record<string, unknown> | undefined}
          onChange={(schema) => set("output_schema", schema)}
        />
      )}
    </div>
  );
}

function OutputSchemaFields({
  value,
  onChange,
}: {
  value?: Record<string, unknown>;
  onChange: (value: Record<string, unknown>) => void;
}) {
  const properties = (value?.properties || {}) as Record<
    string,
    Record<string, unknown>
  >;
  const required = (value?.required || []) as string[];
  const update = (
    next: Record<string, Record<string, unknown>>,
    keys = required,
  ) =>
    onChange({
      ...value,
      type: "object",
      properties: next,
      required: keys,
      additionalProperties: false,
    });
  return (
    <fieldset className="space-y-2 rounded-lg border border-border/60 p-3">
      <legend className="px-1 text-xs font-medium">Structured output</legend>
      {!value && (
        <p className="text-[11px] text-muted-foreground">
          Analysis uses the standard analysis contract unless you define fields
          here. Output nodes require an explicit contract when storing an agent
          result.
        </p>
      )}
      {Object.entries(properties).map(([name, schema], index) => (
        <div
          key={index}
          className="space-y-1 rounded border border-border/50 p-2"
        >
          <input
            aria-label={`Output field ${index + 1}`}
            className={inputClass}
            value={name}
            onChange={(e) =>
              update(
                Object.fromEntries(
                  Object.entries(properties).map(([key, item]) => [
                    key === name ? e.target.value : key,
                    item,
                  ]),
                ),
                required.map((key) => (key === name ? e.target.value : key)),
              )
            }
          />
          <div className="flex items-center gap-2">
            <select
              aria-label={`Output type ${index + 1}`}
              className={`${inputClass} min-w-0`}
              value={String(schema.type || "string")}
              onChange={(e) =>
                update({
                  ...properties,
                  [name]: {
                    type: e.target.value,
                    ...(e.target.value === "array"
                      ? { items: { type: "string" } }
                      : {}),
                  },
                })
              }
            >
              {[
                "string",
                "number",
                "integer",
                "boolean",
                "array",
                "object",
              ].map((type) => (
                <option key={type}>{type}</option>
              ))}
            </select>
            <label className="flex items-center gap-1 text-[10px]">
              <input
                type="checkbox"
                checked={required.includes(name)}
                onChange={(e) =>
                  update(
                    properties,
                    e.target.checked
                      ? [...required, name]
                      : required.filter((key) => key !== name),
                  )
                }
              />
              Required
            </label>
            <button
              aria-label={`Remove output field ${index + 1}`}
              onClick={() =>
                update(
                  Object.fromEntries(
                    Object.entries(properties).filter(([key]) => key !== name),
                  ),
                  required.filter((key) => key !== name),
                )
              }
            >
              ×
            </button>
          </div>
        </div>
      ))}
      <button
        type="button"
        className="rounded border border-dashed px-2 py-1.5 text-xs"
        onClick={() => {
          const key = `field_${Object.keys(properties).length + 1}`;
          update({ ...properties, [key]: { type: "string" } }, [
            ...required,
            key,
          ]);
        }}
      >
        + Output field
      </button>
      <p className="text-[10px] text-muted-foreground">
        Nested schemas and enum values are available in advanced configuration.
      </p>
    </fieldset>
  );
}

function TypedValue({
  value,
  onChange,
}: {
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const kind = Array.isArray(value)
    ? "list"
    : typeof value === "number"
      ? "number"
      : typeof value === "boolean"
        ? "boolean"
        : "text";
  return (
    <div className="space-y-2">
      <label className="block text-xs text-muted-foreground">
        Value type
        <select
          className={`${inputClass} mt-1.5`}
          value={kind}
          onChange={(e) =>
            onChange(
              e.target.value === "number"
                ? 0
                : e.target.value === "boolean"
                  ? true
                  : e.target.value === "list"
                    ? []
                    : "",
            )
          }
        >
          <option value="text">Text</option>
          <option value="number">Number</option>
          <option value="boolean">Boolean</option>
          <option value="list">Text list</option>
        </select>
      </label>
      {kind === "boolean" ? (
        <label className="flex gap-2 text-xs">
          <input
            type="checkbox"
            checked={Boolean(value)}
            onChange={(e) => onChange(e.target.checked)}
          />
          True
        </label>
      ) : (
        <input
          aria-label="Comparison value"
          className={inputClass}
          type={kind === "number" ? "number" : "text"}
          value={Array.isArray(value) ? value.join(", ") : String(value ?? "")}
          onChange={(e) =>
            onChange(
              kind === "number"
                ? e.target.valueAsNumber
                : kind === "list"
                  ? e.target.value
                      .split(",")
                      .map((v) => v.trim())
                      .filter(Boolean)
                  : e.target.value,
            )
          }
        />
      )}
    </div>
  );
}

function MappingFields({
  value,
  onChange,
  legend = "Field mapping · target → source path",
  targetLabel = "Target field",
  sourceLabel = "Source path",
}: {
  value: Record<string, string>;
  onChange: (value: Record<string, string>) => void;
  legend?: string;
  targetLabel?: string;
  sourceLabel?: string;
}) {
  const entries = Object.entries(value);
  return (
    <fieldset className="space-y-2">
      <legend className="mb-2 text-xs text-muted-foreground">{legend}</legend>
      {entries.map(([target, source], i) => (
        <div key={i} className="flex gap-1">
          <input
            aria-label={`${targetLabel} ${i + 1}`}
            className={`${inputClass} min-w-0`}
            value={target}
            onChange={(e) =>
              onChange(
                Object.fromEntries(
                  entries.map((pair, index) =>
                    index === i ? [e.target.value, source] : pair,
                  ),
                ),
              )
            }
          />
          <input
            aria-label={`${sourceLabel} ${i + 1}`}
            className={`${inputClass} min-w-0`}
            value={source}
            onChange={(e) => onChange({ ...value, [target]: e.target.value })}
          />
          <button
            type="button"
            aria-label={`Remove mapping ${i + 1}`}
            onClick={() =>
              onChange(
                Object.fromEntries(entries.filter((_, index) => index !== i)),
              )
            }
            className="px-1 text-muted-foreground"
          >
            ×
          </button>
        </div>
      ))}
      <button
        type="button"
        className="rounded-lg border border-dashed px-3 py-2 text-xs"
        onClick={() =>
          onChange({ ...value, [`field_${entries.length + 1}`]: "" })
        }
      >
        + Add mapping
      </button>
    </fieldset>
  );
}
