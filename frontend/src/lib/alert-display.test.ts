import { describe, expect, it } from "vitest";

import { isCriticalSeverity, severityFromValue } from "./alert-display";

describe("severity display", () => {
  it.each([5, "5", "critical", "Critical", "kritisch"])(
    "recognizes %s as critical",
    (value) => {
      expect(isCriticalSeverity(value)).toBe(true);
      expect(severityFromValue(value).label).toBe("Critical");
    },
  );

  it.each([[4, "High"], [3, "Medium"], [2, "Low"], [1, "Low"]])(
    "maps numeric severity %s",
    (value, label) => expect(severityFromValue(value).label).toBe(label),
  );
});
