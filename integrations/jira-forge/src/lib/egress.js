export async function approveDestination(egress, destination) {
  const hasApproval = response => response.results?.some(group =>
    group.key === destination.egressKey &&
    group.configured?.some(entry => entry.domain === destination.baseUrl &&
      entry.type?.includes("FETCH_BACKEND_SIDE")));
  if (hasApproval(await egress.get({ keys: [destination.egressKey] }))) return;
  await egress.set({ egresses: [{
    key: destination.egressKey,
    description: "Send selected security alerts to your TierX server",
    configured: [{ domain: destination.baseUrl, type: ["FETCH_BACKEND_SIDE"] }],
  }] });
  if (!hasApproval(await egress.get({ keys: [destination.egressKey] }))) {
    throw new Error("Outbound permission was not granted for this TierX server.");
  }
}
