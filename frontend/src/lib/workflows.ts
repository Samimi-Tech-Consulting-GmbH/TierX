import { clearToken, readToken } from "./auth";

export interface FlowNode {
  id: string;
  type: string;
  config: Record<string, unknown>;
  position?: { x: number; y: number };
  label?: string;
}
export interface FlowEdge {
  id: string;
  source: string;
  target: string;
  sourceHandle?: string;
}
export interface FlowGraph {
  format_version: "1.0";
  nodes: FlowNode[];
  edges: FlowEdge[];
  viewport?: { x: number; y: number; zoom: number };
}
export interface FlowDraft {
  flow_id: string;
  name: string;
  graph: FlowGraph;
  draft_version: number;
}
export interface WorkflowJob {
  job_id: string;
  node_id: string;
  state: string;
  output?: unknown;
  error?: unknown;
  wait_reason?: string;
  duration_ms?: number;
  ancestors?: unknown;
  reclaimed_at?: string;
}
export interface WorkflowRun {
  run_id: string;
  alert_id: string;
  state: string;
  created_at: string;
  started_at?: string;
  completed_at?: string;
  graph?: FlowGraph;
  nodes?: WorkflowJob[];
  release_version: string;
  release_sha: string;
  alert?: { cluster_id?: string };
}

const base =
  process.env.NEXT_PUBLIC_TIERX_API_URL ??
  process.env.NEXT_PUBLIC_API_URL ??
  "";
export async function workflowRequest<T>(
  path: string,
  method = "GET",
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const r = await fetch(`${base}/api/v2${path}`, {
    method,
    signal,
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${readToken()}`,
    },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
  if (r.status === 401) {
    clearToken();
    throw new Error("Session expired; please sign in again.");
  }
  const data = await r.json();
  if (!r.ok)
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : `Request failed (${r.status})`,
    );
  return data;
}

export function outputPorts(node: FlowNode): string[] {
  if (["complete", "dead_letter"].includes(node.type)) return [];
  if (node.type === "decision") return ["true", "false", "error"];
  if (node.type === "fork")
    return Array.isArray(node.config.branches)
      ? (node.config.branches as string[])
      : [];
  return ["success", "error"];
}
