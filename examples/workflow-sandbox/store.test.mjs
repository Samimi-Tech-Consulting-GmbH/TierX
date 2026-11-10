import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, rm, stat, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { once } from "node:events";
import { createSandbox } from "./server.mjs";
import { scenarioStore } from "./store.mjs";
const sample = { result: { host: "SYNTHETIC-01" } };
test("AI settings override environment defaults without returning or inheriting keys", async () => {
  const server = createSandbox("https://tierx.example", fetch, undefined, {
    ai: {
      provider: "ollama",
      url: "http://127.0.0.1:11434",
      model: "env-model",
      apiKey: "environment-secret",
    },
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  const origin = `http://127.0.0.1:${server.address().port}`;
  const update = (body) =>
    fetch(origin + "/ai/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  try {
    const initial = await (await fetch(origin + "/ai/settings")).json();
    assert.equal(initial.source, "environment");
    assert.equal(initial.has_key, true);
    assert(!JSON.stringify(initial).includes("environment-secret"));
    const changed = await (
      await update({
        provider: "openai-compatible",
        url: "https://ai.example/v1",
        model: "override-model",
        api_key: "override-secret",
      })
    ).json();
    assert.equal(changed.source, "override");
    assert.equal(changed.has_key, true);
    assert(!JSON.stringify(changed).includes("override-secret"));
    const noKey = await (
      await update({
        provider: "ollama",
        url: "http://localhost:11434",
        model: "local",
      })
    ).json();
    assert.equal(noKey.has_key, false);
    assert.equal(
      (
        await update({
          provider: "ollama",
          url: "http://remote.example",
          model: "m",
        })
      ).status,
      400,
    );
    const reset = await (await update({ use_environment: true })).json();
    assert.equal(reset.model, "env-model");
    assert.equal(reset.source, "environment");
    assert.equal(
      (
        await fetch(origin + "/ai/settings", {
          method: "POST",
          headers: { Origin: "https://foreign.example" },
          body: "{}",
        })
      ).status,
      403,
    );
  } finally {
    server.closeAllConnections();
    await new Promise((resolve) => server.close(resolve));
  }
});
test("UI target selection only routes to configured origins", async () => {
  const calls = [];
  const server = createSandbox(
    "http://127.0.0.1:18084",
    async (url, options) => {
      calls.push({ url: String(url), headers: options.headers });
      return new Response("{}", { status: 200 });
    },
    undefined,
    {
      ai: { provider: "disabled" },
      targets: [{ label: "Testing", target: "https://testing.example.com" }],
    },
  );
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  const origin = `http://127.0.0.1:${server.address().port}`;
  try {
    const config = await (await fetch(origin + "/config")).json();
    assert.equal(config.targets.length, 2);
    const selected = await fetch(origin + "/proxy/api/v1/auth/me", {
      headers: {
        "X-Sandbox-Target": "https://testing.example.com",
        Authorization: "Bearer observer",
      },
    });
    assert.equal(selected.status, 200);
    assert.equal(calls[0].url, "https://testing.example.com/api/v1/auth/me");
    assert.equal(calls[0].headers["X-Sandbox-Target"], undefined);
    assert.equal(
      (
        await fetch(origin + "/proxy/api/v1/auth/me", {
          headers: { "X-Sandbox-Target": "https://unapproved.example.com" },
        })
      ).status,
      400,
    );
    assert.equal(calls.length, 1);
    assert.throws(() =>
      createSandbox("https://example.com", fetch, undefined, {
        targets: [{ target: "https://user:secret@testing.example.com" }],
      }),
    );
  } finally {
    server.closeAllConnections();
    await new Promise((resolve) => server.close(resolve));
  }
});
test("local scenarios/outcomes survive reload, export without credentials and restrict permissions", async () => {
  const directory = await mkdtemp(join(tmpdir(), "tierx-scenarios-"));
  try {
    const store = scenarioStore(directory),
      saved = await store.save({
        alerts: [sample],
        generation: {
          provider: "ollama",
          model: "synthetic",
          api_key: "not-saved",
        },
        token: "not-saved",
      });
    await store.outcome(saved.id, {
      delivery_id: "one",
      state: "ACCEPTED",
      alert_id: "a",
      run_id: "r",
      payload: sample,
      authorization: "not-saved",
      headers: { Authorization: "not-saved" },
    });
    const fresh = scenarioStore(directory),
      exported = await fresh.export(saved.id);
    assert.deepEqual(exported.alerts, [sample]);
    assert.equal(exported.outcomes[0].run_id, "r");
    assert(!JSON.stringify(exported).includes("not-saved"));
    assert.equal((await fresh.list()).length, 1);
    assert.equal(
      (await stat(join(directory, saved.id + ".json"))).mode & 0o777,
      0o600,
    );
    await assert.rejects(fresh.read("../../credentials"));
    await assert.rejects(store.save({ alerts: [{ password: "not-saved" }] }));
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});
test("generation and archive routes enforce local origin and never reveal provider configuration secrets", async () => {
  const directory = await mkdtemp(join(tmpdir(), "tierx-sandbox-api-"));
  const server = createSandbox("https://example.com", fetch, undefined, {
    dataDir: directory,
    ai: {
      provider: "ollama",
      url: "https://provider.example",
      model: "synthetic",
      apiKey: "secret-provider-key",
    },
    generationFetch: async () =>
      new Response(
        JSON.stringify({
          message: { content: JSON.stringify({ alerts: [sample] }) },
        }),
      ),
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  const origin = `http://127.0.0.1:${server.address().port}`;
  const post = (path, body, headers = {}) =>
    fetch(origin + path, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...headers },
      body: JSON.stringify(body),
    });
  try {
    const config = await (await fetch(origin + "/config")).text();
    assert(!config.includes("secret-provider-key"));
    assert(!config.includes("provider.example"));
    assert.equal(
      (
        await post(
          "/ai/generate",
          { sample, description: "Synthetic", count: 1 },
          { Origin: "https://foreign.example" },
        )
      ).status,
      403,
    );
    assert.equal(
      (
        await post("/ai/generate", {
          sample,
          description: "Synthetic",
          count: 1,
        })
      ).status,
      200,
    );
    const saved = await (await post("/scenarios", { alerts: [sample] })).json();
    assert.equal(
      (
        await post(`/scenarios/${saved.id}/outcomes`, {
          payload: sample,
          state: "ACCEPTED",
          delivery_id: "one",
        })
      ).status,
      200,
    );
    const exported = await (
      await fetch(`${origin}/scenarios/${saved.id}/export`)
    ).json();
    assert.equal(exported.outcomes.length, 1);
    assert.equal(
      (await fetch(origin + "/.sandbox-data/" + saved.id + ".json")).status,
      404,
    );
    assert.equal((await fetch(origin + "/generator.mjs")).status, 404);
    assert.equal((await fetch(origin + "/runner.mjs")).status, 200);
    assert(
      !String(
        await readFile(join(directory, saved.id + ".outcomes.jsonl")),
      ).includes("secret-provider-key"),
    );
  } finally {
    server.closeAllConnections();
    await new Promise((resolve) => server.close(resolve));
    await rm(directory, { recursive: true, force: true });
  }
});
