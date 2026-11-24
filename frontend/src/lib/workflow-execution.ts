import {
  workflowRequest,
  WorkflowRequestError,
  type FlowNode,
  type WorkflowJob,
  type WorkflowRun,
} from "./workflows";
import type { Edge, Node } from "@xyflow/react";

export type Call = Record<string, unknown>;
export type ExecutionRun = WorkflowRun & {
  tenant_id: string;
  definition_ref?: string;
  definition_code?: string;
  root_run_id?: string;
  parent_run_id?: string;
  parent_job_id?: string;
  workflow_version?: {
    code: string;
    revision: number;
    definition_ref: string;
    checksum?: string;
  };
  children?: { run_id: string; definition_ref?: string; state: string }[];
  tool_calls?: Call[];
  model_calls?: Call[];
  python_calls?: Call[];
};
export type Execution = {
  root: ExecutionRun;
  runs: ExecutionRun[];
  issues: string[];
  retryable?: boolean;
};
export type ExecutionCache = {
  successful: Map<string, ExecutionRun>;
  denied: Map<string, WorkflowRequestError>;
  transient: Map<string, { error: unknown; attempts: number; retryAt: number }>;
};
export const newExecutionCache = (): ExecutionCache => ({
  successful: new Map(),
  denied: new Map(),
  transient: new Map(),
});
export const permanentReadError = (error: unknown) =>
  error instanceof WorkflowRequestError &&
  error.status >= 400 &&
  error.status < 500 &&
  ![408, 429].includes(error.status);
export function isRecordedJob(job?: WorkflowJob): boolean {
  return Boolean(
    job &&
    !["NOT_REACHED", "CAPABILITY_ONLY"].includes(job.state) &&
    !job.job_id.startsWith("not-executed:"),
  );
}

