"use client";

import { useMemo, useState } from "react";
import {
  Background,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  type NodeProps,
  type Viewport,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  BrainCircuit,
  ChevronDown,
  ChevronRight,
  Maximize2,
} from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { NODE_DESIGN } from "@/components/workflow-node-kit";
import { studioButton } from "@/components/workflow-library";
import { formatDurationMs } from "@/lib/duration";
import { formatLocaleDateTime } from "@/lib/datetime";
import {
  callsFor,
  isRecordedJob,
  executionMap,
  orderedNodes,
  stepId,
  unattributedCalls,
  type Execution,
  type ExecutionNode,
  type ExecutionNodeData,
  type ExecutionRun,
} from "@/lib/workflow-execution";
import { outputPorts } from "@/lib/workflows";

function tone(state: string) {
  if (state === "SUCCEEDED") return "border-emerald-500/40 text-emerald-400";
  if (["FAILED", "UNCERTAIN", "CANCELLED"].includes(state))
    return "border-red-500/40 text-red-400";
  if (["RUNNING", "WAITING", "PENDING"].includes(state))
    return "border-amber-500/40 text-amber-300";
  return "border-border text-muted-foreground";
}

function ExecutionCard({ data }: NodeProps<ExecutionNode>) {
  const design =
      NODE_DESIGN[
        data.definition?.type ||
          (data.callKind === "python"
            ? "python_tool"
            : data.callKind === "tool"
              ? "tool_call"
              : "llm_analysis")
      ],
    Icon = design?.icon || BrainCircuit;
  if (data.kind === "run")
    return (
      <div className="h-full w-full rounded-xl border-2 border-dashed border-violet-400/30 bg-violet-500/[0.025]">
        <div className="flex h-12 items-center gap-3 px-4 text-xs">
          <strong>{data.label}</strong>
          <span className={tone(data.state)}>{data.state}</span>
          <span className="text-muted-foreground">
            {data.run.parent_run_id ? "Pinned subflow" : "Pinned workflow"} ·{" "}
            {data.run.release_version}
          </span>
        </div>
      </div>
    );
  const ports = data.definition ? outputPorts(data.definition) : [];
  return (
    <div
      className={`h-full w-full overflow-hidden rounded-xl border bg-card/95 shadow-sm ${tone(data.state)}`}
    >
      {data.kind === "step" && (
        <Handle type="target" position={Position.Left} isConnectable={false} />
      )}
      <button
        type="button"
        className="nodrag flex w-full gap-3 p-3 text-left text-foreground hover:bg-muted/50"
        onClick={data.inspect}
        aria-label={`Inspect ${data.label} in ${data.run.definition_ref || data.run.run_id}`}
      >
        <Icon
          className="mt-1 size-5 shrink-0"
          style={{ color: design?.color }}
        />
        <span className="min-w-0">
          <strong className="block truncate text-sm">{data.label}</strong>
          <span className="block truncate text-[11px] text-muted-foreground">
            {data.kind === "call"
              ? `${data.callKind} delivery metadata`
              : design?.title || data.definition?.type}
          </span>
          <span className={`block text-[10px] ${tone(data.state)}`}>
            {data.state}{" "}
            {data.job?.node_elapsed_ms != null && data.kind === "step"
              ? `· ${formatDurationMs(data.job.node_elapsed_ms)}`
              : ""}
          </span>
        </span>
      </button>
      {!!data.childCount && (
        <button
          type="button"
          onClick={data.toggle}
          aria-expanded={data.expanded}
          className="nodrag flex w-full items-center gap-2 border-t px-3 py-1 text-[10px] text-muted-foreground hover:text-foreground"
        >
          {data.expanded ? (
            <ChevronDown className="size-3" />
          ) : (
            <ChevronRight className="size-3" />
          )}
          {data.childCount} subflows / calls ·{" "}
          {data.expanded ? "collapse" : "expand"}
        </button>
      )}
      {ports.map((port, i) => (
        <Handle
          key={port}
          id={port}
          type="source"
          position={Position.Right}
          isConnectable={false}
          style={{ top: `${((i + 1) / (ports.length + 1)) * 100}%` }}
        />
      ))}
    </div>
  );
}
const nodeTypes = { execution: ExecutionCard };

function Json({ value }: { value: unknown }) {
  return (
    <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-muted/40 p-3 font-mono text-xs">
      {JSON.stringify(value ?? { state: "Not recorded" }, null, 2)}
    </pre>
  );
}

