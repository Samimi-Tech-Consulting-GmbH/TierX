import { beforeEach, describe, expect, it } from "vitest";

import {
  LEGACY_STORAGE_KEYS,
  STORAGE_KEYS,
  clearSelectedTenant,
  readSelectedTenant,
  writeSelectedTenant,
} from "./storage";

describe("TierX browser storage compatibility", () => {
  beforeEach(() => localStorage.clear());

  it("migrates legacy values to the canonical key", () => {
    localStorage.setItem(LEGACY_STORAGE_KEYS.SELECTED_TENANT, "legacy-tenant");
    expect(readSelectedTenant()).toBe("legacy-tenant");
    expect(localStorage.getItem(STORAGE_KEYS.SELECTED_TENANT)).toBe("legacy-tenant");
  });

  it("mirrors writes for rollback and clears both families", () => {
    writeSelectedTenant("tenant-1");
    expect(localStorage.getItem(STORAGE_KEYS.SELECTED_TENANT)).toBe("tenant-1");
    expect(localStorage.getItem(LEGACY_STORAGE_KEYS.SELECTED_TENANT)).toBe("tenant-1");
    clearSelectedTenant();
    expect(localStorage.getItem(STORAGE_KEYS.SELECTED_TENANT)).toBeNull();
    expect(localStorage.getItem(LEGACY_STORAGE_KEYS.SELECTED_TENANT)).toBeNull();
  });

  it("retains a selection changed by a rollback deployment", () => {
    writeSelectedTenant("before-rollback");
    localStorage.setItem(LEGACY_STORAGE_KEYS.SELECTED_TENANT, "after-rollback");
    expect(readSelectedTenant()).toBe("after-rollback");
    expect(localStorage.getItem(STORAGE_KEYS.SELECTED_TENANT)).toBe("after-rollback");
  });
});
