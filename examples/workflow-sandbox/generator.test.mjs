import test from "node:test";
import assert from "node:assert/strict";
import { aiConfiguration, createGenerator } from "./generator.mjs";
const sample = {
  result: { host: "SYNTHETIC-01", src: "192.0.2.10", user: "synthetic.user" },
};
const input = { sample, description: "Synthetic related endpoints", count: 2 };
const response = (provider, alerts) =>
  new Response(
    JSON.stringify(
      provider === "ollama"
        ? { message: { content: JSON.stringify({ alerts }) } }
        : { choices: [{ message: { content: JSON.stringify({ alerts }) } }] },
    ),
  );
test("provider credentials echoed in output are rejected", async () => {
  const generate = createGenerator(
    {
      provider: "ollama",
      url: "https://ai.example",
      model: "m",
      apiKey: "private-provider-key",
    },
    async () =>
      response("ollama", [{ result: { host: "private-provider-key" } }]),
  );
  await assert.rejects(
    generate({ ...input, count: 1 }),
    /provider credentials/,
  );
});
for (const provider of ["ollama", "openai-compatible"])
  test(`${provider} uses structured requests with no TierX routing or credentials`, async () => {
    let call;
    const generate = createGenerator(
      {
        provider,
        url: "https://ai.example/v1",
        model: "explicit-model",
        apiKey: "provider-only",
      },
      async (url, options) => {
        call = { url, options };
        return response(provider, [sample, sample]);
      },
    );
    const result = await generate({
      ...input,
      tenant_id: "never-send",
      token: "tierx-secret",
      url: "https://tierx.invalid",
    });
    assert.equal(result.alerts.length, 2);
    assert.equal(call.options.headers.Authorization, "Bearer provider-only");
    assert(!call.options.body.includes("tierx-secret"));
    assert(!call.options.body.includes("never-send"));
    assert(!call.options.body.includes("tierx.invalid"));
    assert(!JSON.stringify(result).includes("provider-only"));
    assert.equal(call.options.redirect, "manual");
    assert.equal(
      call.url,
      "https://ai.example/v1" +
        (provider === "ollama" ? "/api/chat" : "/chat/completions"),
    );
  });
test("provider configuration is explicit and fails closed", async () => {
  assert.equal(aiConfiguration({}).provider, "disabled");
  for (const env of [
    { SANDBOX_AI_PROVIDER: "unknown" },
    { SANDBOX_AI_PROVIDER: "ollama" },
    {
      SANDBOX_AI_PROVIDER: "ollama",
      SANDBOX_AI_URL: "http://remote.example",
      SANDBOX_AI_MODEL: "m",
    },
  ])
    assert.throws(() => aiConfiguration(env));
  assert.equal(
    aiConfiguration({
      SANDBOX_AI_PROVIDER: "ollama",
      SANDBOX_AI_URL: "http://127.0.0.1:11434",
      SANDBOX_AI_MODEL: "m",
    }).model,
    "m",
  );
  await assert.rejects(
    createGenerator({ provider: "disabled" })(input),
    /disabled/,
  );
});
test("malformed, wrong count, schema-invalid, failed and oversized AI outputs are never accepted", async () => {
  const config = {
    provider: "ollama",
    url: "http://localhost:11434",
    model: "m",
  };
  for (const make of [
    () => new Response("invalid"),
    () => response("ollama", [sample]),
    () => new Response("provider secret body", { status: 500 }),
    () => new Response("x".repeat(2 * 1024 * 1024 + 1)),
  ])
    await assert.rejects(createGenerator(config, async () => make())(input));
  await assert.rejects(
    createGenerator(config, async () => response("ollama", [sample, sample]))({
      ...input,
      schema: { type: "object", required: ["required"] },
      sample: { required: true },
    }),
    /required/,
  );
});
test("presets are deterministic, negative generation requires consent", async () => {
  const generator = createGenerator(
    { provider: "ollama", url: "http://localhost", model: "m" },
    async () =>
      response("ollama", [
        { result: { host: "OTHER" } },
        { result: { host: "DIFFERENT" } },
      ]),
  );
  const correlated = await generator({ ...input, preset: "correlated" });
  assert.equal(correlated.alerts[1].result.host, sample.result.host);
  const duplicates = await generator({ ...input, preset: "duplicates" });
  assert.deepEqual(duplicates.alerts[0], duplicates.alerts[1]);
  const negative = await generator({
    ...input,
    preset: "validation-failure",
    negative: true,
    missing_path: "result.host",
  });
  assert(!("host" in negative.alerts[0].result));
});
test("one generation at a time, cancellation, timeouts and unavailable providers", async () => {
  const config = {
    provider: "ollama",
    url: "http://localhost",
    model: "m",
    timeout: 15,
  };
  const generator = createGenerator(
    config,
    async (_url, { signal }) =>
      new Promise((_resolve, reject) => {
        signal.addEventListener("abort", () =>
          reject(new DOMException("Aborted", "AbortError")),
        );
      }),
  );
  const pending = generator(input);
  await assert.rejects(generator(input), /in progress/);
  await assert.rejects(pending, /120 seconds/);
  const controller = new AbortController();
  const cancelled = generator(input, controller.signal);
  controller.abort();
  await assert.rejects(cancelled, /cancelled/);
  await assert.rejects(
    createGenerator(config, async () => {
      throw new TypeError("connect failed");
    })(input),
    /unavailable/,
  );
});
