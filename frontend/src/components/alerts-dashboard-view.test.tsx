import { render, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { scopedApi } from "@/lib/tenant-scope";
import { AlertsDashboardView } from "./alerts-dashboard-view";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams("q=needle&since=24"),
}));

vi.mock("@/lib/tenant-scope", () => ({
  scopedApi: vi.fn(),
  scopedRoutes: () => ({
    home: "/home",
    alerts: "/alerts",
    clusters: "/clusters",
  }),
}));

vi.mock("@/components/alert-list-view", () => ({
  AlertListView: () => <div>Alert list</div>,
}));

describe("AlertsDashboardView", () => {
  it("loads severity KPIs with the list's applied search and period filters", async () => {
    const alertStats = vi.fn(() =>
      Promise.resolve({
        filtered_total: 0,
        severity: {
          CRITICAL: 0,
          HIGH: 0,
          MEDIUM: 0,
          LOW: 0,
          UNKNOWN: 0,
        },
      }),
    );
    vi.mocked(scopedApi).mockReturnValue({ alertStats } as never);

    render(
      <AlertsDashboardView tenantId="tenant-1" scope="tenant" />,
    );

    await waitFor(() =>
      expect(alertStats).toHaveBeenCalledWith("tenant-1", {
        q: "needle",
        since_hours: 24,
      }),
    );
  });
});
