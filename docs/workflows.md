# Workflows, playbooks, agents and tools

## Definitions and ownership

Platform administrators manage shared definitions and tenant grants in the
Workflows, Playbooks, and Agents libraries. A workflow is the outer graph; a
playbook is an executable nested graph; an agent is a reusable prompt, tested
model profile, output schema and bounded tool allowlist.

## Editor experience

Each library opens with search, status cards and one create action. Select an
item to edit it; templates create an unpublished copy. The editor separates
the canvas/agent setup from Settings, Ingestion (workflows only), Executions and
Versions. Save draft stores edits; Publish activates an immutable revision for
new runs. Publication and credential rotation require explicit confirmation.

Back, title, draft status, Save and Publish occupy the dashboard top bar while
editing. Descriptions live in Settings. The platform health badge remains on
ordinary dashboard pages, not in the editor toolbar.

Add step opens an overlay palette on demand. Selecting a node overlays its inspector
without shrinking the canvas. Expand canvas uses the full viewport and retains
the editor actions; Escape dismisses the inspector/palette before leaving expanded
mode. Canvas tools contains the collapsed connection and import controls;
each node also has a keyboard-focusable Inspect control. The connection manager
offers a keyboard alternative to dragging edges. Advanced graph/agent JSON is
collapsed, and invalid imports preserve the graph. Unsaved changes are guarded
when returning to the library or leaving the page. Tenant grants use a searched,
paged name selector rather than a comma-separated UUID field.

Tools & integrations and Model profiles are under Settings and have separate
searchable libraries and editors. Credentials remain write-only. Test saved
profiles and discover saved MCP tools only after saving changes. Execution
inspection keeps the pinned flow version prominent and technical identifiers
under an expandable section. The execution tab shows matching runs from the
recent tenant run page, not an unbounded historical search.

## Definitions and runtime

Workflows, Playbooks and Agents use the same icon-based node kit, categorized
searchable palette, typed settings and advanced JSON escape hatch. The separate
Ingestion V2 editor is retired; its entry URLs redirect to the Studio. Selecting
a direct call or selector reveals all referenced subflows, including static
mappings, model candidates and fallback roles. Expand a bordered preview or open
the nested definition, then return using breadcrumbs. These are current editable
definition previews; Debug displays the immutable revisions actually executed.

Publication activates a revision for new ingestion. Existing runs pin the entire dependency bundle: workflow, playbooks, agents, schemas, connectors and profiles. Republish a workflow to adopt updated children. Immediate enable/grant revocation prevents further calls even from pinned revisions.

Graphs are acyclic, with explicit conditions, paired parallel fork/join nodes and error routes. Agent reasoning is a bounded internal loop. No business stage is permanently locked at the front. Typed prerequisites still require normalized evidence before correlation, retrieval or reasoning. Tenant, authentication and safety invariants cannot be disabled in a graph.

Maximum nested call depth is three. Agent defaults: five rounds, ten tool calls. Root aggregate call budget: 100, durable and replay-idempotent. Parents release their worker slot while awaiting children. Leases heartbeat every 30 seconds.

## Nodes

| Node | Responsibility |
| --- | --- |
| Entry | Fixed raw-source or envelope contract |
| Validation / mapping | Schema checks and deterministic ECS mapping |
| Fingerprint | Exact duplicate suppression |
| Correlation | Exact entity/MITRE overlap and grouping |
| Deterministic / semantic KB | Existing tenant retrieval channels |
| LLM call | One structured inference |
| Agent | Bounded model, tools or subagents |
| Playbook call / selector | Explicit subflow or trusted selection plus fallback |
| Tool call | Approved external REST/MCP tool |
| Persist analysis | Alert-owned immutable analysis record |
| Notify Jira | Explicit delivery to initiating issue |
| Webhook | Approved connector delivery of chosen output |
| Condition / fork / join / catch | Routing, parallelism and recovery |
| Complete / dead letter | Terminal outcome |

Tools have approved JSON schemas, explicit tenant grants and encrypted write-only credentials. No shell, inline script, subprocess, or model-generated database query is supported. See the [example provider and node definition](../examples/workflow-providers/README.md).

Static mappings win. Otherwise the playbook selector can ask a model to choose from at most 20 configured candidates. Code validates code/confidence against the configured threshold (default 0.70). Failed/untrusted selection invokes a configured fallback **playbook**, not the outer workflow. Specialist templates do not pretend to install integrations.

## Fixed ingestion URL

There is no tenant default. Each granted workflow has its own stable URL:

```text
POST /api/v2/workflows/{code}/tenants/{tenant_id}/ingest
Authorization: Bearer <copy-once entry credential>
Idempotency-Key: <caller delivery ID>
```

