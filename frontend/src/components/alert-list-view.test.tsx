import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { listTenantAlerts } from "@/lib/api";
import { AlertListView } from "./alert-list-view";

vi.mock("@/lib/api", () => ({ listTenantAlerts: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

describe("AlertListView", () => {
  it("uses semantic links for identifying and action cells", async () => {
    vi.mocked(listTenantAlerts).mockResolvedValue({
      total: 1,
      items: [
        {
          id: "mongo-id",
          alert_id: "alert-123",
          tenant_id: "tenant-1",
          alert_type: "endpoint.malware",
          source_system: "SPLUNK",
          severity: "CRITICAL",
          normalized_payload: { "event.severity": "kritisch" },
          created_at: "2026-08-02T12:00:00Z",
        },
      ],
    });

    render(
      <AlertListView
        tenantId="tenant-1"
        detailBase="/dashboard/admin/tenants/tenant-1/alerts"
      />,
    );

    await waitFor(() => expect(screen.getByText("alert-123")).toBeVisible());
    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(3);
    expect(
      links.every((link) => link.getAttribute("href")?.endsWith("/alert-123")),
    ).toBe(true);
    expect(screen.getByText("Critical")).toBeVisible();
  });
});
