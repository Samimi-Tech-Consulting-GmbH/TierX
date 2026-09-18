import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { listTenantPage } from "@/lib/api";
import { TenantStatus } from "@/lib/types";
import { TenantPicker } from "./tenant-picker";

vi.mock("@/lib/api", () => ({ listTenantPage: vi.fn() }));

describe("TenantPicker", () => {
  it("uses the server page total and semantic tenant links", async () => {
    vi.mocked(listTenantPage).mockResolvedValue({
      total: 250,
      skip: 0,
      limit: 10,
      items: [
        {
          tenant_id: "tenant-1",
          name: "tenant-one",
          display_name: "Tenant One",
          db_name: "tenant_one",
          status: TenantStatus.ACTIVE,
          allowed_source_systems: [],
          settings: {},
          created_at: "2026-08-02T12:00:00Z",
          updated_at: "2026-08-02T12:00:00Z",
        },
      ],
    });

    render(
      <TenantPicker
        title="Tenants"
        description="Choose a tenant"
        hrefFor={(tenant) => `/tenants/${tenant.tenant_id}`}
      />,
    );

    await waitFor(() => expect(screen.getByText("Tenant One")).toBeVisible());
    expect(listTenantPage).toHaveBeenCalledWith({
      skip: 0,
      limit: 10,
      search: undefined,
      status: undefined,
    });
    expect(screen.getByText("250 tenants")).toBeVisible();
    expect(screen.getByRole("link", { name: "Tenant One" })).toHaveAttribute(
      "href",
      "/tenants/tenant-1",
    );
    expect(screen.getByText("1–10 of 250")).toBeVisible();
  });
});
