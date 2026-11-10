import test from "node:test";
import assert from "node:assert/strict";
import { ScenarioRunner } from "./runner.mjs";
import { scenarioFile } from "./scenario.mjs";
const sample = {
  result: { host: "SYNTHETIC", _time: "2026-01-01T00:00:00Z", rule_id: "same" },
};
const scenario = (settings = {}) =>
  scenarioFile({ alerts: [sample], settings: { ...settings } });
function harness(options = {}) {
  let time = 0,
    id = 0;
  const outcomes = [],
    times = [];
  const runner = new ScenarioRunner({
    uuid: () => "delivery-" + ++id,
    clock: () => time,
    sleep: async (ms) => {
      time += ms;
    },
    submit: async () => {
      times.push(time);
      return { alert_id: "a", run_id: "r" };
    },
    record: (row) => outcomes.push(row),
    ...options,
  });
  return { runner, outcomes, times };
}
test("serial sends respect interval, count limits and refreshed payloads", async () => {
  const { runner, outcomes, times } = harness();
  const result = await runner.start(scenario({ total: 3, refresh: true }));
  assert.equal(result.state, "COMPLETED");
  assert.equal(result.counts.accepted, 3);
  assert.deepEqual(times, [0, 5000, 10000]);
  assert.equal(outcomes[1].payload.result.rule_id, "sandbox-delivery-2");
  assert.equal(sample.result.rule_id, "same");
});
test("transient retries reuse delivery identity and stop after three retries", async () => {
  const ids = [];
  const { runner } = harness({
    submit: async (_payload, id) => {
      ids.push(id);
      throw Object.assign(new Error("temporarily unavailable"), {
        status: 503,
      });
    },
  });
  const result = await runner.start(scenario({ total: 1 }));
  assert.equal(ids.length, 4);
  assert.equal(new Set(ids).size, 1);
  assert.equal(result.counts.failed, 1);
});
test("routing/authentication errors stop; validation rejections continue", async () => {
  for (const status of [401, 403, 404, 410]) {
    const { runner } = harness({
      submit: async () => {
        throw Object.assign(new Error("Denied"), { status });
      },
    });
    const result = await runner.start(scenario({ total: 10 }));
    assert.equal(result.state, "FAILED");
    assert.equal(result.completed, 1);
  }
  const { runner } = harness({
    submit: async () => {
      throw Object.assign(new Error("Validation"), { status: 422 });
    },
  });
  const result = await runner.start(scenario({ total: 3 }));
  assert.equal(result.counts.rejected, 3);
  assert.equal(result.state, "COMPLETED");
});
test("fresh batches never overlap and malformed generation sends nothing", async () => {
  let generated = 0,
    active = 0,
    max = 0;
  const { runner } = harness({
    generate: async (count) => {
      active++;
      max = Math.max(max, active);
      await Promise.resolve();
      active--;
      generated++;
      return Array.from({ length: count }, () => sample);
    },
  });
  const result = await runner.start(scenario({ total: 12 }), {
    continuous: true,
  });
  assert.equal(generated, 3);
  assert.equal(max, 1);
  assert.equal(result.counts.generated, 12);
  assert.equal(result.counts.accepted, 12);
  const invalid = harness({ generate: async () => [null] });
  const failed = await invalid.runner.start(scenario(), { continuous: true });
  assert.equal(failed.state, "FAILED");
  assert.equal(invalid.times.length, 0);
});
test("pause aborts in-flight submit; resume reuses pending delivery; stop does not recall accepted work", async () => {
  let started;
  const ready = new Promise((resolve) => (started = resolve)),
    ids = [];
  const { runner } = harness({
    submit: async (_payload, id, signal) => {
      ids.push(id);
      if (ids.length === 1) {
        started();
        await new Promise((_resolve, reject) =>
          signal.addEventListener("abort", () => reject(new Error("aborted"))),
        );
      }
      return { alert_id: "a", run_id: "r" };
    },
  });
  const done = runner.start(scenario({ total: 1 }));
  await ready;
  runner.pause();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(runner.state, "PAUSED");
  assert.equal(ids.length, 1);
  runner.resume();
  const result = await done;
  assert.deepEqual(ids, ["delivery-1", "delivery-1"]);
  assert.equal(result.counts.accepted, 1);
});
test("stop aborts generation and duration bounds prevent more sends", async () => {
  let began;
  const ready = new Promise((resolve) => (began = resolve));
  const { runner, times } = harness({
    generate: async (_count, signal) => {
      began();
      await new Promise((_resolve, reject) =>
        signal.addEventListener("abort", () => reject(new Error("aborted"))),
      );
    },
  });
  const done = runner.start(scenario(), { continuous: true });
  await ready;
  runner.stop();
  assert.equal((await done).state, "STOPPED");
  assert.equal(times.length, 0);
  const limited = harness();
  const result = await limited.runner.start(
    scenario({ total: 1000, duration_minutes: 0.01 }),
  );
  assert.equal(result.state, "TIMED_OUT");
  assert.equal(result.counts.accepted, 1);
});
test("duplicate replay stays identical and intentional missing fields stay missing after refresh", async () => {
  const duplicate = scenarioFile({
      alerts: [sample],
      preset: "duplicates",
      settings: { total: 2, refresh: true },
    }),
    h = harness();
  await h.runner.start(duplicate);
  assert.deepEqual(h.outcomes[0].payload, h.outcomes[1].payload);
  const negative = scenarioFile({
      alerts: [sample],
      preset: "validation-failure",
      negative: true,
      missing_path: "result.rule_id",
      settings: { total: 1, refresh: true },
    }),
    n = harness();
  await n.runner.start(negative);
  assert(!("rule_id" in n.outcomes[0].payload.result));
});
