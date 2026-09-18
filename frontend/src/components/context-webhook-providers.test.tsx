import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AlertDetailView } from "./alert-detail-view";
import { PlaybookDetailView } from "./playbook-detail-view";

const getAlert = vi.fn();

vi.mock("@/lib/tenant-scope", () => ({
  scopedApi: () => ({ getAlert }),
  scopedRoutes: () => ({ alerts: "/alerts" }),
}));

vi.mock("@/components/alert-analysis-panel", () => ({
  AlertAnalysisPanel: () => <div>Analysis panel</div>,
}));

const getPlaybook = vi.fn();
const listPlaybookVersions = vi.fn();

vi.mock("@/lib/api", () => ({
  ApiError: class ApiError extends Error {
    status = 500;
    detail = "error";
  },
  getPlaybook: (...args: unknown[]) => getPlaybook(...args),
  listPlaybookVersions: (...args: unknown[]) => listPlaybookVersions(...args),
  deletePlaybook: vi.fn(),
  replacePlaybook: vi.fn(),
  getTenantWebhookSecret: vi.fn(),
  rotateTenantWebhookSecret: vi.fn(),
  deleteTenantWebhookSecret: vi.fn(),
  getPlaybookWebhookSecret: vi.fn(),
  rotatePlaybookWebhookSecret: vi.fn(),
  deletePlaybookWebhookSecret: vi.fn(),
}));

describe("multiple playbook context providers", () => {
  it("shows every persisted provider outcome on an alert", async () => {
    getAlert.mockResolvedValue({
      id: "mongo-alert",
      alert_id: "alert-1",
      tenant_id: "tenant-1",
      alert_type: "endpoint.malware",
      source_system: "SPLUNK",
      prompt_webhook_contexts: [
        {
          webhook_id: "threat-intel",
          webhook_name: "Threat intelligence",
          config_order: 0,
          status: "SUCCEEDED",
          delivery_id: "delivery-1",
          duration_ms: 750,
          prompt_footer: "Threat context footer",
        },
        {
          webhook_id: "asset-context",
          webhook_name: "Asset context",
          config_order: 1,
          status: "FAILED",
          delivery_id: "delivery-2",
          error_type: "WEBHOOK_TIMEOUT",
        },
      ],
    });

    render(
      <AlertDetailView
        tenantId="tenant-1"
        alertId="alert-1"
        scope="tenant"
      />,
    );

    await waitFor(() => expect(screen.getByText("Threat intelligence")).toBeVisible());
    expect(screen.getByText("Asset context")).toBeVisible();
    expect(screen.getByText("Threat context footer")).toBeVisible();
    expect(screen.getByText("WEBHOOK_TIMEOUT")).toBeVisible();
    expect(screen.getByText("750 ms (0.8 s)")).toBeVisible();
    expect(screen.queryByText(/X-TierX-Signature/)).not.toBeInTheDocument();
    expect(screen.queryByText(/X-SOC-Mind-Signature/)).not.toBeInTheDocument();
  });

  it("shows the ordered provider configuration with one shared credential model", async () => {
    getPlaybook.mockResolvedValue({
      playbook_id: "pb-1",
      version: 2,
      tenant_id: "tenant-1",
      playbook_name: "Endpoint analysis",
      actions: [],
      prompt: "Analyze safely.",
      description: "Provider test.",
      alert_types: ["endpoint.malware"],
      is_active: true,
      is_system: false,
      context_webhook: null,
      context_webhooks: [
        {
          webhook_id: "threat-intel",
          name: "Threat intelligence",
          enabled: true,
          url: "https://customer.example/threat",
          timeout_seconds: 5,
        },
        {
          webhook_id: "asset-context",
          name: "Asset context",
          enabled: false,
          url: "https://customer.example/assets",
          timeout_seconds: 3,
        },
      ],
      created_by: "admin@example.com",
      created_at: "2026-08-10T00:00:00Z",
      updated_at: "2026-08-10T00:00:00Z",
    });
    listPlaybookVersions.mockResolvedValue([]);

    render(
      <PlaybookDetailView
        tenantId="tenant-1"
        playbookId="pb-1"
        canWrite={false}
      />,
    );

    await waitFor(() => expect(screen.getAllByText("Threat intelligence").length).toBeGreaterThan(0));
    expect(screen.getAllByText("Asset context").length).toBeGreaterThan(0);
    expect(
      await screen.findByText(
        /All providers share the effective playbook or tenant credential/,
      ),
    ).toBeVisible();
    expect((await screen.findAllByText("threat-intel · order 1")).length).toBeGreaterThan(0);
    expect((await screen.findAllByText("asset-context · order 2")).length).toBeGreaterThan(0);
  });
});
