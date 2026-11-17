import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import PythonToolsPage from "@/app/dashboard/admin/settings/python-tools/page";
import { workflowRequest } from "@/lib/workflows";
const auth = vi.hoisted(() => ({ user: { role: "PLATFORM_ADMIN" } }));
vi.mock("@/lib/auth", () => ({ useAuth: () => auth }));
vi.mock("@/lib/workflows", () => ({ workflowRequest: vi.fn() }));
vi.mock("@/components/workflow-library", async (original) => ({
  ...(await original<typeof import("@/components/workflow-library")>()),
  TenantSelection: () => <div>Tenant selection</div>,
}));
const tool = {
  code: "observe",
  name: "Observe",
  description: "Synthetic",
  source: "def run(alert, cluster): return {}",
  tenant_ids: ["one"],
  enabled: true,
  output_mode: "json",
  output_schema: { type: "object" },
  timeout_seconds: 30,
  destinations: [],
  draft_version: 1,
  active_revision: 1,
  updated_at: "server metadata",
  updated_by: "admin",
};
describe("Python tool management", () => {
  beforeEach(() => {
    auth.user.role = "PLATFORM_ADMIN";
    vi.mocked(workflowRequest).mockReset();
  });
  it("does not load management APIs for tenant administrators", () => {
    auth.user.role = "TENANT_ADMIN";
    render(<PythonToolsPage />);
    expect(
      screen.getByText(/requires platform administrator/),
    ).toBeInTheDocument();
    expect(workflowRequest).not.toHaveBeenCalled();
  });
  it("saves only editable contract fields, without server metadata", async () => {
    vi.mocked(workflowRequest).mockImplementation(async (_path, method) =>
      method === "PUT" ? { ...tool, draft_version: 2 } : { items: [tool] },
    );
    render(<PythonToolsPage />);
    fireEvent.click(await screen.findByText("Observe"));
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    fireEvent.change(screen.getByLabelText("Name"), {
      target: { value: "Updated" },
    });
    expect(screen.getByRole("button", { name: "Publish" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    await waitFor(() =>
      expect(workflowRequest).toHaveBeenCalledWith(
        "/admin/python-tools/observe",
        "PUT",
        expect.objectContaining({ name: "Updated", expected_version: 1 }),
      ),
    );
    const body = vi
      .mocked(workflowRequest)
      .mock.calls.find((call) => call[1] === "PUT")?.[2];
    expect(body).not.toHaveProperty("updated_at");
    expect(body).not.toHaveProperty("updated_by");
    expect(body).not.toHaveProperty("active_revision");
  });
});
