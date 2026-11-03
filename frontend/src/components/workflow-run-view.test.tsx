import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { WorkflowRunView } from "./workflow-run-view";
import { workflowRequest } from "@/lib/workflows";
vi.mock("@/lib/workflows", async importOriginal => ({ ...await importOriginal<typeof import("@/lib/workflows")>(), workflowRequest: vi.fn() }));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ user: { role: "PLATFORM_ADMIN" } }) }));
vi.mock("@/components/workflow-studio", () => ({ WorkflowCanvas: () => <div>Executed graph</div> }));
const run = { run_id: "r", root_run_id: "r", alert_id: "a", tenant_id: "one", definition_ref: "workflow:triage@2",
  state: "SUCCEEDED", created_at: "2026-01-01T00:00:00Z", completed_at: "2026-01-01T00:00:02Z", release_version: "0.3.0", release_sha: "a".repeat(40),
  graph: { format_version: "2.0", nodes: [], edges: [] }, children: [{ run_id: "c", definition_ref: "playbook:generic@3", state: "SUCCEEDED" }],
  nodes: [{ job_id: "j", node_id: "analysis", state: "SUCCEEDED", duration_ms: 5000 }] };
describe("Workflow execution", () => {
  beforeEach(() => vi.mocked(workflowRequest).mockReset());
  it("shows pinned revision, actual wall time and nested playbook navigation", async () => {
    vi.mocked(workflowRequest).mockResolvedValue(run);
    render(<WorkflowRunView tenantId="one" runId="r" />);
    expect(await screen.findByText("Flow version: workflow:triage@2")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "playbook:generic@3" })).toHaveAttribute("href", "/dashboard/one/workflows/runs/c");
    expect(screen.getByText(/elapsed 2,?000/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel execution" })).not.toBeInTheDocument();
    expect(workflowRequest).toHaveBeenCalledTimes(1);
  });
  it("cancels only after confirmation and warns about dispatched effects", async () => {
    vi.mocked(workflowRequest).mockResolvedValue({ ...run, state: "RUNNING" });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<WorkflowRunView tenantId="one" runId="r" />);
    fireEvent.click(await screen.findByRole("button", { name: "Cancel execution" }));
    await waitFor(() => expect(workflowRequest).toHaveBeenCalledWith("/tenants/one/runs/r/cancel", "POST"));
    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining("cannot be recalled"));
  });
});
