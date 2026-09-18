import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  listJiraProjectRoutes,
  listJiraSiteConnections,
  listTenants,
} from "@/lib/api";
import { TenantStatus } from "@/lib/types";
import JiraIntegrationsPage from "./page";

vi.mock("@/lib/api", async () => {
  class ApiError extends Error {
    status = 500;
    detail = "failed";
  }
  return {
    ApiError,
    listJiraSiteConnections: vi.fn(),
    listJiraProjectRoutes: vi.fn(),
    listTenants: vi.fn(),
    listAlertTypeSchemas: vi.fn(),
    createJiraSiteConnection: vi.fn(),
    rotateJiraSiteConnection: vi.fn(),
    revokeJiraSiteConnection: vi.fn(),
    createJiraProjectRoute: vi.fn(),
    updateJiraProjectRoute: vi.fn(),
    setJiraProjectRouteEnabled: vi.fn(),
    deleteJiraProjectRoute: vi.fn(),
  };
});

describe("Jira integrations page", () => {
  it("loads site connections and their project routes", async () => {
    vi.mocked(listTenants).mockResolvedValue([
      {
        tenant_id: "tenant-1",
        name: "tenant-one",
        display_name: "Tenant One",
        db_name: "soc_mind_tenant_one",
        status: TenantStatus.ACTIVE,
        allowed_source_systems: ["SPLUNK"],
        settings: {},
        created_at: "2026-08-24T10:00:00Z",
        updated_at: "2026-08-24T10:00:00Z",
      },
    ]);
    vi.mocked(listJiraSiteConnections).mockResolvedValue([
      {
        integration_id: "connection-1",
        name: "Samimi Jira",
        jira_cloud_id: "cloud-1",
        jira_site_url: "https://example.atlassian.net",
        state: "ACTIVE",
        secret_prefix: "socjira_test",
        route_count: 1,
        created_at: "2026-08-24T10:00:00Z",
        updated_at: "2026-08-24T10:00:00Z",
        created_by: "admin@example.com",
      },
    ]);
    vi.mocked(listJiraProjectRoutes).mockResolvedValue([
      {
        route_id: "route-1",
        integration_id: "connection-1",
        project_key: "DEMO",
        tenant_id: "tenant-1",
        tenant_name: "Tenant One",
        source_system: "SPLUNK",
        alert_type: "splunk.notable.endpoint_malware",
        enabled: true,
        revision: 1,
        effective_schema_id: "schema-1",
        effective_schema_version: "1.0.0",
        event_timestamp_path: "result._time",
        created_at: "2026-08-24T10:00:00Z",
        updated_at: "2026-08-24T10:00:00Z",
        created_by: "admin@example.com",
        updated_by: "admin@example.com",
      },
    ]);

    render(<JiraIntegrationsPage />);

    await waitFor(() => expect(screen.getAllByText("Samimi Jira")).toHaveLength(2));
    expect(await screen.findByText("DEMO")).toBeVisible();
    expect(screen.getByText(/Tenant One · SPLUNK/)).toBeVisible();
    expect(listJiraProjectRoutes).toHaveBeenCalledWith("connection-1");
  });
});
