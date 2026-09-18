import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { getPlatformDashboardSummary } from "./api";
import { usePlatformDashboard } from "./use-platform-dashboard";

vi.mock("./api", () => ({ getPlatformDashboardSummary: vi.fn() }));

const summary = {
  generated_at: "2026-08-02T12:00:00Z",
  cache_expires_at: "2026-08-02T12:00:30Z",
  coverage: {
    eligible_tenants: 1,
    successful_tenants: 1,
    failed_tenants: 0,
    partial: false,
    failed_sources: [],
    failure_details: [],
  },
  kpis: {
    total_alerts: 1,
    escalated_alerts: 0,
    active_clusters: 1,
    resolved_clusters: 0,
    critical_alerts: 0,
    open_alerts: 1,
    resolved_incidents: 0,
  },
  activity: { daily: [], weekly: [], monthly: [] },
  recent_activity: [],
};

describe("usePlatformDashboard", () => {
  beforeEach(() => {
    vi.mocked(getPlatformDashboardSummary).mockResolvedValue(summary);
  });

  it("loads one complete dashboard snapshot", async () => {
    const { result } = renderHook(() => usePlatformDashboard());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(getPlatformDashboardSummary).toHaveBeenCalledTimes(1);
    expect(result.current.summary).toEqual(summary);
  });
});
