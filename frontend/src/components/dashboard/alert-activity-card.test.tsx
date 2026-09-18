import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { PlatformDashboardSummary } from "@/lib/types";
import { AlertActivityCard } from "./alert-activity-card";

const bucket = {
  start_at: "2026-08-02T09:00:00Z",
  end_at: "2026-08-02T12:00:00Z",
  alerts: 2,
  dead_letters: 0,
};

const summary: PlatformDashboardSummary = {
  generated_at: bucket.end_at,
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
    total_alerts: 2,
    escalated_alerts: 0,
    active_clusters: 1,
    resolved_clusters: 0,
    critical_alerts: 0,
    open_alerts: 2,
    resolved_incidents: 0,
  },
  activity: { daily: [bucket], weekly: [bucket], monthly: [bucket] },
  recent_activity: [],
};

describe("AlertActivityCard", () => {
  it("switches preloaded granularities without loading again", () => {
    render(
      <AlertActivityCard summary={summary} loading={false} error={null} />,
    );
    expect(screen.getByText("Alert Activity (Last 7 Days)")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Daily" }));
    expect(screen.getByText("Alert Activity (Last 24 Hours)")).toBeVisible();
  });
});
