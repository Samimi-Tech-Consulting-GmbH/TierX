import {
  cleanup,
  fireEvent,
  render,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  listAllAlertTypeSchemas,
  listAllPlaybooks,
  listAlertTypeSchemas,
  listPlaybooks,
  getPlatformPlaybookStats,
  getPlaybookStats,
} from "@/lib/api";
import type { PlatformPlaybook, PlatformSchema } from "@/lib/types";
import { UserRole } from "@/lib/types";
import { PlaybooksView } from "./playbooks-view";
import { SchemaRegistryView } from "./schema-registry-view";

vi.mock("@/lib/api", () => ({
  listAllAlertTypeSchemas: vi.fn(),
  listAlertTypeSchemas: vi.fn(),
  listAllPlaybooks: vi.fn(),
  listPlaybooks: vi.fn(),
  getPlatformPlaybookStats: vi.fn(() =>
    Promise.resolve({
      total_playbooks: 0,
      active_playbooks: 0,
      system_playbooks: 0,
      covered_alert_types: 0,
    }),
  ),
  getPlaybookStats: vi.fn(() =>
    Promise.resolve({
      total_playbooks: 0,
      active_playbooks: 0,
      system_playbooks: 0,
      covered_alert_types: 0,
    }),
  ),
  getMyTenant: vi.fn(() => Promise.resolve(null)),
  activateAlertTypeSchema: vi.fn(),
  ApiError: class extends Error {},
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: { role: UserRole.PLATFORM_ADMIN, tenant_id: null } }),
}));

// The detail panes fetch on their own; the lists are what is under test.
vi.mock("@/components/schema-detail-view", () => ({
  useSchemaDetail: () => ({ displayDoc: null, loading: false }),
  SchemaDetailRail: () => <div data-testid="schema-detail" />,
  SchemaCriticalFieldsPanel: () => null,
}));
vi.mock("@/components/playbook-detail-view", () => ({
  PlaybookDetailView: ({ tenantId }: { tenantId: string }) => (
    <div data-testid="playbook-detail">{tenantId}</div>
  ),
}));

const schema = {
  schema_id: "schema-1",
  alert_type: "security.phishing",
  version: 2,
  is_active: true,
  field_mapping: {},
  critical_fields: [],
  updated_at: "2026-08-01T00:00:00Z",
  tenant_id: "t-7",
  tenant_name: "Demo Tenant",
} as unknown as PlatformSchema;

const playbook = {
  playbook_id: "pb-1",
  playbook_name: "Phishing triage",
  version: 1,
  alert_types: ["security.phishing"],
  is_active: true,
  is_system: false,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
  tenant_id: "t-7",
  tenant_name: "Demo Tenant",
} as PlatformPlaybook;

afterEach(cleanup);

describe("SchemaRegistryView across tenants", () => {
  it("lists through the platform endpoint and shows each row's owner", async () => {
    vi.mocked(listAllAlertTypeSchemas).mockResolvedValue({
      items: [schema],
      total: 1,
      skip: 0,
      limit: 25,
    });

    const { container } = render(<SchemaRegistryView tenantId={null} />);
    const view = within(container);

    // The list only paints once the load promise settles, so wait on the row.
    await waitFor(() => expect(view.getByText("Demo Tenant")).toBeVisible());
    expect(listAlertTypeSchemas).not.toHaveBeenCalled();
    expect(view.getByText("Tenant")).toBeVisible();
    expect(view.getByText(/All tenants · 1 schema/)).toBeVisible();
  });

  it("keeps using the tenant endpoint when scoped to one tenant", async () => {
    vi.mocked(listAlertTypeSchemas).mockResolvedValue({
      items: [schema],
      total: 1,
      skip: 0,
      limit: 25,
    });

    const { container } = render(<SchemaRegistryView tenantId="t-7" />);
    const view = within(container);

    await waitFor(() => expect(view.getByText("security.phishing")).toBeVisible());
    expect(listAllAlertTypeSchemas).not.toHaveBeenCalled();
    // No Tenant column when every row belongs to the same tenant.
    expect(view.queryByText("Tenant")).toBeNull();
  });

  it("keeps the status filter usable while searching one tenant", async () => {
    vi.mocked(listAlertTypeSchemas).mockResolvedValue({
      items: [schema],
      total: 1,
      skip: 0,
      limit: 25,
    });

    const { container } = render(<SchemaRegistryView tenantId="t-7" />);
    const view = within(container);

    await waitFor(() => expect(listAlertTypeSchemas).toHaveBeenCalled());
    fireEvent.change(
      view.getByPlaceholderText("Search alert type (e.g. phishing, malware)"),
      { target: { value: "phish" } },
    );

    // The tenant service ANDs `q` with `is_active`, so neither the control nor
    // the parameter is suppressed.
    await waitFor(() =>
      expect(vi.mocked(listAlertTypeSchemas).mock.calls.at(-1)?.[1]).toMatchObject(
        { q: "phish" },
      ),
    );
    expect(view.getByRole("combobox", { name: "Status" })).not.toBeDisabled();
  });

  it("suppresses the status filter while searching across tenants", async () => {
    vi.mocked(listAllAlertTypeSchemas).mockResolvedValue({
      items: [schema],
      total: 1,
      skip: 0,
      limit: 25,
    });

    const { container } = render(<SchemaRegistryView tenantId={null} />);
    const view = within(container);

    await waitFor(() => expect(listAllAlertTypeSchemas).toHaveBeenCalled());
    fireEvent.change(
      view.getByPlaceholderText("Search alert type (e.g. phishing, malware)"),
      { target: { value: "phish" } },
    );

    await waitFor(() =>
      expect(
        vi.mocked(listAllAlertTypeSchemas).mock.calls.at(-1)?.[0],
      ).toMatchObject({ q: "phish", is_active: undefined }),
    );
    expect(view.getByRole("combobox", { name: "Status" })).toBeDisabled();
  });
});

