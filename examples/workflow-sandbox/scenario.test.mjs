import test from "node:test";
import assert from "node:assert/strict";
import {
  scenarioFile,
  generationInput,
  checkSchema,
  validateSchema,
  replay,
  object,
} from "./scenario.mjs";
export const sample = {
  result: {
    host: "SYNTHETIC-01",
    src: "192.0.2.10",
    user: "synthetic.user",
    rule_id: "synthetic",
    _time: "2026-01-01T00:00:00Z",
  },
};
export const schema = {
  type: "object",
  required: ["result"],
  additionalProperties: false,
  properties: {
    result: {
      type: "object",
      required: ["host"],
      properties: { host: { type: "string", minLength: 1 } },
    },
  },
};
test("scenario validates limits, paths, schemas and credential exclusion", () => {
  const row = scenarioFile({ alerts: [sample], settings: { total: 1000 } });
  assert.equal(row.settings.total, 1000);
  for (const total of [0, 1001, 1.5])
    assert.throws(() =>
      scenarioFile({ alerts: [sample], settings: { total } }),
    );
  for (const duration_minutes of [0, 61])
    assert.throws(() =>
      scenarioFile({ alerts: [sample], settings: { duration_minutes } }),
    );
  for (const path of ["__proto__.x", "result.constructor.x", ""])
    assert.throws(() =>
      scenarioFile({ alerts: [sample], settings: { unique_paths: [path] } }),
    );
  assert.throws(() => object({ result: { password: "not-to-be-saved" } }));
  assert.throws(() => object({ message: "Bearer synthetic-secret-value" }));
  assert.throws(() => scenarioFile({ alerts: [{}], schema }));
  assert.throws(
    () => checkSchema({ $ref: "https://example.com/schema" }),
    /Unsupported/,
  );
  assert.throws(() => checkSchema({ pattern: "(a+)+$" }), /Unsupported/);
  checkSchema(schema);
  validateSchema(sample, schema);
  assert.throws(() => validateSchema({ result: { host: 42 } }, schema));
});
test("schema subset enforces alternatives, bounds and false schemas", () => {
  assert.throws(() => validateSchema("a", { type: "string", minLength: 2 }));
  assert.throws(() => validateSchema([1, 2], { type: "array", maxItems: 1 }));
  assert.throws(() => validateSchema(11, { type: "integer", maximum: 10 }));
  assert.throws(() => validateSchema(1, false));
  validateSchema("a", { oneOf: [{ type: "string" }, { type: "number" }] });
  assert.throws(() =>
    validateSchema("a", { oneOf: [{ type: "string" }, { const: "a" }] }),
  );
});
test("negative fixtures are explicit and replay never mutates originals", () => {
  assert.throws(
    () =>
      generationInput({
        sample,
        description: "Synthetic",
        preset: "validation-failure",
      }),
    /Confirm/,
  );
  assert.throws(
    () => scenarioFile({ alerts: [{}], preset: "validation-failure" }),
    /Confirm/,
  );
  const negative = scenarioFile({
    alerts: [{}],
    schema,
    preset: "validation-failure",
    negative: true,
  });
  assert.equal(negative.negative, true);
  const row = scenarioFile({ alerts: [sample], settings: { refresh: true } });
  const changed = replay(sample, row.settings, "one", "2030-01-01T00:00:00Z");
  assert.equal(changed.result.rule_id, "sandbox-one");
  assert.equal(sample.result.rule_id, "synthetic");
  assert.equal(
    scenarioFile({
      alerts: [sample],
      preset: "duplicates",
      settings: { refresh: true },
    }).settings.refresh,
    false,
  );
  const imported = scenarioFile({
    ...row,
    authorization: "not-exported",
    generation: {
      provider: "ollama",
      model: "synthetic",
      api_key: "not-exported",
    },
  });
  assert(!JSON.stringify(imported).includes("not-exported"));
});
