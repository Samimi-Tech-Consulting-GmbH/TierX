import {
  mkdir,
  writeFile,
  readFile,
  readdir,
  appendFile,
  stat,
} from "node:fs/promises";
import { join } from "node:path";
import { randomUUID } from "node:crypto";
import { scenarioFile, object } from "./scenario.mjs";

export function scenarioStore(directory) {
  const path = (id, suffix = ".json") => {
    if (!/^[a-f0-9-]{36}$/.test(id))
      throw new Error("Invalid scenario identity.");
    return join(directory, id + suffix);
  };
  const ready = () => mkdir(directory, { recursive: true, mode: 0o700 });
  let writing = Promise.resolve();
  return {
    async save(input) {
      const scenario = scenarioFile(input),
        id = randomUUID();
      await ready();
      await writeFile(path(id), JSON.stringify(scenario, null, 2), {
        mode: 0o600,
        flag: "wx",
      });
      return { id, scenario };
    },
    async list() {
      await ready();
      const names = (await readdir(directory))
        .filter((name) => /^[a-f0-9-]{36}\.json$/.test(name))
        .sort();
      return Promise.all(
        names.map(async (name) => {
          const row = JSON.parse(await readFile(join(directory, name), "utf8"));
          return {
            id: name.slice(0, -5),
            name: row.name,
            count: row.alerts.length,
            generation: row.generation,
          };
        }),
      );
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
      return {
        ...scenario,
        outcomes: content.trim()
          ? content
              .trim()
              .split("\n")
              .map((line) => JSON.parse(line))
          : [],
      };
    },
  };
}
