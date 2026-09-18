import { render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import LegacyAdminAlertListRedirect from "./list/page";
import LegacyAdminRecentAlertsRedirect from "./recent/page";

const replace = vi.fn();

vi.mock("next/navigation", () => ({
  useParams: () => ({ tenantId: "tenant-1" }),
  useRouter: () => ({ replace }),
}));

describe("legacy admin alert routes", () => {
  beforeEach(() => replace.mockReset());

  it.each([
    ["list", LegacyAdminAlertListRedirect],
    ["recent", LegacyAdminRecentAlertsRedirect],
  ])("redirects the %s route to the redesigned alerts page", async (_, Page) => {
    render(<Page />);
    await waitFor(() =>
      expect(replace).toHaveBeenCalledWith(
        "/dashboard/admin/tenants/tenant-1/alerts",
      ),
    );
  });
});
