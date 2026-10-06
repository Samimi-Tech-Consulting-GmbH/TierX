import { randomUUID } from "node:crypto";
export const CONNECTION_KEY = "tierx:connection:v1";
export const CONNECTION_MUTATION_KEY = "tierx:connection-mutation:v1";
export class ConnectionChangedError extends Error {
  constructor() { super("TierX connection changed or was disconnected. Submit the issue again."); this.name = "ConnectionChangedError"; }
}
export function publicConnection(record) {
  if (!record) return { baseUrl: "", configured: false };
  const { secret, ...safe } = record;
  return { ...safe, configured: Boolean(secret) };
}
export function createConnectionStore(storage, verify) {
  async function serializeMutation(operation) {
    try {
      await storage.setSecret(CONNECTION_MUTATION_KEY, { owner: randomUUID() }, { keyPolicy: "FAIL_IF_EXISTS" });
    } catch {
      throw new Error("Another connection change is active. Retry shortly; contact the operator if it persists.");
    }
    try { return await operation(); }
    finally { await storage.deleteSecret(CONNECTION_MUTATION_KEY); }
  }
  return {
    async read(identity) {
      const record = await storage.getSecret(CONNECTION_KEY);
      if (!record?.secret || (identity !== undefined && record.identity !== identity)) throw new ConnectionChangedError();
      return record;
    },
    async public() { return publicConnection(await storage.getSecret(CONNECTION_KEY)); },
    async save(candidate, cloudId) {
      const previous = await storage.getSecret(CONNECTION_KEY);
      const info = await verify(candidate);
      if (info.jira_cloud_id !== cloudId) throw new Error("The TierX credential is bound to a different Jira site.");
      return serializeMutation(async () => {
      // One encrypted atomic value prevents concurrent saves mixing URLs and secrets.
      const current = await storage.getSecret(CONNECTION_KEY);
      if (current?.revision !== previous?.revision) throw new ConnectionChangedError();
      const same = previous?.baseUrl === candidate.baseUrl && previous?.integrationId === candidate.integrationId;
      const record = {
        ...candidate, identity: same ? previous.identity : randomUUID(),
        revision: randomUUID(), connectionName: info.name,
        routeCount: info.route_count, jiraCloudId: info.jira_cloud_id,
        updatedAt: new Date().toISOString(),
      };
      await storage.setSecret(CONNECTION_KEY, record);
      return publicConnection(record);
      });
    },
    async disconnect() {
      return serializeMutation(async () => {
      // A non-secret tombstone invalidates in-progress first-time pairing too.
      await storage.setSecret(CONNECTION_KEY, { revision: randomUUID(), baseUrl: "" });
      await storage.deleteSecret("soc-mind:integration-secret");
      await storage.delete("soc-mind:config");
      return { configured: false, baseUrl: "" };
      });
    },
  };
}
