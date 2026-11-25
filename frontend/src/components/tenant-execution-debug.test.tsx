import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { TenantExecutionDebug } from "./tenant-execution-debug";
import { workflowRequest } from "@/lib/workflows";
vi.mock("@/lib/workflows", () => ({ workflowRequest: vi.fn() }));
describe("Tenant Debug execution list", () => {
  beforeEach(() => {
    vi.mocked(workflowRequest).mockReset();
  });
  it("loads only tenant-authorized runs and links to Debug", async () => {
    vi.mocked(workflowRequest).mockResolvedValue({
      items: [{ run_id: "run", state: "SUCCEEDED" }],
    });
    render(<TenantExecutionDebug tenantId="one" />);
    expect(await screen.findByRole("link", { name: /run/ })).toHaveAttribute(
      "href",
      "/dashboard/one/debug/runs/run",
    );
    expect(workflowRequest).toHaveBeenCalledWith(
      "/tenants/one/runs?limit=25",
      "GET",
      undefined,
      expect.any(AbortSignal),
    );
  });
  it("does not fall back to a broader endpoint on denied access", async () => {
    vi.mocked(workflowRequest).mockRejectedValue(new Error("Denied"));
    render(<TenantExecutionDebug tenantId="other" />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "could not be loaded",
    );
    expect(workflowRequest).toHaveBeenCalledTimes(1);
  });
});