Generate/rotate entry credentials in the studio; only their hashes are retained. Reusing an idempotency key with different input returns 409. A raw entry supplies source system, alert type and original timestamp extraction path. An envelope entry accepts `{source_system,alert_type,timestamp,raw_payload}`. Original timestamps require a timezone. Callers cannot override the workflow revision. A 202 response returns alert ID, run ID and execution URL immediately.

## Correlation and analysis

`group: null` selects the tenant's shared pool; named groups isolate workflows. Only alerts that execute correlation participate. Unmatched participating alerts get solo clusters; exact matches may join open clusters. No automatic cluster merge or movement from closed clusters occurs.

Matching uses exact case-sensitive ECS field/value pairs or MITRE equality. Default candidate and grouping windows are 24 hours. Stable cluster selection prefers largest membership, earliest creation, then cluster ID. There is no undefined overlap score or hidden debounce/analysis scheduling.

LLM input defaults to the initiating alert; optional `input_scope: correlated` adds a bounded durable member snapshot. Upstream tool/agent results and retrieved evidence are included as untrusted context. Persist Analysis writes `alert.alert_analysis` plus immutable history, never another member's result or analyst verdict. Cluster pages show individual alert results. Historical cluster summaries remain readable.

## Jira and explicit outputs

Each Forge installation is configured with one fixed workflow URL:

```text
https://your-instance.example/api/v2/workflows/{code}/tenants/{tenant_id}/jira
```

The platform administrator explicitly grants the Jira site connection access to the workflow. A Jira administrator enters this URL, connection ID and copy-once secret, approves egress, then tests/saves. Changing the URL/connection invalidates pending jobs. Secrets remain encrypted in Forge. Changed permissions can require reinstalling/upgrading the app.

Jira supplies one raw source JSON object. Entry configuration supplies routing; issue identity remains separate trusted provenance. Cloud ID/site URL must match the authenticated connection. Acknowledgements/errors describe transport/processing. Completing analysis does **not** implicitly post a final comment. Each Notify Jira node creates its own idempotent delivery, posted and acknowledged by Forge. Without it, stored analysis is available for polling; an explicit webhook can deliver elsewhere.

Human-response waiting, implicit learning, automatic benign-rule approval and automatic false-positive closure are not implemented. Alert feedback through the dashboard or `/api/v2/tenants/{tenant}/alerts/{alert}/feedback` is recorded evidence, not an automatic verdict or training update.

## Execution inspection

The execution view shows the pinned root flow revision and checksum separately from the application release. Every graph node appears, including not-reached nodes and capability-only tool definitions. Executed nodes expose sanitized input/output snapshots, checks, decisions, routes, attempts, timestamps, active execution time and wall elapsed time. Nested playbook/agent runs link to their own node timelines. The alert Debug page resolves workflow executions automatically. Copied summaries include the pinned flow version.

Full prompts, raw alerts, evidence text and credentials are excluded from debug/run-list responses. Snapshots above 32 KiB are omitted with checksum and size metadata, not silently truncated. Authorized alert detail retains its separate original source record. Model profiles expose an explicit context-token limit (default 2,048) for Ollama; size it against the tested model and available memory.

Use the dependency-free [Workflow Sandbox](../examples/workflow-sandbox/README.md) to send synthetic alerts and watch the last five runs without blocking ingestion. It starts with `npm install` and `npm run dev` and keeps credentials only in page memory.

Tenant-authorized users may inspect runs and analysis history. Only platform admins cancel root runs and descendants. Cancellation cannot recall already dispatched external operations.

If cancellation races an analysis-history write, the uncommitted history item is
retained for audit with `persistence_state=DISCARDED` and a `discard_reason`.
It is not the alert's current analysis, is excluded from normal analysis history,
and cannot be selected as a feedback target. Debug uses bounded, sanitized snapshots
for node inputs, outputs and propagated error input; internal ancestry and evidence
reference fields are not returned.

## Rollout

Workflows are the only execution system. The standard pipeline service runs the
workflow scheduler through `python main.py` and exposes no public port. No mode
flag or optional worker profile is required. Backend readiness requires a fresh
workflow-worker heartbeat, even before any definitions have been imported.

Publish explicitly configured subflows and workflows, grant tenants, and generate
fixed entry credentials before submitting alerts. There is no built-in default
workflow. Legacy ingestion and legacy flow mutations return `410 Gone`;
historical read interfaces remain available. Existing experimental graph-format
1 runs are not scheduled by the current worker. Upgrade operators must drain or
archive old Kafka and durable queues before switching releases. No database wipe,
implicit default-binding migration, or historical backfill occurs automatically.

Rollback requires deliberate draining/cancellation and deployment of a previous
release, not changing an execution-mode flag. Preserve databases, volumes and
encryption keys. Use immutable semantic releases; never build an unpinned branch
on a server.