/** Existing tenant-authorized, redacted Debug APIs remain the only data source. */
export async function loadExecution(
  tenant: string,
  requestedId: string,
  signal: AbortSignal,
  cache = newExecutionCache(),
): Promise<Execution> {
  const read = async (id: string): Promise<ExecutionRun> => {
    if (cache.denied.has(id)) throw cache.denied.get(id);
    if (cache.successful.has(id)) return cache.successful.get(id)!;
    const previousFailure = cache.transient.get(id);
    if (previousFailure && Date.now() < previousFailure.retryAt)
      throw previousFailure.error;
    try {
      const value = await workflowRequest<ExecutionRun>(
        `/tenants/${encodeURIComponent(tenant)}/runs/${encodeURIComponent(id)}`,
        "GET",
        undefined,
        signal,
      );
      cache.transient.delete(id);
      // Successful runs have finished all their jobs; failed/cancelled runs may
      // still receive late delivery metadata and are deliberately not cached.
      if (
        value.state === "SUCCEEDED" &&
        [value.model_calls, value.tool_calls, value.python_calls].every(
          (calls) =>
            (calls || []).every(
              (call) =>
                !["PENDING", "RUNNING", "WAITING", "DISPATCHED"].includes(
                  String(call.state),
                ),
            ),
        )
      )
        cache.successful.set(id, value);
      return value;
    } catch (error) {
      if (signal.aborted) throw error;
      if (permanentReadError(error))
        cache.denied.set(id, error as WorkflowRequestError);
      else {
        const attempts = (previousFailure?.attempts || 0) + 1;
        cache.transient.set(id, {
          error,
          attempts,
          retryAt: Date.now() + Math.min(30000, 5000 * 2 ** (attempts - 1)),
        });
      }
      throw error;
    }
  };
  const requested = await read(requestedId);
  if (requested.run_id !== requestedId || requested.tenant_id !== tenant)
    throw new Error("Requested execution identity mismatch.");
  const root =
    requested.root_run_id && requested.root_run_id !== requested.run_id
      ? await read(requested.root_run_id)
      : requested;
  if (
    root.tenant_id !== tenant ||
    root.run_id !== (requested.root_run_id || requestedId) ||
    root.alert_id !== requested.alert_id ||
    Boolean(root.parent_run_id) ||
    Boolean(root.root_run_id && root.root_run_id !== root.run_id)
  )
    throw new Error(
      "Execution identity mismatch; cannot display a complete trace.",
    );
  let retryable = false;
  const runs = [root],
    issues: string[] = [],
    seen = new Set([root.run_id]);
  let queue = (root.children || []).map((child) => ({
    id: child.run_id,
    parent: root.run_id,
    depth: 1,
  }));
  while (queue.length) {
    const batch: typeof queue = [];
    while (queue.length && batch.length < 6) {
      const item = queue.shift()!;
      if (seen.has(item.id)) {
        issues.push(`Repeated or cyclic subflow reference: ${item.id}`);
        continue;
      }
      if (seen.size >= 100 || item.depth > 8) {
        issues.push(
          "Execution display limit reached; some subflows are not shown.",
        );
        queue = [];
        break;
      }
      seen.add(item.id);
      batch.push(item);
    }
    const values = await Promise.all(
      batch.map(async (item) => {
        try {
          const child =
            item.id === requested.run_id ? requested : await read(item.id);
          if (
            child.run_id !== item.id ||
            child.tenant_id !== tenant ||
            child.alert_id !== root.alert_id ||
            child.parent_run_id !== item.parent ||
            child.root_run_id !== root.run_id
          )
            throw new Error("Subflow identity or parent mismatch");
          return { child, depth: item.depth };
        } catch (error) {
          if (signal.aborted) throw error;
          if (
            !permanentReadError(error) &&
            !(
              error instanceof Error &&
              error.message === "Subflow identity or parent mismatch"
            )
          )
            retryable = true;
          const cause =
            error instanceof WorkflowRequestError
              ? `HTTP ${error.status}`
              : error instanceof Error &&
                  error.message === "Subflow identity or parent mismatch"
                ? "identity/parent metadata mismatch"
                : "read failed";
          issues.push(
            `Subflow ${item.id} could not be loaded (${cause}). The map is incomplete.`,
          );
          return null;
        }
      }),
    );
    for (const value of values)
      if (value) {
        runs.push(value.child);
        queue.push(
          ...(value.child.children || []).map((child) => ({
            id: child.run_id,
            parent: value.child.run_id,
            depth: value.depth + 1,
          })),
        );
      }
  }
  for (const run of runs) {
    if (unattributedCalls(run).length)
      issues.push(
        `Some call records in ${run.definition_ref || run.run_id} have no recorded caller; shown separately.`,
      );
    if (!run.graph?.nodes.length)
      issues.push(
        `Pinned graph unavailable for ${run.definition_ref || run.run_id}.`,
      );
    if (
      run.run_id !== root.run_id &&
      !runs
        .find((parent) => parent.run_id === run.parent_run_id)
        ?.nodes?.some(
          (job) => isRecordedJob(job) && job.job_id === run.parent_job_id,
        )
    )
      issues.push(
        `Caller metadata is missing for subflow ${run.run_id}; its position cannot be inferred.`,
      );
  }
  return { root, runs, issues, retryable };
}

export function callsFor(run: ExecutionRun, job?: WorkflowJob) {
  if (!isRecordedJob(job)) return [];
  return callRecords(run).filter(
    (record) => record.call.job_id === job!.job_id,
  );
}

export function unattributedCalls(run: ExecutionRun) {
  return callRecords(run).filter(
    (record) =>
      !run.nodes?.some(
        (job) => isRecordedJob(job) && job.job_id === record.call.job_id,
      ),
  );
}

function callRecords(run: ExecutionRun) {
  return (["model", "tool", "python"] as const).flatMap((kind) =>
    (run[`${kind}_calls`] || []).map((call, i) => ({
      kind,
      call,
      id: `${kind}:${String(call.call_id || call.python_call_id || "record")}:${i}`,
    })),
  );
}

export type ExecutionNodeData = Record<string, unknown> & {
  kind: "run" | "step" | "call";
  run: ExecutionRun;
  label: string;
  state: string;
  definition?: FlowNode;
  job?: WorkflowJob;
  call?: Call;
  callKind?: string;
  recordKey?: string;
  childCount?: number;
  expanded?: boolean;
  inspect?: () => void;
  toggle?: () => void;
};
export type ExecutionNode = Node<ExecutionNodeData>;
export const stepId = (run: string, node: string) => `step:${run}:${node}`;

