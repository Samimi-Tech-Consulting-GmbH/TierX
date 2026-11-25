import {
  render,
  screen,
  waitFor,
  fireEvent,
  within,
} from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { WorkflowRunView } from "./workflow-run-view";
import { workflowRequest } from "@/lib/workflows";
import { executionFixture } from "@/test/execution-fixture";
vi.mock("@/lib/workflows", async (original) => ({
  ...(await original<typeof import("@/lib/workflows")>()),
  workflowRequest: vi.fn(),
}));
vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: { role: "PLATFORM_ADMIN" } }),
}));
vi.mock("@xyflow/react", () => ({
  ReactFlow: ({
    nodes,
    colorMode,
  }: {
    nodes: { id: string; data: { label: string; inspect: () => void } }[];
    colorMode?: string;
  }) => (
    <div data-testid="execution-flow" data-color-mode={colorMode}>
      {nodes.map((node) => (
        <button key={node.id} onClick={node.data.inspect}>
          {node.data.label}
        </button>
      ))}
    </div>
  ),
  Background: () => null,
  Controls: () => null,
  MiniMap: () => null,
  Handle: () => null,
  Position: { Left: "left", Right: "right" },
}));
describe("Complete workflow debugger", () => {
  beforeEach(() => {
    vi.mocked(workflowRequest).mockReset();
    const runs = executionFixture();
    vi.mocked(workflowRequest).mockImplementation(async (path) =>
      runs.find((run) => path.endsWith(`/${run.run_id}`))!,
    );
  });
  it("displays root, playbook, agent, not-reached branches and recorded calls in one map", async () => {
    render(<WorkflowRunView tenantId="one" runId="r" />);
    expect(
      await screen.findByText("Flow version: workflow:triage@2"),
    ).toBeInTheDocument();
    expect(
      await screen.findByRole("button", { name: "Assess evidence" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "playbook:investigate@3" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "agent:endpoint@4" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Model call · phi3/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Rejected branch" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/elapsed 2,?000/)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Cancel execution" }),
    ).not.toBeInTheDocument();
    expect(workflowRequest).toHaveBeenCalledTimes(3);
    expect(screen.getByTestId("execution-flow")).toHaveAttribute(
      "data-color-mode",
      "dark",
    );
  });
  it("opens an overlay inspector without replacing the full execution and supports a nested outline", async () => {
    render(<WorkflowRunView tenantId="one" runId="r" />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Assess evidence" }),
    );
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Safe input snapshot")).toBeInTheDocument();
    expect(within(dialog).getAllByText(/safe input/).length).toBeGreaterThan(0);
    expect(
      screen.getByLabelText("Complete nested execution map"),
    ).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Close" }));
    fireEvent.click(screen.getByRole("button", { name: "Step by step" }));
    expect(
      screen.getByRole("list", { name: "Steps in agent:endpoint@4" }),
    ).toBeInTheDocument();
    expect(screen.getByText("2.2.2")).toBeInTheDocument();
  });
  it("expands all by default and collapsing a caller hides every descendant", async () => {
    render(<WorkflowRunView tenantId="one" runId="r" />);
    await screen.findByRole("button", { name: "Assess evidence" });
    fireEvent.click(screen.getByRole("button", { name: "Collapse subflows" }));
    expect(
      screen.queryByRole("button", { name: "Assess evidence" }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Expand all" }));
    expect(
      screen.getByRole("button", { name: "Assess evidence" }),
    ).toBeInTheDocument();
  });
  it("displays a visible incomplete warning when a subflow cannot load", async () => {
    const [root] = executionFixture();
    vi.mocked(workflowRequest).mockImplementation(async (path) => {
      if (path.endsWith("/r")) return root;
      throw new Error("Denied");
    });
    render(<WorkflowRunView tenantId="one" runId="r" />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Incomplete execution map",
    );
    expect(
      screen.getByRole("button", { name: "Receive alert" }),
    ).toBeInTheDocument();
  });
  it("a nested permalink still displays the root and cancels only the root after confirmation", async () => {
    const runs = executionFixture();
    runs[0].state = "RUNNING";
    vi.mocked(workflowRequest).mockImplementation(async (path) =>
      runs.find((run) => path.endsWith(`/${run.run_id}`))!,
    );
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<WorkflowRunView tenantId="one" runId="s" />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Cancel execution" }),
    );
    await waitFor(() =>
      expect(workflowRequest).toHaveBeenCalledWith(
        "/tenants/one/runs/r/cancel",
        "POST",
      ),
    );
    expect(window.confirm).toHaveBeenCalledWith(
      expect.stringContaining("cannot be recalled"),
    );
  });
  it("shows a node's recorded release separately from its run release", async () => {
    const runs = executionFixture();
    Object.assign(runs[2].nodes![1], {
      release_version: "0.2.19",
      release_sha: "b".repeat(40),
    });
    vi.mocked(workflowRequest).mockImplementation(async (path) =>
      runs.find((run) => path.endsWith(`/${run.run_id}`))!,
    );
    render(<WorkflowRunView tenantId="one" runId="r" />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Assess evidence" }),
    );
    expect(
      await screen.findByText("Node execution release: 0.2.19 / bbbbbbbb"),
    ).toBeInTheDocument();
    expect(screen.getByText(/run application 0.2.18/)).toBeInTheDocument();
  });
  it("uses a full-viewport dialog and returns to the same map", async () => {
    render(<WorkflowRunView tenantId="one" runId="r" />);
    fireEvent.click(await screen.findByRole("button", { name: "Full screen" }));
    expect(await screen.findByRole("dialog")).toHaveClass("h-dvh");
    fireEvent.click(screen.getByRole("button", { name: "Close full screen" }));
    expect(
      screen.getByLabelText("Complete nested execution map"),
    ).toBeInTheDocument();
  });
  it("keeps full screen open when its nested inspector closes", async () => {
    render(<WorkflowRunView tenantId="one" runId="r" />);
    fireEvent.click(await screen.findByRole("button", { name: "Full screen" }));
    const fullScreen = await screen.findByRole("dialog");
    fireEvent.click(
      within(fullScreen).getByRole("button", { name: "Assess evidence" }),
    );
    await waitFor(() =>
      expect(screen.getAllByRole("dialog", { hidden: true })).toHaveLength(2),
    );
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.getAllByRole("dialog")).toHaveLength(1));
    expect(screen.getByRole("dialog")).toHaveClass("h-dvh");
  });
  it("labels placeholder steps as unexecuted instead of presenting fabricated job metadata", async () => {
    render(<WorkflowRunView tenantId="one" runId="r" />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Rejected branch" }),
    );
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/Attempts: 0/)).toBeInTheDocument();
    expect(
      within(dialog).queryByText("Recorded execution metadata"),
    ).not.toBeInTheDocument();
    expect(
      within(dialog).getByText(/has no recorded execution/),
    ).toBeInTheDocument();
  });
  it("can retry a partially loaded terminal execution without hiding missing records", async () => {
    const runs = executionFixture();
    let failed = true;
    vi.mocked(workflowRequest).mockImplementation(async (path) => {
      if (failed && path.endsWith("/p")) throw new Error("Unavailable");
      return runs.find((run) => path.endsWith(`/${run.run_id}`))!;
    });
    render(<WorkflowRunView tenantId="one" runId="r" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Incomplete");
    failed = false;
    fireEvent.click(screen.getByRole("button", { name: "Refresh execution" }));
    expect(
      await screen.findByRole("button", { name: "Assess evidence" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
