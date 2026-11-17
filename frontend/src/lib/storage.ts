export const STORAGE_KEYS = {
  TOKEN: "tierx_token",
  ONBOARDING_SEEN: "tierx_onboarding_seen",
  SELECTED_TENANT: "tierx_selected_tenant",
} as const;

export function readSelectedTenant(): string | null {
  return typeof window === "undefined"
    ? null
    : localStorage.getItem(STORAGE_KEYS.SELECTED_TENANT);
}
export function writeSelectedTenant(tenantId: string): void {
  if (typeof window !== "undefined")
    localStorage.setItem(STORAGE_KEYS.SELECTED_TENANT, tenantId);
}
export function clearSelectedTenant(): void {
  if (typeof window !== "undefined")
    localStorage.removeItem(STORAGE_KEYS.SELECTED_TENANT);
}
export function hasSeenOnboarding(): boolean {
  return (
    typeof window === "undefined" ||
    localStorage.getItem(STORAGE_KEYS.ONBOARDING_SEEN) === "true"
  );
}
export function markOnboardingSeen(): void {
  if (typeof window !== "undefined")
    localStorage.setItem(STORAGE_KEYS.ONBOARDING_SEEN, "true");
}
