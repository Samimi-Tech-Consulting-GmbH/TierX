import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { WorkflowExecutionIndex } from "./workflow-execution-index";
import { listWorkflowDebugExecutions } from "@/lib/api";
import { workflowRequest } from "@/lib/workflows";
vi.mock("@/lib/api", () => ({ listWorkflowDebugExecutions: vi.fn() }));
vi.mock("@/lib/workflows", () => ({ workflowRequest: vi.fn() }));
const page = { items: [{ run_id: "root", alert_id: "alert", tenant_id: "one", tenant_name: "One", state: "SUCCEEDED", definition_ref: "workflow:triage@3" }], total: 26, skip: 0, limit: 25 };
describe("workflow Debug index", () => {
  beforeEach(() => { vi.mocked(listWorkflowDebugExecutions).mockReset().mockResolvedValue(page); });
  it("lists real roots across tenants and links to canonical Debug", async () => {
    render(<WorkflowExecutionIndex platformAdmin />);
    expect(await screen.findByRole("link", { name: "alert" })).toHaveAttribute("href", "/dashboard/admin/debug/runs/one/root");
    expect(listWorkflowDebugExecutions).toHaveBeenCalledWith("skip=0&limit=25", expect.any(AbortSignal));
    expect(screen.getByText("workflow:triage@3")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Historical/ })).toHaveAttribute("href", "/dashboard/admin/debug/history");
    expect(workflowRequest).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    await waitFor(() => expect(listWorkflowDebugExecutions).toHaveBeenLastCalledWith("skip=25&limit=25", expect.any(AbortSignal)));
    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "FAILED" } });
    await waitFor(() => expect(listWorkflowDebugExecutions).toHaveBeenLastCalledWith("skip=0&limit=25&state=FAILED", expect.any(AbortSignal)));
  });
  it("scopes the admin API and debounces literal search", async () => {
    render(<WorkflowExecutionIndex platformAdmin tenantId="one" />);
    await screen.findByRole("link", { name: "alert" });
    fireEvent.change(screen.getByLabelText("Search alerts, runs or workflows"), { target: { value: "a.*" } });
    await waitFor(() => expect(listWorkflowDebugExecutions).toHaveBeenLastCalledWith("skip=0&limit=25&tenant_id=one&q=a.*", expect.any(AbortSignal)));
  });
  it("never displays an error as no executions", async () => {
    vi.mocked(listWorkflowDebugExecutions).mockRejectedValue(new Error("unavailable"));
    render(<WorkflowExecutionIndex platformAdmin />);
    expect(await screen.findByRole("alert")).toHaveTextContent("could not be loaded");
    expect(screen.queryByText(/No recorded/)).not.toBeInTheDocument();
  });
  it("aborts and hides old scope data immediately", async () => {
    const { rerender } = render(<WorkflowExecutionIndex platformAdmin tenantId="one" />);
    await screen.findByRole("link", { name: "alert" });
    const signal = vi.mocked(listWorkflowDebugExecutions).mock.calls[0][1];
    vi.mocked(listWorkflowDebugExecutions).mockImplementation(() => new Promise(() => {}));
    rerender(<WorkflowExecutionIndex platformAdmin tenantId="two" />);
    expect(signal?.aborted).toBe(true);
    expect(screen.queryByRole("link", { name: "alert" })).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Loading");
  });
});
