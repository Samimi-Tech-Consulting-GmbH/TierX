import {
  render,
  screen,
  fireEvent,
  cleanup,
  waitFor,
} from "@testing-library/react";
import { describe, it, expect, vi, afterEach } from "vitest";
import {
  GraphJsonEditor,
  WorkflowStudio,
  WorkflowCanvas,
  SubflowPanel,
  subflowReferences,
  isFlowGraph,
} from "./workflow-studio";
import { NodeGallery, NodeFields } from "./workflow-node-kit";
import { ReactFlow } from "@xyflow/react";
import * as workflows from "@/lib/workflows";
import type { FlowGraph } from "@/lib/workflows";
const auth = vi.hoisted(() => ({ user: null as { role: string } | null }));
vi.mock("@/lib/auth", () => ({ useAuth: () => auth }));
vi.mock("@xyflow/react", async () => ({
  ...(await vi.importActual<typeof import("@xyflow/react")>("@xyflow/react")),
  ReactFlow: vi.fn(() => null),
  Background: () => null,
  Controls: () => null,
  Handle: () => null,
}));
const graph: FlowGraph = {
  format_version: "2.0",
  nodes: [
    { id: "entry", type: "entry", config: {} },
    { id: "done", type: "complete", config: {} },
  ],
  edges: [],
};
afterEach(() => {
  cleanup();
  auth.user = null;
  vi.restoreAllMocks();
});
describe("Graph JSON import", () => {
  it("resolves selector fallback, mappings and model candidates without losing their roles", () => {
    expect(
      subflowReferences({
        id: "pick",
        type: "playbook_selector",
        config: {
          fallback: "generic",
          mappings: { malware: "endpoint" },
          candidates: ["network", "endpoint"],
        },
      }),
    ).toEqual([
      { kind: "playbook", code: "generic", role: "Fallback" },
      { kind: "playbook", code: "endpoint", role: "Static: malware" },
      { kind: "playbook", code: "network", role: "Model candidate" },
      { kind: "playbook", code: "endpoint", role: "Model candidate" },
    ]);
  });
  it("previews selector child graphs and opens them through the nested editor callback", () => {
    const open = vi.fn(),
      child = {
        kind: "playbook" as const,
        code: "generic",
        name: "Generic investigation",
        description: "",
        enabled: true,
        tenant_ids: ["one"],
        configuration: graph as unknown as Record<string, unknown>,
        draft_version: 1,
        active_revision: 2,
      };
    render(
      <SubflowPanel
        node={{
          id: "pick",
          type: "playbook_selector",
          config: { fallback: "generic", mappings: { malware: "generic" } },
        }}
        definitions={[child]}
        onOpen={open}
      />,
    );
    expect(screen.getAllByText("Generic investigation")).toHaveLength(1);
    expect(screen.getByText(/Fallback · Static: malware/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Preview subflow" }));
    expect(screen.getByLabelText("Workflow canvas")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open playbook" }));
    expect(open).toHaveBeenCalledWith(child);
  });
  it("restores the icon palette and searches modern node types", () => {
    const add = vi.fn();
    render(
      <NodeGallery
        catalog={[
          "entry",
          "playbook_selector",
          "kb_semantic",
          "persist_analysis",
        ]}
        hasEntry
        onAdd={add}
      />,
    );
    expect(
      screen.getByRole("button", { name: "Add Alert entry" }),
    ).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Search nodes"), {
      target: { value: "playbook" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Add Select playbook" }),
    );
    expect(add).toHaveBeenCalledWith("playbook_selector");
    expect(
      screen.queryByRole("button", { name: "Add Save analysis" }),
    ).not.toBeInTheDocument();
  });
  it("uses the playbook registry in structured selector settings", () => {
    const change = vi.fn();
    render(
      <NodeFields
        node={{ id: "pick", type: "playbook_selector", config: {} }}
        value={{ mode: "static" }}
        profiles={[]}
        definitions={[
          { kind: "playbook", code: "generic", name: "Generic investigation" },
        ]}
        onChange={change}
      />,
    );
    fireEvent.change(screen.getByLabelText("Fallback playbook"), {
      target: { value: "generic" },
    });
    expect(change).toHaveBeenCalledWith({
      mode: "static",
      fallback: "generic",
    });
  });
  it("does not replace controlled nodes on measurement or selection events", () => {
    const change = vi.fn();
    render(<WorkflowCanvas graph={graph} onChange={change} />);
    const props = vi.mocked(ReactFlow).mock.calls.at(-1)![0];
    props.onNodesChange?.([
      {
        id: "entry",
        type: "dimensions",
        dimensions: { width: 180, height: 90 },
      },
    ]);
    props.onNodesChange?.([{ id: "entry", type: "select", selected: true }]);
    expect(change).not.toHaveBeenCalled();
    props.onNodesChange?.([
      { id: "entry", type: "position", position: { x: 50, y: 40 } },
    ]);
    expect(change.mock.calls[0][0].nodes[0].position).toEqual({ x: 50, y: 40 });
  });
  it("opens the dedicated playbook library instead of an empty workflow screen", async () => {
    auth.user = { role: "PLATFORM_ADMIN" };
    const request = vi
      .spyOn(workflows, "workflowRequest")
      .mockResolvedValue({ items: [], node_types: [], templates: [] });
    render(<WorkflowStudio initialKind="playbook" />);
    expect(
      await screen.findByRole("button", { name: "Create playbook" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Playbooks" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Workflow Studio")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Execution history" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Workflow canvas")).not.toBeInTheDocument();
    request.mockRestore();
    auth.user = null;
  });
  it("never imports on blur and rejects an outdated edit buffer", () => {
    const apply = vi.fn();
    const view = render(
      <GraphJsonEditor graph={graph} readOnly={false} onApply={apply} />,
    );
    const editor = screen.getByLabelText("Graph JSON");
    fireEvent.change(editor, {
      target: {
        value: JSON.stringify({
          ...graph,
          edges: [{ id: "x", source: "entry", target: "done" }],
        }),
      },
    });
    fireEvent.blur(editor);
    expect(apply).not.toHaveBeenCalled();
    view.rerender(
      <GraphJsonEditor
        graph={{
          ...graph,
          nodes: [
            ...graph.nodes,
            { id: "new", type: "validation", config: {} },
          ],
        }}
        readOnly={false}
        onApply={apply}
      />,
    );
    expect(
      screen.getByRole("button", { name: "Apply JSON import" }),
    ).toBeDisabled();
    fireEvent.click(
      screen.getByRole("button", { name: "Reload current graph" }),
    );
    expect(
      (screen.getByLabelText("Graph JSON") as HTMLTextAreaElement).value,
    ).toContain('"new"');
  });
  it("rejects syntactically valid JSON that is not a graph", () => {
    expect(isFlowGraph(null)).toBe(false);
    expect(
      isFlowGraph({
        ...graph,
        nodes: [{ id: "x", type: "entry", config: null }],
      }),
    ).toBe(false);
    expect(isFlowGraph({ ...graph, edges: [null] })).toBe(false);
    const apply = vi.fn();
    render(<GraphJsonEditor graph={graph} readOnly={false} onApply={apply} />);
    fireEvent.change(screen.getByLabelText("Graph JSON"), {
      target: { value: "null" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Apply JSON import" }));
    expect(apply).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("preserved");
  });
  it("opens a canvas without a permanent palette and protects unsaved changes", async () => {
    auth.user = { role: "PLATFORM_ADMIN" };
    const definition = {
      kind: "workflow",
      code: "triage",
      name: "Endpoint triage",
      description: "Investigate endpoints",
      tenant_ids: ["one"],
      enabled: true,
      configuration: graph,
      draft_version: 1,
      active_revision: 1,
    };
    vi.spyOn(workflows, "workflowRequest").mockImplementation(
      async (path) =>
        (path === "/admin/workflow-definitions"
          ? {
              items: [definition],
              node_types: ["entry", "validation"],
              templates: [],
            }
          : { items: [] }) as never,
    );
    render(<WorkflowStudio />);
    fireEvent.click(
      await screen.findByRole("button", { name: /Endpoint triage/ }),
    );
    expect(screen.queryByLabelText("Node gallery")).not.toBeInTheDocument();
    expect(screen.queryByText("Investigate endpoints")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Workflow canvas")).toHaveClass("h-full");
    fireEvent.click(screen.getByRole("button", { name: "Expand canvas" }));
    expect(
      screen.getByRole("dialog", { name: "Expanded workflow editor" }),
    ).toHaveClass("fixed", "inset-0");
    expect(screen.getByRole("button", { name: "Save draft" })).toBeVisible();
    expect(document.body.style.overflow).toBe("hidden");
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(document.body.style.overflow).not.toBe("hidden");
    fireEvent.click(screen.getByRole("button", { name: "Add step" }));
    expect(screen.getByLabelText("Node gallery")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Name" }), {
      target: { value: "Changed triage" },
    });
    vi.spyOn(window, "confirm").mockReturnValue(false);
    fireEvent.click(screen.getByRole("button", { name: "Back to workflows" }));
    expect(
      screen.getByRole("heading", { name: "Changed triage" }),
    ).toBeInTheDocument();
  });
  it("synchronizes the agent buffer after save so publication can proceed", async () => {
    auth.user = { role: "PLATFORM_ADMIN" };
    let definition = {
      kind: "agent",
      code: "endpoint",
      name: "Endpoint specialist",
      description: "",
      tenant_ids: ["one"],
      enabled: true,
      configuration: {
        profile_code: "local",
        prompt: "Initial",
        tools: [],
        output_schema: { type: "object" },
      },
      draft_version: 1,
      active_revision: 1,
    };
    vi.spyOn(workflows, "workflowRequest").mockImplementation(
      async (path, method, body) => {
        if (method === "PUT") {
          definition = {
            ...definition,
            configuration: (
              body as { configuration: typeof definition.configuration }
            ).configuration,
            draft_version: 2,
          };
          return definition as never;
        }
        return (
          path === "/admin/workflow-definitions"
            ? { items: [definition], node_types: [], templates: [] }
            : { items: [] }
        ) as never;
      },
    );
    render(<WorkflowStudio initialKind="agent" />);
    fireEvent.click(
      await screen.findByRole("button", { name: /Endpoint specialist/ }),
    );
    fireEvent.change(screen.getByLabelText("Agent configuration"), {
      target: {
        value: JSON.stringify({
          ...definition.configuration,
          prompt: "Updated",
        }),
      },
    });
    expect(screen.getByRole("button", { name: "Publish" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Publish" })).toBeEnabled(),
    );
  });
});