describe("PlaybooksView across tenants", () => {
  it("pages through the platform endpoint and opens the row's tenant", async () => {
    vi.mocked(listAllPlaybooks).mockResolvedValue({
      items: [playbook],
      total: 1,
      skip: 0,
      limit: 25,
    });

    const { container } = render(<PlaybooksView tenantId={null} />);
    const view = within(container);

    // The view renders a loading placeholder until the load promise settles.
    await waitFor(() =>
      expect(view.getByTestId("playbook-detail")).toHaveTextContent("t-7"),
    );
    expect(listPlaybooks).not.toHaveBeenCalled();
    expect(vi.mocked(listAllPlaybooks).mock.calls[0][0]).toMatchObject({
      skip: 0,
      limit: 25,
    });
    expect(await view.findByTestId("playbook-detail")).toHaveTextContent("t-7");
    expect(await view.findByText("Demo Tenant")).toBeVisible();
  });

  it("counts every match beside the list title, not the rows on the page", async () => {
    vi.mocked(listAllPlaybooks).mockResolvedValue({
      items: [playbook],
      total: 137,
      skip: 0,
      limit: 25,
    });

    const { container } = render(<PlaybooksView tenantId={null} />);

    await waitFor(() => expect(within(container).getByText("137")).toBeVisible());
  });

  it("renders authoritative platform KPI cards instead of page-derived counts", async () => {
    vi.mocked(listAllPlaybooks).mockResolvedValue({
      items: [playbook],
      total: 400,
      skip: 0,
      limit: 25,
    });
    vi.mocked(getPlatformPlaybookStats).mockResolvedValue({
      total_playbooks: 400,
      active_playbooks: 317,
      system_playbooks: 12,
      covered_alert_types: 86,
    });

    const { container } = render(<PlaybooksView tenantId={null} />);
    const view = within(container);

    await waitFor(() => expect(view.getByText("Active playbooks")).toBeVisible());
    expect(view.getByText("317")).toBeVisible();
    expect(getPlatformPlaybookStats).toHaveBeenCalledTimes(1);
  });

  it("keeps the tenant scope on its own endpoint and KPI cards", async () => {
    vi.mocked(listPlaybooks).mockResolvedValue([playbook]);
    vi.mocked(getPlaybookStats).mockResolvedValue({
      total_playbooks: 1,
      active_playbooks: 1,
      system_playbooks: 0,
      covered_alert_types: 1,
    });

    const { container } = render(<PlaybooksView tenantId="t-7" />);
    const view = within(container);

    await waitFor(() => expect(view.getByText("Active playbooks")).toBeVisible());
    expect(listAllPlaybooks).not.toHaveBeenCalled();
    expect(await within(container).findByText("Active playbooks")).toBeVisible();
  });
});
