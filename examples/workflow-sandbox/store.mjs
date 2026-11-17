import {
  mkdir,
  writeFile,
  readFile,
  readdir,
  appendFile,
  stat,
  chmod,
} from "node:fs/promises";
import { join } from "node:path";
import { randomUUID } from "node:crypto";
import { scenarioFile, object } from "./scenario.mjs";

export function scenarioStore(directory, { maxFiles = 1000, maxBytes = 100 * 1024 * 1024 } = {}) {
  const path = (id, suffix = ".json") => {
    if (!/^[a-f0-9-]{36}$/.test(id))
      throw new Error("Invalid scenario identity.");
    return join(directory, id + suffix);
  };
  const ready = async () => {
    await mkdir(directory, { recursive: true, mode: 0o700 });
    await chmod(directory, 0o700);
  };
  const inventory = async () => {
    const names = (await readdir(directory)).filter((name) => /^[a-f0-9-]{36}(\.json|\.outcomes\.jsonl)$/.test(name));
    const sizes = await Promise.all(names.map((name) => stat(join(directory, name))));
    return { count: names.filter((name) => name.endsWith(".json")).length, bytes: sizes.reduce((sum, item) => sum + item.size, 0) };
  };
  let writing = Promise.resolve();
  return {
    async save(input) {
      const scenario = { ...scenarioFile(input), created_at: new Date().toISOString() },
        id = randomUUID();
      const work = writing.then(async () => {
        await ready();
        const stored = await inventory();
        const content = JSON.stringify(scenario, null, 2);
        if (stored.count >= maxFiles || stored.bytes + Buffer.byteLength(content) > maxBytes)
          throw new Error("Scenario archive capacity reached; export and remove old local archives before continuing.");
        await writeFile(path(id), content, { mode: 0o600, flag: "wx" });
      });
      writing = work.catch(() => {});
      await work;
      return { id, scenario };
    },
    async list() {
      await ready();
      const names = (await readdir(directory))
        .filter((name) => /^[a-f0-9-]{36}\.json$/.test(name))
        .sort();
      const rows = await Promise.all(
        names.map(async (name) => {
          try {
          const row = JSON.parse(await readFile(join(directory, name), "utf8"));
          if (!Array.isArray(row.alerts)) return null;
          return {
            id: name.slice(0, -5),
            name: row.name,
            count: row.alerts.length,
            generation: row.generation,
            created_at: row.created_at || (await stat(join(directory, name))).mtime.toISOString(),
          };
          } catch { return null; }
        }),
      );
      return rows.filter(Boolean).sort((a, b) => b.created_at.localeCompare(a.created_at) || a.id.localeCompare(b.id));
    },
    async read(id) {
      return JSON.parse(await readFile(path(id), "utf8"));
    },
    async outcome(id, input) {
      const row = {
        delivery_id: String(input.delivery_id || "").slice(0, 64),
        state: input.state,
        status: Number(input.status) || 0,
        attempts: Number(input.attempts) || 0,
        timestamp: String(input.timestamp || "").slice(0, 64),
        ...(input.alert_id
          ? { alert_id: String(input.alert_id).slice(0, 128) }
          : {}),
        ...(input.run_id ? { run_id: String(input.run_id).slice(0, 128) } : {}),
        payload: object(input.payload),
      };
      if (!["ACCEPTED", "REJECTED", "FAILED", "UNKNOWN"].includes(row.state))
        throw new Error("Invalid outcome.");
      // Serialize append/limit checks, and never copy request headers or arbitrary metadata.
      const work = writing.then(async () => {
        await readFile(path(id));
        const destination = path(id, ".outcomes.jsonl"),
          line = JSON.stringify(row) + "\n";
        let size = 0;
        try {
          size = (await stat(destination)).size;
        } catch (error) {
          if (error.code !== "ENOENT") throw error;
        }
        if (size + Buffer.byteLength(line) > 10 * 1024 * 1024)
          throw new Error(
            "Scenario archive reached 10 MiB; export and start a new scenario.",
          );
        if ((await inventory()).bytes + Buffer.byteLength(line) > maxBytes)
          throw new Error("Scenario archive capacity reached; export and remove old local archives before continuing.");
        await appendFile(destination, line, { mode: 0o600 });
      });
      writing = work.catch(() => {});
      await work;
      return { saved: true };
    },
    async export(id) {
      await writing;
      const scenario = JSON.parse(await readFile(path(id), "utf8"));
      let content = "";
      try {
        content = await readFile(path(id, ".outcomes.jsonl"), "utf8");
      } catch (error) {
        if (error.code !== "ENOENT") throw error;
      }
      const lines = content.trim() ? content.trim().split("\n") : [];
      const outcomes = [];
      for (const [index, line] of lines.entries()) {
        try { outcomes.push(JSON.parse(line)); }
        catch (error) {
          if (index !== lines.length - 1 || content.endsWith("\n")) throw error;
          // A crash can interrupt the last append; keep preceding complete records.
        }
      }
      return {
        ...scenario,
        outcomes,
      };
    },
  };
}
