# Workflows, playbooks, agents and tools

## Definitions and ownership

Platform administrators manage shared definitions and tenant grants in **Workflow Studio**. A workflow is the outer graph; a playbook is an executable nested graph; an agent is a reusable prompt, tested model profile, output schema and bounded tool allowlist.

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

## Rollout

`TIERX_WORKFLOW_ENGINE_ENABLED=false` by default. Deploy disabled, prepare and test profiles/tools, publish subflows and workflows, grant tenants, and generate fixed entry credentials. The private worker runs `python workflow_main.py` from the pipeline image and exposes no port.

Before enabling the flag consistently on backend, ingestion proxy and pipeline, drain legacy Kafka and durable analysis/action queues. Enabled cutover retires legacy private ingestion with 410 and stops legacy consumers from starting. No database wipe, implicit default-binding migration, or historical backfill occurs. Do not toggle mid-flight. Historical records remain readable.

Rollback requires deliberate draining/cancellation and restoration of the prior ingestion route before re-enabling old consumers. Preserve databases, volumes and encryption keys. Use the normal immutable semantic release workflow; never build an unpinned branch on a server.