/** Longest-path columns preserve forks and joins; saved editor coordinates are not execution order. */
export function orderedNodes(run: ExecutionRun) {
  const nodes = run.graph?.nodes || [],
    edges = run.graph?.edges || [];
  const ranks = new Map(nodes.map((node) => [node.id, 0]));
  const remaining = new Set(nodes.map((node) => node.id)),
    ordered: FlowNode[] = [];
  while (remaining.size) {
    const ready = nodes.filter(
      (node) =>
        remaining.has(node.id) &&
        !edges.some(
          (edge) => edge.target === node.id && remaining.has(edge.source),
        ),
    );
    if (!ready.length) {
      ordered.push(...nodes.filter((node) => remaining.has(node.id)));
      break;
    }
    for (const node of ready) {
      remaining.delete(node.id);
      ordered.push(node);
      for (const edge of edges.filter((edge) => edge.source === node.id))
        ranks.set(
          edge.target,
          Math.max(ranks.get(edge.target) || 0, (ranks.get(node.id) || 0) + 1),
        );
    }
  }
  return { nodes: ordered, ranks };
}

/** Namespaced compound nodes keep every recorded child under its actual caller job. */
export function executionMap(
  execution: Execution,
  collapsed = new Set<string>(),
) {
  const nodes: ExecutionNode[] = [],
    edges: Edge[] = [],
    expandable: string[] = [],
    issues = [...execution.issues];
  const linked = new Set<string>();
  const hidden = new Set<string>();
  function layout(
    run: ExecutionRun,
    parentId?: string,
    position = { x: 0, y: 0 },
    ancestors = new Set<string>(),
  ): { width: number; height: number } {
    if (ancestors.has(run.run_id)) return { width: 260, height: 100 };
    const path = new Set([...ancestors, run.run_id]);
    linked.add(run.run_id);
    const frameId = `run:${run.run_id}`,
      frameIndex = nodes.length;
    nodes.push({
      id: frameId,
      type: "execution",
      parentId,
      position,
      data: {
        kind: "run",
        run,
        label: run.definition_ref || run.run_id,
        state: run.state,
      },
      style: { width: 280, height: 120 },
      selectable: false,
      draggable: false,
    });
    const order = orderedNodes(run),
      sizes = new Map<string, { width: number; height: number }>(),
      stepNodes = new Map<string, ExecutionNode>();
    for (const definition of order.nodes) {
      const id = stepId(run.run_id, definition.id),
        // Validated DAGs forbid loops and shared fork branches before the paired
        // join. enqueue(run,node,fork-path) upserts the same job on retry.
        job = run.nodes?.find((job) => job.node_id === definition.id);
      const children = execution.runs.filter(
        (child) =>
          child.parent_run_id === run.run_id &&
          child.parent_job_id === job?.job_id &&
          isRecordedJob(job),
      );
      const calls = callsFor(run, job),
        count = children.length + calls.length;
      if (count) expandable.push(id);
      const open = !collapsed.has(id);
      let width = 236,
        height = 124;
      const index = nodes.length;
      nodes.push({
        id,
        type: "execution",
        parentId: frameId,
        position: { x: 0, y: 0 },
        draggable: false,
        data: {
          kind: "step",
          recordKey: id,
          run,
          definition,
          job,
          label: definition.label || definition.id,
          state: job?.state || "NOT_REACHED",
          childCount: count,
          expanded: open,
        },
        style: { width, height },
      });
      if (open) {
        for (const child of children) {
          const size = layout(child, id, { x: 16, y: height }, path);
          width = Math.max(width, size.width + 32);
          height += size.height + 20;
        }
        for (const { kind, call, id: callId } of calls) {
          nodes.push({
            id: `${id}:${callId}`,
            type: "execution",
            parentId: id,
            position: { x: 16, y: height },
            draggable: false,
            data: {
              kind: "call",
              recordKey: `${id}:${callId}`,
              run,
              job,
              call,
              callKind: kind,
              label: `${kind === "model" ? "Model" : kind === "python" ? "Python" : "Tool"} call · ${String(call.model || call.tool_code || call.tool_name || call.connector_code || "recorded")}`,
              state: String(
                call.state || (kind === "model" ? "SUCCEEDED" : "RECORDED"),
              ),
            },
            style: { width: 204, height: 92 },
          });
          height += 108;
        }
      } else {
        const hide = (child: ExecutionRun) => {
          if (linked.has(child.run_id)) return;
          linked.add(child.run_id);
          hidden.add(child.run_id);
          for (const descendant of execution.runs.filter(
            (run) => run.parent_run_id === child.run_id,
          ))
            hide(descendant);
        };
        for (const child of children) hide(child);
      }
      if (count && open) height += 8;
      nodes[index].style = { width, height };
      stepNodes.set(definition.id, nodes[index]);
      sizes.set(definition.id, { width, height });
    }
    const columnWidths = new Map<number, number>();
    for (const node of order.nodes) {
      const rank = order.ranks.get(node.id) || 0;
      columnWidths.set(
        rank,
        Math.max(columnWidths.get(rank) || 0, sizes.get(node.id)!.width),
      );
    }
    let x = 24,
      maxHeight = 80;
    for (const rank of [...columnWidths.keys()].sort((a, b) => a - b)) {
      let y = 64;
      for (const node of order.nodes.filter(
        (node) => (order.ranks.get(node.id) || 0) === rank,
      )) {
        stepNodes.get(node.id)!.position = { x, y };
        y += sizes.get(node.id)!.height + 36;
      }
      maxHeight = Math.max(maxHeight, y);
      x += columnWidths.get(rank)! + 64;
    }
    for (const edge of run.graph?.edges || []) {
      const source = run.nodes?.find((job) => job.node_id === edge.source),
        target = run.nodes?.find((job) => job.node_id === edge.target);
      const sourceNode = run.graph?.nodes.find(
        (node) => node.id === edge.source,
      );
      const observed = Boolean(
        source &&
        target &&
        !["NOT_REACHED", "CAPABILITY_ONLY"].includes(target.state) &&
        (source.port === (edge.sourceHandle || "success") ||
          (sourceNode?.type === "fork" &&
            Array.isArray(sourceNode.config.branches) &&
            sourceNode.config.branches.includes(edge.sourceHandle))),
      );
      edges.push({
        id: `${frameId}:${edge.id}`,
        source: stepId(run.run_id, edge.source),
        target: stepId(run.run_id, edge.target),
        sourceHandle: edge.sourceHandle || "success",
        label: `${edge.sourceHandle || "success"} · ${observed ? "recorded route" : "no traversal recorded"}`,
        style: {
          stroke: observed ? "#34d399" : "#71717a",
          strokeWidth: observed ? 2 : 1,
          strokeDasharray: observed ? undefined : "5 4",
        },
        labelStyle: { fill: "#a1a1aa", fontSize: 10 },
      });
    }
    const size = {
      width: Math.max(300, x - 40),
      height: Math.max(170, maxHeight),
    };
    nodes[frameIndex].style = size;
    return size;
  }
  layout(execution.root);
  // Legacy/missing caller metadata must not be guessed or silently dropped.
  let detachedY = Number(nodes[0]?.style?.height || 0) + 100;
  for (const run of execution.runs) {
    if (linked.has(run.run_id)) continue;
    const parent = execution.runs.find(
      (parent) => parent.run_id === run.parent_run_id,
    );
    const caller = parent?.nodes?.find(
      (job) => isRecordedJob(job) && job.job_id === run.parent_job_id,
    );
    if (caller && collapsed.has(stepId(parent!.run_id, caller.node_id)))
      continue;
    issues.push(
      `Subflow ${run.definition_ref || run.run_id} has no visible caller; shown separately.`,
    );
    const size = layout(run, undefined, { x: 0, y: detachedY });
    detachedY += size.height + 60;
  }
  for (const run of execution.runs.filter((run) => !hidden.has(run.run_id)))
    for (const record of unattributedCalls(run)) {
      issues.push(
        `Call record in ${run.definition_ref || run.run_id} has no recorded caller; shown separately.`,
      );
      nodes.push({
        id: `unlinked:${run.run_id}:${record.id}`,
        type: "execution",
        position: { x: 0, y: detachedY },
        data: {
          kind: "call",
          recordKey: `unlinked:${run.run_id}:${record.id}`,
          run,
          call: record.call,
          callKind: record.kind,
          label: `Unattributed ${record.kind} call`,
          state: String(record.call.state || "RECORDED"),
        },
        style: { width: 260, height: 92 },
        draggable: false,
      });
      detachedY += 112;
    }
  return { nodes, edges, expandable, issues };
}
