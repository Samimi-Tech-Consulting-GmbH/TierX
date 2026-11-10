import { generationInput, scenarioFile } from "./scenario.mjs";
import { ScenarioRunner } from "./runner.mjs";
const $ = (id) => document.getElementById(id);
let metadata = null,
  archive = null,
  config = null,
  generating = null,
  submitter = null;
const status = (message) => {
  $("scenario-message").textContent = message;
};
document.addEventListener("sandbox-target-change", () => {
  if (config) config.target = globalThis.sandbox.target();
});
async function local(path, body, signal) {
  const response = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  });
  const value = await response.json();
  if (!response.ok) throw new Error(value.detail || "Local request failed.");
  return value;
}
const paths = (id) =>
  $(id)
    .value.split(",")
    .map((value) => value.trim())
    .filter(Boolean);
function input(count = Number($("generation-count").value)) {
  return generationInput({
    sample: JSON.parse($("payload").value),
    description: $("scenario-description").value,
    count,
    preset: $("preset").value,
    negative: $("negative").checked,
    missing_path: $("missing-path").value,
    schema: $("alert-schema").value.trim()
      ? JSON.parse($("alert-schema").value)
      : null,
  });
}
function scenario() {
  return scenarioFile({
    name: $("scenario-name").value,
    description: $("scenario-description").value,
    preset: $("preset").value,
    negative: $("negative").checked,
    missing_path: $("missing-path").value,
    schema: $("alert-schema").value.trim()
      ? JSON.parse($("alert-schema").value)
      : null,
    alerts: JSON.parse($("batch").value || "[]"),
    generation: metadata,
    settings: {
      total: Number($("run-total").value),
      interval_seconds: Number($("run-interval").value),
      duration_minutes: Number($("run-duration").value),
      refresh: $("refresh-fields").checked,
      timestamp_paths: paths("timestamp-paths"),
      unique_paths: paths("unique-paths"),
    },
  });
}
async function save(value) {
  const saved = await local("/scenarios", value);
  archive = saved.id;
  return saved;
}
async function generate(count, signal) {
  const result = await local("/ai/generate", input(count), signal);
  metadata = result.generation;
  $("batch").value = JSON.stringify(result.alerts, null, 2);
  $("validation").textContent = result.generation.validation;
  return result.alerts;
}
function busy(active) {
  for (const id of [
    "generate",
    "send-batch",
    "start-loop",
    "load-scenario",
    "import-scenario",
    "send",
    "duplicate",
    "path",
    "entry-token",
    "payload",
  ])
    $(id).disabled = active || (id === "generate" && !config?.ai?.enabled);
  for (const element of document.querySelectorAll("[data-run-config]"))
    element.disabled = active;
}
const runner = new ScenarioRunner({
  submit: (payload, id, signal) => submitter(payload, id, signal),
  generate: (count, signal) => generate(count, signal),
  record: (row) => local(`/scenarios/${archive}/outcomes`, row),
  changed(snapshot) {
    const active = ["RUNNING", "PAUSED"].includes(snapshot.state);
    busy(active || !!generating);
    $("pause-run").disabled = snapshot.state !== "RUNNING";
    $("resume-run").disabled = snapshot.state !== "PAUSED";
    $("stop-run").disabled = !active && !generating;
    $("run-state").textContent = snapshot.state;
    $("run-counts").textContent = Object.entries(snapshot.counts)
      .map(([key, value]) => `${key}: ${value}`)
      .join(" · ");
    if (snapshot.error) status(snapshot.error);
  },
});
async function refreshSaved() {
  const result = await local("/scenarios");
  const select = $("saved-scenarios");
  select.replaceChildren(
    new Option("Choose saved scenario", ""),
    ...result.items.map(
      (item) =>
        new Option(`${item.name} (${item.count} initial alerts)`, item.id),
    ),
  );
}
$("generate").onclick = async () => {
  try {
    if (generating) return;
    const request = input();
    if (
      !confirm(
        `Generate ${request.count} synthetic alerts using ${config?.ai?.provider}/${config?.ai?.model}? Only the sample, scenario description and schema are sent to that provider. Do not include real customer data.`,
      )
    )
      return;
    generating = new AbortController();
    busy(true);
    $("stop-run").disabled = false;
    status("Generating synthetic alerts…");
    await generate(request.count, generating.signal);
    await save(scenario());
    await refreshSaved();
    status("Batch validated and saved locally. Review/edit before sending.");
  } catch (error) {
    status(error.message);
  } finally {
    generating = null;
    busy(false);
    $("stop-run").disabled = true;
  }
};
async function start(once) {
  try {
    if (["RUNNING", "PAUSED"].includes(runner.state) || generating) return;
    let value = scenario();
    const continuous = !once && $("run-mode").value === "continuous";
    if (continuous && !config?.ai?.enabled)
      throw new Error(
        "Configure the local AI provider before continuous generation.",
      );
    const count = once ? value.alerts.length : value.settings.total,
      path = $("path").value.trim();
    if (
      !/^\/api\/v2\/workflows\/[a-z0-9][a-z0-9_-]{0,63}\/tenants\/[a-zA-Z0-9_-]+\/ingest$/.test(
        path,
      )
    )
      throw new Error("Set a fixed workflow ingestion path first.");
    if (
      !confirm(
        `Target: ${config.target}\nWorkflow: ${path}\nMode: ${continuous ? "Fresh AI generation" : "Saved batch replay"}\nAlerts: ${count}\nInterval: ${value.settings.interval_seconds}s\nMaximum: ${value.settings.duration_minutes} minutes (including pauses)\n${value.negative ? "INTENTIONAL VALIDATION FAILURES" : "Synthetic test data only"}\nStart this non-production test?`,
      )
    )
      return;
    submitter = globalThis.sandbox.bindSubmission();
    if (continuous)
      value = {
        ...value,
        generation: {
          provider: config.ai.provider,
          model: config.ai.model,
          generated_at: new Date().toISOString(),
        },
      };
    busy(true);
    await save(value);
    await refreshSaved();
    status("Run started. Accepted alerts process independently.");
    await runner.start(value, { continuous, once });
    if (!runner.error)
      status(
        `Run ${runner.state.toLowerCase()}. Stop never recalls accepted alerts.`,
      );
  } catch (error) {
    status(error.message);
  } finally {
    submitter = null;
    busy(false);
  }
}
$("send-batch").onclick = () => start(true);
$("start-loop").onclick = () => start(false);
$("pause-run").onclick = () => runner.pause();
$("resume-run").onclick = () => runner.resume();
$("stop-run").onclick = () => {
  generating?.abort();
  runner.stop();
  status(
    "Stopped locally. Already accepted alerts continue; an interrupted request may have been accepted—check its delivery ID in the archive.",
  );
};
document.addEventListener("sandbox-disconnect", () => {
  generating?.abort();
  runner.stop();
});
function load(value) {
  const original = value;
  if (value.outcomes?.length)
    value = { ...value, alerts: value.outcomes.map((row) => row.payload) };
  const row = scenarioFile(value);
  $("scenario-name").value = row.name;
  $("scenario-description").value = row.description;
  $("preset").value = row.preset;
  $("negative").checked = row.negative;
  $("missing-path").value = row.missing_path;
  $("alert-schema").value =
    row.schema === null ? "" : JSON.stringify(row.schema, null, 2);
  $("batch").value = JSON.stringify(row.alerts, null, 2);
  $("payload").value = JSON.stringify(original.alerts[0], null, 2);
  metadata = row.generation;
  $("run-total").value = row.settings.total;
  $("run-interval").value = row.settings.interval_seconds;
  $("run-duration").value = row.settings.duration_minutes;
  $("refresh-fields").checked = row.settings.refresh;
  $("timestamp-paths").value = row.settings.timestamp_paths.join(", ");
  $("unique-paths").value = row.settings.unique_paths.join(", ");
  $("validation").textContent =
    row.schema === null
      ? "STRUCTURAL_ONLY"
      : row.negative
        ? "INTENTIONAL_NEGATIVE"
        : "SCHEMA_VALIDATED";
}
$("load-scenario").onclick = async () => {
  try {
    const id = $("saved-scenarios").value;
    if (!id) return;
    load(await local(`/scenarios/${id}/export`));
    archive = id;
    status("Saved scenario loaded. No AI is needed for replay.");
  } catch (error) {
    status(error.message);
  }
};
$("import-scenario").onchange = async (event) => {
  try {
    const file = event.target.files[0];
    if (!file) return;
    if (file.size > 10 * 1024 * 1024) throw new Error("Import exceeds 10 MiB.");
    load(JSON.parse(await file.text()));
    await save(scenario());
    await refreshSaved();
    status("Imported scenario validated and saved locally.");
  } catch (error) {
    status(error.message);
  } finally {
    event.target.value = "";
  }
};
$("export-scenario").onclick = async () => {
  try {
    const value = archive
      ? await local(`/scenarios/${archive}/export`)
      : scenario();
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = "tierx-synthetic-scenario.json";
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) {
    status(error.message);
  }
};
$("preset").onchange = () => {
  if ($("preset").value === "duplicates") $("refresh-fields").checked = false;
};
async function refreshAI() {
  const value = await local("/config");
  config = { ...value, target: globalThis.sandbox.target() || value.target };
  $("ai-provider").textContent = value.ai.enabled
    ? `AI: ${value.ai.provider} · ${value.ai.model}`
    : "AI disabled. Choose an AI provider in AI settings; manual sending and replay remain available.";
  busy(["RUNNING", "PAUSED"].includes(runner.state) || !!generating);
  const settings = await local("/ai/settings");
  $("settings-provider").value = settings.provider;
  $("settings-url").value = settings.url;
  $("settings-model").value = settings.model;
  $("settings-key").value = "";
  $("settings-status").textContent =
    `Using ${settings.source} settings. API key ${settings.has_key ? "configured on server (never returned)" : "not configured"}.`;
}
async function changeAI(useEnvironment) {
  try {
    if (["RUNNING", "PAUSED"].includes(runner.state) || generating)
      throw new Error(
        "Stop the current run or generation before changing AI settings.",
      );
    if (
      !confirm(
        useEnvironment
          ? "Remove the override and use server environment defaults?"
          : `Use ${$("settings-provider").value} at ${$("settings-url").value || "(disabled)"}? Synthetic scenario content will be sent to this provider.`,
      )
    )
      return;
    await local(
      "/ai/settings",
      useEnvironment
        ? { use_environment: true }
        : {
            provider: $("settings-provider").value,
            url: $("settings-url").value.trim(),
            model: $("settings-model").value.trim(),
            api_key: $("settings-key").value,
          },
    );
    await refreshAI();
  } catch (error) {
    $("settings-status").textContent = error.message;
  } finally {
    $("settings-key").value = "";
  }
}
$("ai-settings-form").onsubmit = (event) => {
  event.preventDefault();
  changeAI(false);
};
$("settings-reset").onclick = () => changeAI(true);
Promise.all([local("/config"), refreshSaved()])
  .then(([value]) => {
    config = value;
    refreshAI().catch((error) => status(error.message));
    $("generate").disabled = !value.ai.enabled;
    $("batch").value = JSON.stringify(
      [JSON.parse($("payload").value)],
      null,
      2,
    );
  })
  .catch((error) => status(error.message));
