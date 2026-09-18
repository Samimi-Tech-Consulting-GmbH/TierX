import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { listEnrichmentActions, listTenantPage } from "@/lib/api";
import { TenantStatus } from "@/lib/types";
import EnrichmentActionsPage from "./page";

vi.mock("@/lib/api", async () => {
  class ApiError extends Error {
    status = 500;
    detail = "failed";
  }
  return {
    ApiError,
    listEnrichmentActions: vi.fn(),
    listTenantPage: vi.fn(),
    createEnrichmentAction: vi.fn(),
    updateEnrichmentAction: vi.fn(),
    rotateEnrichmentActionSecret: vi.fn(),
    deleteEnrichmentAction: vi.fn(),
  };
});

describe("enrichment actions page", () => {
  it("shows safe metadata, tenant scope, and the long-timeout warning", async () => {
    vi.mocked(listTenantPage).mockResolvedValue({
      items: [{
        tenant_id: "tenant-1",
        name: "tenant-one",
        display_name: "Tenant One",
        db_name: "soc_mind_tenant_one",
        status: TenantStatus.ACTIVE,
        allowed_source_systems: ["SPLUNK"],
        settings: {},
        created_at: "2026-08-31T10:00:00Z",
        updated_at: "2026-08-31T10:00:00Z",
      }],
      total: 1,
      skip: 0,
      limit: 200,
    });
    vi.mocked(listEnrichmentActions).mockResolvedValue({
      items: [
        {
          action_code: "example-observer",
          name: "Example observer",
          description: "Safe deterministic evidence.",
          url: "https://tierx.example.com/examples/enrichment-actions/example-observer/",
          timeout_seconds: 300,
          enabled: true,
          tenant_scope: "SELECTED_TENANTS",
          tenant_ids: ["tenant-1"],
          key_id: "eak_test",
          configuration_checksum: "a".repeat(64),
          created_at: "2026-08-31T10:00:00Z",
          updated_at: "2026-08-31T10:00:00Z",
          created_by: "admin@example.com",
          updated_by: "admin@example.com",
        },
      ],
      total: 1,
      skip: 0,
      limit: 200,
    });

    render(<EnrichmentActionsPage />);

    expect(await screen.findByText("Example observer")).toBeVisible();
    expect(screen.getByText("Tenant One")).toBeVisible();
    expect(screen.queryByText(/delay correlation/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Edit/ }));
    fireEvent.change(screen.getByLabelText("Timeout (1–1800 seconds)"), {
      target: { value: "301" },
    });
    await waitFor(() =>
      expect(screen.getByText(/delay correlation, analysis/)).toBeVisible(),
    );
  });
});
