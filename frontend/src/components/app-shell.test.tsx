import { render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { AppShell } from "./app-shell";

const state = vi.hoisted(() => ({ path: "/legal/source", replace: vi.fn() }));
vi.mock("next/navigation", () => ({
  usePathname: () => state.path,
  useRouter: () => ({ replace: state.replace }),
}));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ user: null, isLoading: false }), getHomeRoute: () => "/dashboard" }));
vi.mock("./dashboard/dashboard-shell", () => ({ DashboardShell: () => null }));

beforeEach(() => { state.path = "/legal/source"; state.replace.mockClear(); });

it("allows logged-out visitors to read the source page", () => {
  render(<AppShell><p>Corresponding source</p></AppShell>);
  expect(screen.getByText("Corresponding source")).toBeTruthy();
  expect(state.replace).not.toHaveBeenCalled();
});

it("keeps authenticated routes private", () => {
  state.path = "/dashboard";
  render(<AppShell><p>Private content</p></AppShell>);
  expect(screen.queryByText("Private content")).toBeNull();
  expect(state.replace).toHaveBeenCalledWith("/login");
});
