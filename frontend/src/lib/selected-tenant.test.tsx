import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useEffect } from "react";

import { listTenants } from "@/lib/api";
import {
  ALL_TENANTS,
  SelectedTenantProvider,
  pathForTenant,
  sectionHref,
  useSelectedTenant,
} from "./selected-tenant";

const push = vi.fn();
let pathname = "/dashboard/admin/tenants/t1";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  usePathname: () => pathname,
}));

vi.mock("@/lib/api", () => ({
  listTenants: vi.fn(),
  getMyTenant: vi.fn(),
}));

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({
    user: { role: "PLATFORM_ADMIN", tenant_id: null, email: "a@b.c" },
  }),
}));

/** Holds the latest context value so tests can drive it from outside React. */
const ctx: { selectTenant: (id: string) => void } = { selectTenant: () => {} };

function Probe() {
  const state = useSelectedTenant();
  useEffect(() => {
    ctx.selectTenant = state.selectTenant;
  }, [state.selectTenant]);
  return <span data-testid="scope">{state.selectedTenantId ?? "none"}</span>;
}

function renderProvider() {
  return render(
    <SelectedTenantProvider>
      <Probe />
    </SelectedTenantProvider>,
  );
}

describe("sectionHref", () => {
  it("keeps tenant users out of the admin route tree", () => {
    expect(sectionHref("alerts", "t1", false)).toBe("/dashboard/t1/alerts");
    expect(sectionHref("clusters", "t1", false)).toBe("/dashboard/t1/clusters");
    expect(sectionHref("alerts", "t1", true)).toBe(
      "/dashboard/admin/tenants/t1/alerts",
    );
  });

  it("uses the shared route for sections that have only one", () => {
    for (const admin of [true, false]) {
      expect(sectionHref("playbooks", "t1", admin)).toBe(
        "/dashboard/t1/playbooks",
      );
      expect(sectionHref("schema-registry", "t1", admin)).toBe(
        "/dashboard/t1/schema-registry",
      );
      expect(sectionHref("knowledge-base", "t1", admin)).toBe(
        "/dashboard/t1/knowledge-base",
      );
    }
  });

  it("resolves the all-tenants view regardless of role", () => {
    expect(sectionHref("alerts", ALL_TENANTS, false)).toBe(
      "/dashboard/admin/alerts",
    );
    expect(sectionHref("knowledge-base", ALL_TENANTS, true)).toBe(
      "/dashboard/admin/knowledge-base",
    );
  });
});

describe("pathForTenant", () => {
  it("keeps the section when switching scope", () => {
    expect(pathForTenant("/dashboard/t1/playbooks", ALL_TENANTS)).toBe(
      "/dashboard/admin/playbooks",
    );
    expect(pathForTenant("/dashboard/admin/playbooks", "t2")).toBe(
      "/dashboard/t2/playbooks",
    );
    expect(
      pathForTenant("/dashboard/admin/tenants/t1/alerts", ALL_TENANTS),
    ).toBe("/dashboard/admin/alerts");
    expect(pathForTenant("/dashboard/t1/knowledge-base", ALL_TENANTS)).toBe(
      "/dashboard/admin/knowledge-base",
    );
  });

  it("does not re-route pages that are not tenant-scoped sections", () => {
    expect(pathForTenant("/dashboard/admin", ALL_TENANTS)).toBeNull();
    expect(pathForTenant("/dashboard/admin/debug", "t2")).toBeNull();
    expect(pathForTenant("/users", "t2")).toBeNull();
    expect(
      pathForTenant("/dashboard/admin/tenants/t1", ALL_TENANTS),
    ).toBeNull();
  });
});

describe("SelectedTenantProvider", () => {
  afterEach(cleanup);

  beforeEach(() => {
    push.mockClear();
    pathname = "/dashboard/admin/tenants/t1";
    localStorage.clear();
    vi.mocked(listTenants).mockResolvedValue([
      { tenant_id: "t1", display_name: "One", name: "one" },
      { tenant_id: "t2", display_name: "Two", name: "two" },
    ] as never);
  });

  it("keeps the choice without navigating when the page is not tenant-scoped", async () => {
    renderProvider();
    await waitFor(() =>
      expect(screen.getByTestId("scope")).toHaveTextContent("t1"),
    );

    await act(async () => {
      ctx.selectTenant(ALL_TENANTS);
    });

    expect(push).not.toHaveBeenCalled();
    expect(screen.getByTestId("scope")).toHaveTextContent(ALL_TENANTS);
    expect(localStorage.getItem("soc_mind_selected_tenant")).toBe(ALL_TENANTS);
    expect(localStorage.getItem("tierx_selected_tenant")).toBe(ALL_TENANTS);
  });

  it("re-routes a tenant-scoped section to the new scope", async () => {
    pathname = "/dashboard/admin/tenants/t1/alerts";
    renderProvider();
    await waitFor(() =>
      expect(screen.getByTestId("scope")).toHaveTextContent("t1"),
    );

    await act(async () => {
      ctx.selectTenant(ALL_TENANTS);
    });

    expect(push).toHaveBeenCalledWith("/dashboard/admin/alerts");
    expect(screen.getByTestId("scope")).toHaveTextContent(ALL_TENANTS);
  });

  it("adopts the scope of a path the user navigates to directly", async () => {
    pathname = "/dashboard/admin/playbooks";
    renderProvider();
    await waitFor(() =>
      expect(screen.getByTestId("scope")).toHaveTextContent(ALL_TENANTS),
    );
  });
});
