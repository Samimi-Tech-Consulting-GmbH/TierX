import { cleanup, render, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { listAllClusters, listClusters } from "@/lib/api";
import type { ClusterListItem, PlatformCluster } from "@/lib/types";
import { ClusterListView } from "./cluster-list-view";

vi.mock("@/lib/api", () => ({
  listAllClusters: vi.fn(),
  listClusters: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

// The detail pane authenticates and fetches on its own; the list is what is
// under test here.
vi.mock("@/components/cluster-detail-view", () => ({
  ClusterDetailView: ({
    tenantId,
    clusterId,
  }: {
    tenantId: string;
    clusterId: string;
  }) => <div data-testid="detail">{`${tenantId}/${clusterId}`}</div>,
}));

// Only the fields the list card reads; the analysis summary is a large shape
// the list never renders past its headline.
const cluster = {
  cluster_id: "cluster-1",
  status: "OPEN",
  alert_count: 3,
  severity: { max: "critical" },
  first_seen: "2026-08-01T00:00:00Z",
  last_seen: "2026-08-02T00:00:00Z",
  is_open_for_grouping: true,
  summary: { headline: "Brute force against SSH" },
  analyzed_version: 1,
  requested_analysis_version: 1,
  created_at: "2026-08-01T00:00:00Z",
} as unknown as ClusterListItem;

const ownedCluster = {
  ...cluster,
  tenant_id: "t-9",
  tenant_name: "Demo Tenant",
} as PlatformCluster;

afterEach(cleanup);

describe("ClusterListView across tenants", () => {
  it("lists through the platform endpoint and opens the row's tenant", async () => {
    vi.mocked(listAllClusters).mockResolvedValue({
      items: [ownedCluster],
      total: 1,
      skip: 0,
      limit: 25,
    });

    const { container } = render(
      <ClusterListView tenantId={null} homeHref="/dashboard/admin" />,
    );
    const view = within(container);

    await waitFor(() => expect(listAllClusters).toHaveBeenCalled());
    expect(listClusters).not.toHaveBeenCalled();

    // Owner is visible on the card, and the detail pane opens in that tenant.
    expect(view.getByText("Demo Tenant")).toBeVisible();
    expect(view.getByTestId("detail")).toHaveTextContent("t-9/cluster-1");
  });

  it("sends no time filter across tenants, because the endpoint has none", async () => {
    vi.mocked(listAllClusters).mockResolvedValue({
      items: [ownedCluster],
      total: 1,
      skip: 0,
      limit: 25,
    });

    render(<ClusterListView tenantId={null} homeHref="/dashboard/admin" />);

    await waitFor(() => expect(listAllClusters).toHaveBeenCalled());
    expect(vi.mocked(listAllClusters).mock.calls[0][0]).not.toHaveProperty(
      "created_after",
    );
  });

  it("keeps using the tenant endpoint when scoped to one tenant", async () => {
    vi.mocked(listClusters).mockResolvedValue({ items: [cluster], total: 1 });

    render(
      <ClusterListView
        tenantId="t-1"
        homeHref="/dashboard/admin"
        alertBase="/dashboard/admin/tenants/t-1/alerts"
      />,
    );

    await waitFor(() => expect(listClusters).toHaveBeenCalled());
    expect(listAllClusters).not.toHaveBeenCalled();
    expect(vi.mocked(listClusters).mock.calls[0][0]).toBe("t-1");
  });
});
