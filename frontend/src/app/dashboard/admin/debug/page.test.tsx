import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import DebugPage from "./page";

const scope = vi.hoisted(() => ({ selectedTenantId: "all", loading: false }));
vi.mock("@/lib/selected-tenant", () => ({ ALL_TENANTS: "all", useSelectedTenant: () => scope }));
vi.mock("@/components/workflow-execution-index", () => ({
  WorkflowExecutionIndex: ({ tenantId, platformAdmin }: { tenantId?: string; platformAdmin?: boolean }) =>
    <div data-testid="index">{platformAdmin ? "admin" : "tenant"}:{tenantId || "all"}</div>,
}));
describe("admin Debug scope", () => {
  beforeEach(() => { scope.selectedTenantId = "all"; scope.loading = false; });
  it("uses the workflow index for all tenants", () => {
    render(<DebugPage />);
    expect(screen.getByTestId("index")).toHaveTextContent("admin:all");
  });
  it("respects the selected tenant", () => {
    scope.selectedTenantId = "one";
    render(<DebugPage />);
    expect(screen.getByTestId("index")).toHaveTextContent("admin:one");
  });
  it("does not fetch global data while tenant scope loads", () => {
    scope.loading = true;
    render(<DebugPage />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading tenant scope");
    expect(screen.queryByTestId("index")).not.toBeInTheDocument();
  });
});
