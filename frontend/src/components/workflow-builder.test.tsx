import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WorkflowBuilder } from "./workflow-builder";
import { workflowRequest, outputPorts } from "@/lib/workflows";
let role = "TENANT_ADMIN";
afterEach(cleanup);
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ user: { role } }) }));
vi.mock("@/lib/workflows", async (original) => ({
  ...(await original<typeof import("@/lib/workflows")>()),
  workflowRequest: vi.fn(),
}));
vi.mock("@xyflow/react", () => ({
  ReactFlow: () => <div data-testid="canvas" />,
  Background: () => null,
  Controls: () => null,
  Handle: () => null,
  Position: { Left: "left", Right: "right" },
  applyNodeChanges: (_: unknown, nodes: unknown) => nodes,
  applyEdgeChanges: (_: unknown, edges: unknown) => edges,
  addEdge: (_: unknown, edges: unknown) => edges,
}));
const graph = {
  format_version: "1.0",
  nodes: [
    { id: "entry", type: "entry", config: {} },
    { id: "done", type: "complete", config: {} },
  ],
  edges: [
    { id: "next", source: "entry", target: "done", sourceHandle: "success" },
  ],
};
beforeEach(() => {
  role = "TENANT_ADMIN";
  vi.clearAllMocks();
  vi.mocked(workflowRequest).mockImplementation(async (path, method) => {
    if (path.endsWith("workflow-catalog"))
      return { node_types: ["entry", "complete"], default_graph: graph };
    if (path.endsWith("/flows"))
      return {
        items: [
          { flow_id: "flow", name: "Synthetic", draft_version: 1, graph },
        ],
      };
    if (path.endsWith("/runs")) return { items: [] };
    if (path.endsWith("/ingest") && method === "POST")
      return { run_id: "run", alert_id: "alert", state: "PENDING" };
    if (path.endsWith("/runs/run"))
      return {
        run_id: "run",
        alert_id: "alert",
        state: "SUCCEEDED",
        created_at: "2026-01-01T00:00:00Z",
        completed_at: "2026-01-01T00:00:02Z",
        release_version: "0.0.0",
        release_sha: "test-sha",
        nodes: [],
        graph,
      };
    return {};
  });
});
describe("V2 workspace", () => {
  it("keeps operators read-only", async () => {
    role = "TENANT_OPERATOR";
    render(<WorkflowBuilder tenantId="one" />);
    await screen.findByText("Synthetic · draft 1");
    expect(screen.queryByText("Save draft")).not.toBeInTheDocument();
    expect(screen.queryByText("Submit alert")).not.toBeInTheDocument();
    expect(screen.getByTestId("canvas")).toBeInTheDocument();
  });
  it("submits asynchronously and follows a separate run", async () => {
    render(<WorkflowBuilder tenantId="one" />);
    await screen.findByText("Synthetic · draft 1");
    fireEvent.change(screen.getByLabelText("Select workflow"), {
      target: { value: "flow" },
    });
    fireEvent.click(screen.getByText("Submit alert"));
    await waitFor(() =>
      expect(workflowRequest).toHaveBeenCalledWith(
        "/tenants/one/ingest",
        "POST",
        expect.objectContaining({ flow_id: "flow", draft_version: 1 }),
      ),
    );
    await screen.findByText(/Watching stopped/);
    expect(screen.queryByText("Save draft")).not.toBeInTheDocument();
    expect(
      screen.getByText(/Read-only execution snapshot/),
    ).toBeInTheDocument();
    expect(screen.getByText(/2000 ms \(2 s\)/)).toBeInTheDocument();
  });
  it("supports explicit decision and failure ports", () => {
    expect(
      outputPorts({ id: "condition", type: "decision", config: {} }),
    ).toEqual(["true", "false", "error"]);
    expect(
      outputPorts({
        id: "fork",
        type: "fork",
        config: { branches: ["kb", "provider"] },
      }),
    ).toEqual(["kb", "provider"]);
    expect(outputPorts({ id: "done", type: "complete", config: {} })).toEqual(
      [],
    );
  });
});
