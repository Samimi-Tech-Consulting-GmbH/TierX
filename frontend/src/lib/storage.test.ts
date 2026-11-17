import { beforeEach, describe, expect, it } from "vitest";
import {
  STORAGE_KEYS,
  clearSelectedTenant,
  readSelectedTenant,
  writeSelectedTenant,
} from "./storage";

describe("TierX browser storage", () => {
  beforeEach(() => localStorage.clear());
  it("reads, writes and clears the TierX tenant key", () => {
    expect(readSelectedTenant()).toBeNull();
    writeSelectedTenant("tenant-1");
    expect(readSelectedTenant()).toBe("tenant-1");
    expect(localStorage.length).toBe(1);
    expect(localStorage.getItem(STORAGE_KEYS.SELECTED_TENANT)).toBe("tenant-1");
    clearSelectedTenant();
    expect(readSelectedTenant()).toBeNull();
  });
});
