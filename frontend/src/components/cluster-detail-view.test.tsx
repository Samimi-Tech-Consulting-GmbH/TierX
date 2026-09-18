import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  getCluster,
  getClusterAlerts,
  getClusterSummaryHistory,
  listClusterAnalysisRuns,
} from "@/lib/api";
import type { AlertDocument, ClusterDocument } from "@/lib/types";
import { UserRole } from "@/lib/types";
import { ClusterDetailView } from "./cluster-detail-view";

vi.mock("@/lib/api", () => ({
  addClusterNote: vi.fn(),
  assignCluster: vi.fn(),
  getCluster: vi.fn(),
  getClusterAlerts: vi.fn(),
  getClusterSummaryHistory: vi.fn(),
  listClusterAnalysisRuns: vi.fn(),
  retryClusterAnalysis: vi.fn(),
  setClusterVerdict: vi.fn(),
  updateClusterStatus: vi.fn(),
}));

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({
    user: { role: UserRole.PLATFORM_ADMIN, tenant_id: null },
  }),
}));

vi.mock("sonner", () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

const now = "2026-08-24T12:00:00Z";
const cluster = {
  cluster_id: "cluster-1",
  tenant_id: "tenant-1",
  lead_alert_id: "alert-1",
  alert_ids: ["alert-1"],
  alert_count: 251,
  affected_host_count: 231,
  is_open_for_grouping: true,
  debounce_expires_at: now,
  grouping_window_expires_at: now,
  correlation_basis: {},
  first_seen: now,
  last_seen: now,
  severity: { max: 5 },
  analysis_type: "CLUSTER_ANALYSIS",
  analyzed_version: 0,
  analyzed_alert_count: 0,
  requested_analysis_version: 1,
  summary: null,
  status: "OPEN",
  analyst_notes: [],
  created_at: now,
  updated_at: now,
} as ClusterDocument;

const alert = {
  alert_id: "stale-alert",
  tenant_id: "tenant-1",
  alert_type: "endpoint.malware",
  source_system: "SPLUNK",
  severity: "CRITICAL",
  normalized_payload: {},
  created_at: now,
} as AlertDocument;

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("ClusterDetailView", () => {
  it("uses the exact host count and clears stale rows after a page failure", async () => {
    vi.mocked(getCluster).mockResolvedValue(cluster);
    vi.mocked(getClusterSummaryHistory).mockResolvedValue({ items: [] });
    vi.mocked(listClusterAnalysisRuns).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(getClusterAlerts)
      .mockResolvedValueOnce({ items: [alert], total: 51 })
      .mockRejectedValueOnce(new Error("page unavailable"));

    render(
      <ClusterDetailView
        tenantId="tenant-1"
        clusterId="cluster-1"
        alertBase="/alerts"
      />,
    );

    await waitFor(() => expect(screen.getByText("stale-alert")).toBeVisible());
    expect(screen.getByText("Affected Hosts").nextSibling).toHaveTextContent(
      "231",
    );

    fireEvent.click(screen.getByRole("button", { name: "Next page" }));

    await waitFor(() =>
      expect(screen.getByText("Failed to load member alerts.")).toBeVisible(),
    );
    expect(screen.queryByText("stale-alert")).toBeNull();
    expect(screen.queryByLabelText("Pagination")).toBeNull();
  });
});
