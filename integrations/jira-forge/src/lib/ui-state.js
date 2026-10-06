export const TERMINAL_UI_STATES = new Set([
  "PROCESSING", "CLUSTERED", "ANALYZED", "FAILED", "CANCELLED",
]);

export async function cleanupPreviousDestination(egress, previousKey, nextKey) {
  if (!previousKey || previousKey === nextKey) return null;
  try {
    await egress.deleteGroup({ key: previousKey });
    return null;
  } catch {
    return "The new connection is saved, but its previous destination remains authorized. Remove the old TierX permission in Connected Apps.";
  }
}
