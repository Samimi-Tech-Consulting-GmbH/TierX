import {
  render,
  screen,
  fireEvent,
  cleanup,
  waitFor,
} from "@testing-library/react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { ResourceLibrary, TenantSelection } from "./workflow-library";
import { listTenantPage } from "@/lib/api";
vi.mock("@/lib/api", () => ({ listTenantPage: vi.fn() }));
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});
describe("Workflow library experience", () => {
  it("searches names and descriptions and opens a definition without an editor shell", () => {
    const open = vi.fn(),
      create = vi.fn();
    render(
      <ResourceLibrary
        title="Agents"
        description="Investigators"
        createLabel="Create agent"
        onCreate={create}
        items={[
          {
            id: "one",
            name: "Endpoint investigator",
            description: "Check process evidence",
            metadata: "Local model",
            status: "Published v2",
            onOpen: open,
          },
          {
            id: "two",
            name: "Network investigator",
            description: "Network evidence",
            metadata: "Local model",
            status: "Draft",
            onOpen: open,
          },
        ]}
      />,
    );
    fireEvent.change(screen.getByRole("textbox", { name: "Search agents" }), {
      target: { value: "process" },
    });
    expect(
      screen.queryByRole("heading", { name: "Network investigator" }),
    ).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: /Endpoint investigator/ }),
    );
    expect(open).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole("button", { name: "Create agent" }));
    expect(create).toHaveBeenCalledOnce();
  });
  it("distinguishes loading, no results and a failed lookup", () => {
    const props = {
      title: "Playbooks",
      description: "Reusable flows",
      createLabel: "Create playbook",
      onCreate: vi.fn(),
      items: [],
    };
    const view = render(<ResourceLibrary {...props} loading />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading");
    view.rerender(<ResourceLibrary {...props} error="Could not load" />);
    expect(screen.getByRole("alert")).toHaveTextContent("Could not load");
    expect(
      screen.getByText(/The library could not be loaded/),
    ).toBeInTheDocument();
  });
  it("selects tenant names and uses server pagination", async () => {
    vi.mocked(listTenantPage).mockResolvedValue({
      items: [
        { tenant_id: "tenant-a", name: "alpha", display_name: "Alpha SOC" },
      ],
      total: 30,
      skip: 0,
      limit: 25,
    } as Awaited<ReturnType<typeof listTenantPage>>);
    const change = vi.fn();
    render(<TenantSelection value={[]} onChange={change} multiple />);
    await screen.findByRole("option", { name: "Alpha SOC" });
    fireEvent.change(screen.getByRole("combobox", { name: "Tenant access" }), {
      target: { value: "tenant-a" },
    });
    expect(change).toHaveBeenCalledWith(["tenant-a"]);
    fireEvent.click(screen.getByRole("button", { name: "Next tenants" }));
    await waitFor(() =>
      expect(listTenantPage).toHaveBeenLastCalledWith({
        search: undefined,
        skip: 25,
        limit: 25,
      }),
    );
  });
});
