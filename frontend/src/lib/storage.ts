export const STORAGE_KEYS = {
  TOKEN: "tierx_token",
  ONBOARDING_SEEN: "tierx_onboarding_seen",
  SELECTED_TENANT: "tierx_selected_tenant",
} as const;

export const LEGACY_STORAGE_KEYS = {
  TOKEN: "soc_mind_token",
  ONBOARDING_SEEN: "soc_mind_onboarding_seen",
  SELECTED_TENANT: "soc_mind_selected_tenant",
} as const;

export function readCompatibleStorage(
  storage: Storage,
  canonical: string,
  legacy: string,
): string | null {
  // Both keys are mirrored on writes. A rollback can update only the old key.
  const value = storage.getItem(legacy) ?? storage.getItem(canonical);
  if (value !== null) {
    storage.setItem(canonical, value);
    storage.setItem(legacy, value);
  }
  return value;
}

export function writeCompatibleStorage(
  storage: Storage,
  canonical: string,
  legacy: string,
  value: string,
): void {
  storage.setItem(canonical, value);
  storage.setItem(legacy, value);
}

export function clearCompatibleStorage(
  storage: Storage,
  canonical: string,
  legacy: string,
): void {
  storage.removeItem(canonical);
  storage.removeItem(legacy);
}

export function readSelectedTenant(): string | null {
  if (typeof window === "undefined") return null;
  return readCompatibleStorage(
    localStorage,
    STORAGE_KEYS.SELECTED_TENANT,
    LEGACY_STORAGE_KEYS.SELECTED_TENANT,
  );
}

export function writeSelectedTenant(tenantId: string): void {
  if (typeof window === "undefined") return;
  writeCompatibleStorage(localStorage, STORAGE_KEYS.SELECTED_TENANT, LEGACY_STORAGE_KEYS.SELECTED_TENANT, tenantId);
}

export function clearSelectedTenant(): void {
  if (typeof window === "undefined") return;
  clearCompatibleStorage(localStorage, STORAGE_KEYS.SELECTED_TENANT, LEGACY_STORAGE_KEYS.SELECTED_TENANT);
}

export function hasSeenOnboarding(): boolean {
  if (typeof window === "undefined") return true;
  return readCompatibleStorage(localStorage, STORAGE_KEYS.ONBOARDING_SEEN, LEGACY_STORAGE_KEYS.ONBOARDING_SEEN) === "true";
}

export function markOnboardingSeen(): void {
  if (typeof window === "undefined") return;
  writeCompatibleStorage(localStorage, STORAGE_KEYS.ONBOARDING_SEEN, LEGACY_STORAGE_KEYS.ONBOARDING_SEEN, "true");
}
