// Fresh disposable localhost stack only. Synthetic data; no credentials printed.
import assert from "node:assert/strict";
import { randomBytes } from "node:crypto";
const origin = process.env.TIERX_V2_SMOKE_URL || "http://127.0.0.1:18083";
if (!["localhost", "127.0.0.1"].includes(new URL(origin).hostname)) throw new Error("Local smoke test only");
let token;
async function request(path, method = "GET", body, setup = false) {
  const response = await fetch(origin + path, { method, headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(setup ? { "X-TierX-Installation-Token": process.env.TIERX_V2_SETUP_TOKEN || "" } : {}) }, ...(body ? { body: JSON.stringify(body) } : {}) });
  const data = await response.json();
  if (!response.ok) throw new Error(`${method} ${path}: ${response.status} ${JSON.stringify(data.detail)}`);
  return data;
}
let status;
const readyDeadline = Date.now() + 60000;
while (Date.now() < readyDeadline) {
  try { status = await request("/api/v1/installation/status"); break; }
  catch { await new Promise(resolve => setTimeout(resolve, 1000)); }
}
assert.ok(status, "Backend did not become ready within 60 seconds");
assert.ok(!status.installed || process.env.TIERX_V2_SMOKE_RESUME === "true", "Use a fresh disposable deployment, or explicitly permit a synthetic rerun. This script never resets installation.");
const password = process.env.TIERX_V2_SMOKE_PASSWORD || randomBytes(24).toString("base64url");
if (!status.installed) await request("/api/v1/installation/complete", "POST", { email: "admin@example.com", password, values: { ...status.defaults, public_url: origin.replace("127.0.0.1", "localhost") } }, true);
token = (await request("/api/v1/auth/login", "POST", { email: "admin@example.com", password })).access_token;
const tenant = await request("/api/v1/admin/tenants", "POST", { name: `workflow-smoke-${Date.now()}`, display_name: "Synthetic V2 Test", allowed_source_systems: ["SPLUNK"] });
await request(`/api/v1/admin/tenants/${tenant.tenant_id}/status`, "PATCH", { status: "ACTIVE" });
const existing = (await request("/api/v2/admin/llm-profiles")).items.find(p => p.profile_code === "local-analysis");
await request("/api/v2/admin/llm-profiles/local-analysis", "PUT", { profile_code: "local-analysis", provider: "ollama", base_url: "http://ollama:11434", model: "phi3:latest", tenant_ids: [...new Set([...(existing?.tenant_ids || []), tenant.tenant_id])], max_tokens: 1024, timeout_seconds: 120, expected_revision: existing?.revision || 0 });
await request("/api/v2/admin/llm-profiles/local-analysis/test", "POST");
const prefix = `/api/v2/tenants/${tenant.tenant_id}`;
const graph = (await request(prefix + "/workflow-catalog")).default_graph;
const mapping = { "host.hostname": "result.host", "source.ip": "result.src", "event.severity": "result.severity", "rule.id": "result.rule_id", "event.created": "result._time" };
graph.nodes.find(n => n.type === "validation").config = { field_mapping: mapping, critical_fields: ["host.hostname", "source.ip", "event.severity"] };
graph.nodes.find(n => n.type === "normalization").config = { field_mapping: mapping };
graph.nodes.find(n => n.type === "llm_analysis").config = { profile_code: "local-analysis", prompt: "Use only supplied evidence. Summarize the normalized activity. Return the required JSON with no invented facts." };
await request(prefix + "/flows/validate", "POST", { graph });
const flow = await request(prefix + "/flows", "POST", { name: "Synthetic parity smoke", graph });
const published = await request(prefix + `/flows/${flow.flow_id}/publish`, "POST");
await request(prefix + "/flow-bindings", "PUT", { flow_id: flow.flow_id, revision: published.revision });
const payload = sequence => ({ alert_type: "example.endpoint", source_system: "SPLUNK", raw_payload: { result: { host: "EXAMPLE-ENDPOINT", src: "192.0.2.42", severity: "5", rule_id: `synthetic-${sequence}-${Date.now()}`, _time: new Date().toISOString() } } });
async function finish(accepted, expected = "SUCCEEDED") {
  const deadline = Date.now() + 300000;
  while (Date.now() < deadline) {
    const run = await request(prefix + `/runs/${accepted.run_id}`);
    if (["SUCCEEDED", "SUCCEEDED_WITH_WARNINGS", "FAILED"].includes(run.state)) {
      assert.equal(run.state, expected, JSON.stringify(run.nodes?.map(n => ({ node: n.node_id, state: n.state, error: n.error }))));
      return run;
    }
    await new Promise(r => setTimeout(r, 1000));
  }
  throw new Error("V2 smoke run timed out");
}
const first = await finish(await request(prefix + "/ingest", "POST", payload("first")));
assert.ok(first.alert.cluster_id); assert.ok(first.cluster.summary.headline);
assert.equal(first.cluster.analysis_status, "SUCCEEDED");
assert.ok(first.created_at.endsWith("Z") || first.created_at.endsWith("+00:00"));
const secondPayload = payload("second");
const second = await finish(await request(prefix + "/ingest", "POST", secondPayload));
assert.equal(second.alert.cluster_id, first.alert.cluster_id); assert.equal(second.cluster.alert_count, 2);
assert.ok(second.cluster.analyzed_version >= 2); assert.ok(second.cluster.summary.history.length >= 1);
const duplicate = await finish(await request(prefix + "/ingest", "POST", secondPayload), "FAILED");
assert.ok(duplicate.nodes.some(n => n.error?.type === "DUPLICATED_ALERT"));
const invalid = payload("invalid"); delete invalid.raw_payload.result.host;
const rejected = await finish(await request(prefix + "/ingest", "POST", invalid), "FAILED");
assert.ok(rejected.nodes.some(n => n.error?.type === "MISSING_REQUIRED_FIELD"));
// Reserved .invalid never receives an alert; this tests the real safe failure path.
const actionCode = `synthetic-unavailable-${Date.now()}`;
await request("/api/v1/admin/enrichment-actions", "POST", { action_code: actionCode, name: "Synthetic unavailable provider", description: "Disposable V2 failure-isolation test", url: "https://provider.invalid/context", timeout_seconds: 1, tenant_scope: "SELECTED_TENANTS", tenant_ids: [tenant.tenant_id] });
const parallel = (await request(prefix + "/workflow-catalog")).examples.find(t => t.name === "Parallel context with catch").graph;
for (const type of ["validation", "normalization"]) parallel.nodes.find(n => n.type === type).config = graph.nodes.find(n => n.type === type).config;
parallel.nodes.find(n => n.type === "enrichment_action").config.action_code = actionCode;
parallel.nodes.find(n => n.type === "llm_analysis").config = graph.nodes.find(n => n.type === "llm_analysis").config;
const parallelFlow = await request(prefix + "/flows", "POST", { name: "Synthetic parallel fallback smoke", graph: parallel });
const recovered = await finish(await request(prefix + "/ingest", "POST", { ...payload("parallel"), flow_id: parallelFlow.flow_id, draft_version: parallelFlow.draft_version }), "SUCCEEDED_WITH_WARNINGS");
assert.ok(recovered.nodes.some(n => n.node_id === "provider" && n.state === "FAILED"));
assert.ok(recovered.nodes.some(n => n.node_id === "provider-catch" && n.state === "SUCCEEDED"));
assert.deepEqual(Object.keys(recovered.nodes.find(n => n.node_id === "context-join").output.branches), ["kb", "provider"]);
const clusterView = await request(prefix + `/clusters/${recovered.alert.cluster_id}`);
assert.ok(clusterView.requests.length > 0);
console.log(`PASS: tenant ${tenant.tenant_id}; solo cluster ${first.alert.cluster_id}; correlated pair, real summaries/history, duplicate/validation DLQ, parallel branches and handled provider failure. Credentials were not printed.`);