function Inspector({
  data,
  close,
}: {
  data: ExecutionNodeData | null;
  close: () => void;
}) {
  const recorded = isRecordedJob(data?.job);
  return (
    <Dialog
      open={Boolean(data)}
      onOpenChange={(open) => {
        if (!open) close();
      }}
    >
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-3xl">
        <DialogTitle>{data?.label || "Recorded step"}</DialogTitle>
        <DialogDescription className="sr-only">
          Recorded, redacted execution details. Closing returns to the complete
          pipeline.
        </DialogDescription>
        {data && (
          <>
            <p className="break-all text-xs text-muted-foreground">
              {data.job?.definition_ref || data.run.definition_ref} ·{" "}
              {data.state} · run application {data.run.release_version} /{" "}
              {data.run.release_sha?.slice(0, 8)}
            </p>
            <p className="text-xs text-muted-foreground">
              Node execution release:{" "}
              {recorded && data.job?.release_version
                ? `${data.job.release_version} / ${data.job.release_sha?.slice(0, 8) || "SHA unavailable"}`
                : "Not recorded"}
            </p>
            {data.kind === "call" ? (
              <>
                <p className="text-sm">
                  Recorded call metadata. Raw model responses and protected tool
                  payloads are not exposed by this API.
                </p>
                <Json value={data.call} />
              </>
            ) : (
              <>
                <p className="text-sm">
                  Route: {data.job?.port || "Not selected"} · Attempts:{" "}
                  {recorded ? (data.job?.attempt_count ?? "Not recorded") : 0} ·
                  Active execution:{" "}
                  {data.job?.execution_duration_ms == null
                    ? "Not recorded"
                    : formatDurationMs(data.job.execution_duration_ms)}
                </p>
                {data.job?.first_started_at && (
                  <p className="text-xs text-muted-foreground">
                    Started {formatLocaleDateTime(data.job.first_started_at)}
                    {data.job.completed_at
                      ? ` · completed ${formatLocaleDateTime(data.job.completed_at)}`
                      : ""}
                  </p>
                )}
                <section className="space-y-2">
                  <h3 className="font-semibold">Safe input snapshot</h3>
                  <Json value={data.job?.input_snapshot} />
                </section>
                <section className="space-y-2">
                  <h3 className="font-semibold">Safe output snapshot</h3>
                  <Json value={data.job?.output_snapshot ?? data.job?.output} />
                </section>
                <section className="space-y-2">
                  <h3 className="font-semibold">
                    Decisions, routing and errors
                  </h3>
                  <Json
                    value={{
                      selection: data.job?.selection,
                      decisions: data.job?.decisions,
                      error: data.job?.error,
                      error_input_snapshot: data.job?.error_input_snapshot,
                      wait_reason: data.job?.wait_reason,
                    }}
                  />
                </section>
                {recorded && (
                  <details>
                    <summary className="cursor-pointer text-sm">
                      Recorded execution metadata
                    </summary>
                    <Json value={data.job} />
                  </details>
                )}
                {!recorded && (
                  <p className="text-sm text-muted-foreground">
                    This pinned step has no recorded execution. No inputs,
                    outputs or successful result have been inferred.
                  </p>
                )}
              </>
            )}
            <p className="text-xs text-muted-foreground">
              Run: {data.run.run_id} · Node:{" "}
              {data.definition?.id || data.job?.node_id}. Snapshots retain the
              existing redaction and size limits. Attempt counts do not imply
              that separate historical attempt payloads were retained.
            </p>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

export function WorkflowExecutionMap({ execution }: { execution: Execution }) {
  const [viewport, setViewport] = useState<Viewport>();
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set()),
    [view, setView] = useState<"map" | "steps">("map"),
    [full, setFull] = useState(false);
  const [selected, setSelected] = useState<ExecutionNodeData | null>(null);
  const map = useMemo(
    () => executionMap(execution, collapsed),
    [execution, collapsed],
  );
  const inspect = (data: ExecutionNodeData) => setSelected(data);
  const nodes = useMemo(
    () =>
      map.nodes.map((node) => ({
        ...node,
        data: {
          ...node.data,
          inspect: () => setSelected(node.data),
          toggle: () =>
            setCollapsed((previous) => {
              const next = new Set(previous);
              if (next.has(node.id)) next.delete(node.id);
              else next.add(node.id);
              return next;
            }),
        },
      })),
    [map],
  );
  const selectedRun = execution.runs.find(
    (run) => run.run_id === selected?.run.run_id,
  );
  const selectedJob = selectedRun?.nodes?.find(
    (job) => job.job_id === selected?.job?.job_id,
  );
  const selectedCall = selectedRun
    ? [
        ...callsFor(selectedRun, selectedJob),
        ...unattributedCalls(selectedRun),
      ].find((call) =>
        [
          `${stepId(selectedRun.run_id, selectedJob?.node_id || "")}:${call.id}`,
          `unlinked:${selectedRun.run_id}:${call.id}`,
        ].includes(selected?.recordKey || ""),
      )
    : undefined;
  const currentSelection =
    selected && selectedRun
      ? {
          ...selected,
          run: selectedRun,
          job: selectedJob,
          ...(selected.kind === "call" && selectedCall
            ? {
                call: selectedCall.call,
                state: String(
                  selectedCall.call.state ||
                    (selected.callKind === "model" ? "SUCCEEDED" : "RECORDED"),
                ),
              }
            : selected.kind === "step"
              ? { state: selectedJob?.state || "NOT_REACHED" }
              : {}),
        }
      : null;
  function outline(
    run: ExecutionRun,
    prefix = "",
    ancestry = new Set<string>(),
  ): React.ReactNode {
    if (ancestry.has(run.run_id)) return null;
    const visited = new Set([...ancestry, run.run_id]);
    return (
      <ol
        className="space-y-3 border-l border-violet-400/30 pl-4"
        aria-label={`Steps in ${run.definition_ref || run.run_id}`}
      >
        {orderedNodes(run).nodes.map((definition, i) => {
          const job = run.nodes?.find((job) => job.node_id === definition.id),
            number = `${prefix}${i + 1}`;
          const data: ExecutionNodeData = {
            kind: "step",
            recordKey: stepId(run.run_id, definition.id),
            run,
            definition,
            job,
            label: definition.label || definition.id,
            state: job?.state || "NOT_REACHED",
          };
          const children = execution.runs.filter(
            (child) =>
              child.parent_run_id === run.run_id &&
              isRecordedJob(job) &&
              child.parent_job_id === job?.job_id,
          );
          return (
            <li key={stepId(run.run_id, definition.id)} className="space-y-3">
              <button
                onClick={() => inspect(data)}
                aria-label={`Step ${number} ${data.label} in ${run.definition_ref || run.run_id} · ${data.state}`}
                className="flex w-full flex-wrap items-center gap-3 rounded-lg border p-3 text-left hover:bg-muted/40"
              >
                <span className="font-mono text-xs text-muted-foreground">
                  {number}
                </span>
                <strong className="text-sm">{data.label}</strong>
                <span className={`text-xs ${tone(data.state)}`}>
                  {data.state}
                </span>
                <span className="text-xs text-muted-foreground">
                  {NODE_DESIGN[definition.type]?.title || definition.type}
                </span>
              </button>
              {children.map((child, c) => (
                <section key={child.run_id} className="space-y-2 pl-3">
                  <h3 className="text-xs text-violet-300">
                    {child.definition_ref || child.run_id} · {child.state}
                  </h3>
                  {outline(
                    child,
                    `${number}.${children.length > 1 ? `${c + 1}.` : ""}`,
                    visited,
                  )}
                </section>
              ))}
              {callsFor(run, job).map(({ kind, call, id }) => (
                <button
                  key={id}
                  className="ml-4 block rounded border px-3 py-2 text-left text-xs hover:bg-muted/40"
                  onClick={() =>
                    inspect({
                      kind: "call",
                      recordKey: `${stepId(run.run_id, definition.id)}:${id}`,
                      run,
                      job,
                      call,
                      callKind: kind,
                      label: `${kind} call`,
                      state: String(
                        call.state ||
                          (kind === "model" ? "SUCCEEDED" : "RECORDED"),
                      ),
                    })
                  }
                >
                  {kind} call ·{" "}
                  {String(
                    call.model ||
                      call.tool_name ||
                      call.tool_code ||
                      "recorded",
                  )}
                </button>
              ))}
            </li>
          );
        })}
      </ol>
    );
  }
  const content = (
    <>
      <div className="flex flex-wrap items-center gap-2 border-b p-3">
        <div className="mr-auto">
          <h2 className="font-semibold">Complete execution</h2>
          <p className="text-xs text-muted-foreground">
            {execution.runs.length} loaded flows · all subflows expanded by
            default · branches may run in parallel
          </p>
        </div>
        <div role="group" aria-label="Execution view" className="flex gap-2">
          <button
            className={studioButton}
            aria-pressed={view === "map"}
            onClick={() => setView("map")}
          >
            Execution map
          </button>
          <button
            className={studioButton}
            aria-pressed={view === "steps"}
            onClick={() => setView("steps")}
          >
            Step by step
          </button>
        </div>
        {view === "map" && (
          <>
            <button
              className={studioButton}
              onClick={() => setCollapsed(new Set())}
            >
              Expand all
            </button>
            <button
              className={studioButton}
              onClick={() => setCollapsed(new Set(map.expandable))}
            >
              Collapse subflows
            </button>
          </>
        )}
        <button
          className={studioButton}
          aria-expanded={full}
          onClick={() => setFull(!full)}
        >
          <Maximize2 className="size-4" />
          {full ? "Close full screen" : "Full screen"}
        </button>
      </div>
      {map.issues.length > 0 && (
        <div
          role="alert"
          className="max-h-32 overflow-auto border-b bg-amber-500/10 p-3 text-sm text-amber-300"
        >
          <strong>Incomplete execution map</strong>
          <ul>
            {[...new Set(map.issues)].map((issue) => (
              <li key={issue}>{issue}</li>
            ))}
          </ul>
        </div>
      )}
      {view === "map" ? (
        <div
          className="min-h-0 flex-1"
          aria-label="Complete nested execution map"
          role="region"
        >
          <ReactFlow
            colorMode="dark"
            nodes={nodes}
            edges={map.edges}
            nodeTypes={nodeTypes}
            defaultViewport={viewport}
            onMoveEnd={(_, value) => setViewport(value)}
            fitView={!viewport}
            fitViewOptions={{ padding: 0.1 }}
            minZoom={0.03}
            maxZoom={1.5}
            nodesDraggable={false}
            nodesFocusable={false}
            nodesConnectable={false}
            edgesReconnectable={false}
            deleteKeyCode={null}
          >
            <Background />
            <Controls showInteractive={false} />
            <MiniMap
              pannable
              zoomable
              nodeColor={(node) =>
                node.data.kind === "run"
                  ? "transparent"
                  : node.data.state === "SUCCEEDED"
                    ? "#34d399"
                    : node.data.state === "FAILED"
                      ? "#f87171"
                      : "#a1a1aa"
              }
            />
          </ReactFlow>
        </div>
      ) : (
        <div className="min-h-0 flex-1 space-y-4 overflow-auto p-5">
          <p className="text-xs text-muted-foreground">
            Graph dependency order, not a fabricated serial timeline. Inspect
            any step without leaving this execution.
          </p>
          {outline(execution.root)}
          {execution.runs
            .filter(
              (run) =>
                run.run_id !== execution.root.run_id &&
                !execution.runs
                  .find((parent) => parent.run_id === run.parent_run_id)
                  ?.nodes?.some(
                    (job) =>
                      isRecordedJob(job) && job.job_id === run.parent_job_id,
                  ),
            )
            .map((run) => (
              <section key={run.run_id}>
                <h3 className="text-sm font-semibold">
                  Unlinked subflow: {run.definition_ref || run.run_id}
                </h3>
                {outline(run)}
              </section>
            ))}
          {execution.runs.flatMap((run) =>
            unattributedCalls(run).map((record) => (
              <button
                key={`${run.run_id}:${record.id}`}
                className={studioButton}
                onClick={() =>
                  inspect({
                    kind: "call",
                    recordKey: `unlinked:${run.run_id}:${record.id}`,
                    run,
                    call: record.call,
                    callKind: record.kind,
                    label: `Unattributed ${record.kind} call`,
                    state: String(record.call.state || "RECORDED"),
                  })
                }
              >
                Unattributed {record.kind} call · {run.definition_ref}
              </button>
            )),
          )}
        </div>
      )}
      <p className="border-t px-3 py-2 text-xs text-muted-foreground">
        Green lines: recorded route. Dashed lines: no recorded traversal. Grey
        steps: not reached / capability only. The map uses pinned execution
        graphs, never current editable drafts.
      </p>
    </>
  );
  return (
    <>
      {full ? (
        <Dialog open onOpenChange={(open) => setFull(open)}>
          <DialogContent
            showCloseButton={false}
            className="inset-0 top-0 left-0 flex h-dvh w-screen max-w-none translate-x-0 translate-y-0 flex-col gap-0 rounded-none p-0 sm:max-w-none"
          >
            <DialogTitle className="sr-only">
              Complete workflow execution
            </DialogTitle>
            <DialogDescription className="sr-only">
              Explore the recorded root and nested execution. The node inspector
              opens above this map.
            </DialogDescription>
            {content}
            <Inspector
              data={currentSelection}
              close={() => setSelected(null)}
            />
          </DialogContent>
        </Dialog>
      ) : (
        <section className="flex h-[75dvh] min-h-[520px] flex-col overflow-hidden rounded-xl border bg-card">
          {content}
        </section>
      )}
      {!full && (
        <Inspector data={currentSelection} close={() => setSelected(null)} />
      )}
    </>
  );
}
