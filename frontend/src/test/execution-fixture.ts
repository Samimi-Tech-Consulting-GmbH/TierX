import type { ExecutionRun } from "@/lib/workflow-execution";

export function executionFixture(): ExecutionRun[] {
  const common = {
    tenant_id: "one",
    alert_id: "a",
    state: "SUCCEEDED",
    created_at: "2026-01-01T00:00:00Z",
    completed_at: "2026-01-01T00:00:02Z",
    release_version: "0.2.18",
    release_sha: "a".repeat(40),
  };
  const make = (
    id: string,
    definition: string,
    labels: [string, string, string][],
  ): ExecutionRun => ({
    ...common,
    run_id: id,
    root_run_id: "r",
    definition_ref: definition,
    workflow_version: {
      code: "triage",
      revision: 2,
      definition_ref: "workflow:triage@2",
      checksum: "b".repeat(64),
    },
    graph: {
      format_version: "2.0",
      nodes: labels.map(([id, type, label]) => ({
        id,
        type,
        label,
        config: {},
      })),
      edges: labels
        .slice(1)
        .map((item, i) => ({
          id: `e${i}`,
          source: labels[i][0],
          target: item[0],
        })),
    },
    nodes: labels.map(([node_id, node_type, label]) => ({
      job_id: `${id}-${node_id}`,
      node_id,
      node_type,
      label,
      state: "SUCCEEDED",
      port: "success",
      node_elapsed_ms: 100,
      execution_duration_ms: 40,
      attempt_count: 1,
      input_snapshot: { value: { synthetic: "safe input" } },
      output_snapshot: { value: { synthetic: "safe output" } },
    })),
    children: [],
  });
  const root = make("r", "workflow:triage@2", [
    ["entry", "entry", "Receive alert"],
    ["route", "playbook_selector", "Choose playbook"],
    ["done", "complete", "Finish workflow"],
  ]);
  root.graph!.nodes.push({
    id: "skipped",
    type: "dead_letter",
    label: "Rejected branch",
    config: {},
  });
  root.graph!.edges.push({
    id: "error",
    source: "route",
    target: "skipped",
    sourceHandle: "error",
  });
  root.nodes!.push({
    job_id: "not-executed:skipped",
    node_id: "skipped",
    label: "Rejected branch",
    state: "NOT_REACHED",
  });
  const playbook = {
    ...make("p", "playbook:investigate@3", [
      ["entry", "entry", "Playbook entry"],
      ["agent", "agent", "Endpoint specialist"],
      ["done", "complete", "Finish investigation"],
    ]),
    parent_run_id: "r",
    parent_job_id: "r-route",
  };
  const agent = {
    ...make("s", "agent:endpoint@4", [
      ["entry", "entry", "Agent entry"],
      ["reason", "llm_tools", "Assess evidence"],
      ["done", "complete", "Finish agent"],
    ]),
    parent_run_id: "p",
    parent_job_id: "p-agent",
    model_calls: [
      {
        job_id: "s-reason",
        model: "phi3:latest",
        created_at: "2026-01-01T00:00:01Z",
        duration_ms: 40,
      },
    ],
    tool_calls: [
      {
        job_id: "s-reason",
        call_id: "tool-1",
        tool_name: "asset_lookup",
        state: "SUCCEEDED",
      },
    ],
  };
  root.children = [
    {
      run_id: "p",
      definition_ref: playbook.definition_ref,
      state: playbook.state,
    },
  ];
  playbook.children = [
    { run_id: "s", definition_ref: agent.definition_ref, state: agent.state },
  ];
  return [root, playbook, agent];
}
