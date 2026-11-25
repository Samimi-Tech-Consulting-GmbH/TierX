import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Sidebar } from "./sidebar";
const state = vi.hoisted(() => ({
  path: "/dashboard/admin/debug/runs/one/run",
  role: "PLATFORM_ADMIN",
}));
vi.mock("next/navigation", () => ({ usePathname: () => state.path }));
vi.mock("@/lib/auth", () => ({
  useAuth: () => ({
    user: { role: state.role, tenant_id: "one" },
    logout: vi.fn(),
  }),
}));
vi.mock("@/lib/selected-tenant", async (original) => ({
  ...(await original<typeof import("@/lib/selected-tenant")>()),
  useSelectedTenant: () => ({ selectedTenantId: "one" }),
}));
vi.mock("@/components/dashboard/tenant-switcher", () => ({
  TenantSwitcher: () => null,
}));
vi.mock("@/components/dashboard/settings-menu", () => ({
  SettingsMenu: () => null,
}));
vi.mock("@/components/product-links", () => ({ ProductLinks: () => null }));
describe("Execution navigation selection", () => {
  beforeEach(() => {
    state.role = "PLATFORM_ADMIN";
    state.path = "/dashboard/admin/debug/runs/one/run";
  });
  it("selects Debug, not Workflows, for an admin execution", () => {
    render(<Sidebar />);
    expect(screen.getByRole("link", { name: "Debug" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("link", { name: "Workflows" })).not.toHaveAttribute(
      "aria-current",
    );
  });
  it("keeps tenant execution bookmarks in Debug for platform admins", () => {
    state.path = "/dashboard/one/debug/runs/run";
    render(<Sidebar />);
    expect(screen.getByRole("link", { name: "Debug" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });
  it("provides tenant operators their own Debug navigation without an admin route", () => {
    state.role = "TENANT_OPERATOR";
    state.path = "/dashboard/one/debug/runs/run";
    render(<Sidebar />);
    expect(screen.getByRole("link", { name: "Debug" })).toHaveAttribute(
      "href",
      "/dashboard/one/debug",
    );
    expect(screen.getByRole("link", { name: "Debug" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(
      screen.queryByRole("link", { name: "Workflows" }),
    ).not.toBeInTheDocument();
  });
});
