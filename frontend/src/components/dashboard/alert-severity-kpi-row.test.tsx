import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AlertSeverityKpiRow } from "./alert-severity-kpi-row";

describe("AlertSeverityKpiRow", () => {
  it("shows canonical severity counts and reports unknown data separately", () => {
    render(
      <AlertSeverityKpiRow
        stats={{
          filtered_total: 21,
          severity: {
            CRITICAL: 4,
            HIGH: 5,
            MEDIUM: 6,
            LOW: 3,
            UNKNOWN: 3,
          },
        }}
        loading={false}
        error={null}
      />,
    );

    for (const value of ["4", "5", "6", "3"]) {
      expect(screen.getAllByText(value).length).toBeGreaterThan(0);
    }
    expect(screen.getByRole("alert")).toHaveTextContent(
      "3 filtered alert(s) have unknown severity",
    );
  });
});
