import { describe, expect, it } from "vitest";

import { activeClusterId } from "./cluster-list-view";

describe("cluster deep links", () => {
  it("keeps a requested cluster outside the visible page", () => {
    expect(activeClusterId("bookmarked", ["first", "second"])).toBe("bookmarked");
  });

  it("uses the first visible cluster only without a deep link", () => {
    expect(activeClusterId(null, ["first", "second"])).toBe("first");
  });
});
