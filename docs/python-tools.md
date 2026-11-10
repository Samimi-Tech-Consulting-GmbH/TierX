# Isolated Python tools

Platform administrators manage these at **Settings → Python tools**. Save a draft,
select authorized tenants, test with synthetic input, then publish. Draft saves use
optimistic version checks; publications are immutable. A workflow run pins the
published revision. Saving a disabled tool or removing a tenant grant prevents new
calls immediately, including calls from previously published workflows.

## Contract 1.0

The authoritative JSON schemas (`INPUT_SCHEMA`, `ALERT_SCHEMA`, `CLUSTER_SCHEMA`)
and `TypedDict` definitions live in `tierx_workflows.python_tools` and are returned
by `GET /api/v2/admin/python-tools`. Tool code requires a synchronous
`run(alert: AlertContext, cluster: ClusterContext | None) -> str | dict` function.
Hints are editing aids; JSON-schema checks enforce the runtime contract.

Alert fields: `alert_id`, `tenant_id`, `alert_type`, `source_system`, `event_time`,
`normalized_payload`, `enrichment`, `correlation`. Cluster is null or contains
`cluster_id`, `tenant_id`, allowlisted `metadata`, `correlation_basis`, and normalized
`members`. Raw source documents, internal identifiers, configuration and known
credential fields are excluded recursively. Administrators must not embed secrets
in source code or normalized evidence. Inputs are snapshotted once per invocation,
limited to 1 MiB and 100 members; oversized inputs fail rather than truncate.

Text output is `{"type":"text","text":"..."}` (16 KiB). JSON output is
`{"type":"json","data":{...}}` (64 KiB) and must match the declared schema.
Downstream paths use `nodes.<node-id>.output.result.data` or `.text`. Agent
capabilities use `python:<tool-code>` and accept no model-supplied arguments.
The runtime supplies context and revision, never the model. Results are untrusted
evidence, not commands to alter alerts or clusters.

## Execution boundary

`python_runner/Dockerfile.job` uses pinned Python 3.12 and its standard library.
`tierx_tools.http_request(url, method="GET", body=None)` and
`tierx_tools.tcp_connect(host, port)` use a per-call policy proxy. No packages,
custom images, target credentials, application mounts or Docker socket are supplied
to scripts. A fresh read-only, non-root container uses 256 MiB RAM, one CPU,
64 PIDs, 16 MiB temporary storage, dropped capabilities, Docker's default seccomp,
and no-new-privileges. The private broker runs at most two invocations concurrently.
Timeouts are 1–1800 seconds (30 by default); container setup counts toward deadline.

Only the broker receives a **dedicated rootless Docker socket**. Never mount the
application daemon socket. Rootless Docker requires Linux cgroup v2, systemd, and
effective cpu/memory/pids delegation. Startup checks actual container limits and
fails closed. Docker Desktop/rootful Docker is not an accepted deployment target.
Containers share a kernel: this is not a hostile-public-code or VM-grade sandbox.

Each job uses an isolated internal network with no gateway address. Only its
trusted proxy also joins an egress network. Exact hostnames or CIDRs plus ports are
approved per revision. Every DNS answer is checked at connection time and the
chosen address is pinned. HTTP redirects are rejected. Loopback, link-local,
metadata, reserved addresses, rootless network subnets and configured TierX
infrastructure CIDRs are denied even when explicitly allowed. Each invocation has
32 connection attempts. TCP checks open then close a connection; no arbitrary TCP
payload forwarding is supported.

The operator must include all TierX host, service, database, orchestration and
application network addresses in `TIERX_PYTHON_DENIED_NETWORKS`. Missing denylist,
unpinned image or ineffective isolation prevents broker startup. Use the optional
`compose.python-runner.yaml` overlay only after dedicated runtime provisioning.
The broker API has no published port; keep the bearer token private.

## Management API

All routes require platform-admin authentication under `/api/v2/admin/python-tools`:

- `GET /`: list drafts and contract schemas.
- `PUT /{code}`: save with `expected_version` (zero for creation).
- `POST /{code}/publish`: create/select an immutable published revision.
- `GET /{code}/versions`: published history.
- `POST /{code}/test`: explicitly execute the saved draft using `tenant_id`,
  `alert`, optional `cluster`, and `members`.
- `GET` or `DELETE /{code}/tests/{call_id}`: observe or cancel that test.

Invocations persist call identity, input/code hashes, revision, runtime digest,
queue/start/deadline/duration, bounded output and safe destination decisions.
Completed calls replay without execution. Uncertain requests are not retried:
approved HTTP requests can have side effects. Cancellation kills containers;
broker restart marks unfinished calls uncertain and removes orphan resources.
Runner errors follow explicit workflow error edges. Debug omits code, input
documents, output evidence and stdout/stderr; it exposes metadata and checksums.

## Verification and examples

`examples/python-tools/` contains synthetic summary, CIDR, HTTP and TCP functions.
Network examples intentionally use non-routable `.test` names; substitute only
operator-owned fixtures and approve those exact destinations. No scanning,
credentials or historical backfill is needed.

Run contract/broker tests with `PYTHONPATH=kb_shared pytest python_runner/`.
Backend and pipeline suites cover authorization, publications and durable replay.
Run Linux/rootless acceptance separately; unit tests and Docker Desktop builds
are not proof of network or resource isolation. Deployment requires a successful
rootless preflight and synthetic end-to-end acceptance before any tool is enabled.
