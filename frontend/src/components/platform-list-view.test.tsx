import {
  cleanup,
  fireEvent,
  render,
  waitFor,
  within,
} from "@testing-library/react";
import { Bell } from "lucide-react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { PlatformPage } from "@/lib/types";
import { PlatformListView } from "./platform-list-view";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

type Row = { alert_id: string; tenant_id: string; tenant_name: string };

type FetchParams = {
  q?: string;
  skip: number;
  limit: number;
  since_hours?: number;
};

const onePage: PlatformPage<Row> = {
  items: [{ alert_id: "alert-1", tenant_id: "t-1", tenant_name: "Demo" }],
  total: 1,
  skip: 0,
  limit: 25,
};

function renderView(showPeriodFilter = true, page: PlatformPage<Row> = onePage) {
  const fetchPage = vi.fn<(params: FetchParams) => Promise<PlatformPage<Row>>>(
    () => Promise.resolve(page),
  );
  const { container } = render(
    <PlatformListView<Row>
      title="Alerts Management"
      description="Alerts from every tenant."
      icon={Bell}
      searchPlaceholder="Search…"
      columns={[
        { key: "alert", header: "Alert", render: (row) => row.alert_id },
      ]}
      fetchPage={fetchPage}
      rowKey={(row) => row.alert_id}
      hrefFor={() => null}
      emptyLabel="No alerts on the platform yet."
      showPeriodFilter={showPeriodFilter}
    />,
  );
  // Queries are scoped to this render: the shared vitest setup does not
  // register RTL's auto-cleanup, so a document-wide query can see an earlier
  // test's tree.
  return { fetchPage, view: within(container) };
}

afterEach(cleanup);

describe("PlatformListView period filter", () => {
  it("sends no since_hours until a period is applied", async () => {
    const { fetchPage } = renderView();

    await waitFor(() => expect(fetchPage).toHaveBeenCalled());
    expect(fetchPage.mock.calls[0][0].since_hours).toBeUndefined();
  });

  it("shows the period control defaulted to all time", async () => {
    const { fetchPage, view } = renderView();

    await waitFor(() => expect(fetchPage).toHaveBeenCalled());
    expect(view.getByText("Period:")).toBeVisible();
    // Named, because the pagination footer contributes a combobox too.
    expect(view.getByRole("combobox", { name: "Period" })).toHaveTextContent(
      "All time",
    );
  });

  it("searches as it is typed, once the typing settles", async () => {
    const { fetchPage, view } = renderView();

    await waitFor(() => expect(fetchPage).toHaveBeenCalledTimes(1));

    const box = view.getByPlaceholderText("Search…");
    fireEvent.change(box, { target: { value: "b" } });
    fireEvent.change(box, { target: { value: "br" } });
    fireEvent.change(box, { target: { value: "brute" } });

    // No button press: the settled term reaches the server on its own, and a
    // burst of keystrokes costs one request rather than one each.
    await waitFor(() => expect(fetchPage).toHaveBeenCalledTimes(2));
    expect(fetchPage.mock.calls[1][0].q).toBe("brute");
  });

  it("omits the period control, and its button, where nothing is applied", async () => {
    const { fetchPage, view } = renderView(false);

    await waitFor(() => expect(fetchPage).toHaveBeenCalled());
    expect(view.queryByText("Period:")).toBeNull();
    // Search needs no button, so with no filters there is nothing to press.
    expect(
      view.queryByRole("button", { name: /Apply filters|Search/ }),
    ).toBeNull();
  });
});

describe("PlatformListView record count", () => {
  it("keeps the singular for one record", async () => {
    const { fetchPage, view } = renderView();

    await waitFor(() => expect(fetchPage).toHaveBeenCalled());
    expect(view.getByText(/All tenants · 1 record$/)).toBeVisible();
  });

  it("pluralises the whole word, not the stem", async () => {
    const { fetchPage, view } = renderView(true, {
      ...onePage,
      items: [
        { alert_id: "alert-1", tenant_id: "t-1", tenant_name: "Demo" },
        { alert_id: "alert-2", tenant_id: "t-1", tenant_name: "Demo" },
      ],
      total: 39,
    });

    await waitFor(() => expect(fetchPage).toHaveBeenCalled());
    expect(view.getByText(/All tenants · 39 records$/)).toBeVisible();
  });

  it("counts matches while searching", async () => {
    const { fetchPage, view } = renderView();

    await waitFor(() => expect(fetchPage).toHaveBeenCalledTimes(1));
    fireEvent.change(view.getByPlaceholderText("Search…"), {
      target: { value: "brute" },
    });

    await waitFor(() => expect(fetchPage).toHaveBeenCalledTimes(2));
    expect(view.getByText(/All tenants · 1 match$/)).toBeVisible();
  });
});
