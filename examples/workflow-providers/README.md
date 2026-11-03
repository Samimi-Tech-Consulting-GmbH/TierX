# Synthetic REST / MCP provider

Five deterministic read-only tools. No scanning, credential testing, inference, or response action. Unknown subjects return `UNKNOWN`, never an inferred benign verdict.

## Start locally

```sh
export EXAMPLE_PROVIDER_TOKEN="$(openssl rand -hex 32)"
docker compose up --build -d
curl http://127.0.0.1:18090/health
```

Run in this directory. Only localhost port 18090 is published. Delivery IDs persist in the SQLite named volume; `docker compose down` preserves it.

For a private development Compose network, explicitly set `TIERX_V2_LOCAL_CONNECTOR_ORIGINS=http://context-provider:8090` on backend and worker. This deployment-only exemption is for an isolated synthetic provider, not arbitrary private-network access. Normal connectors require public HTTPS, reject private DNS answers, pin the resolved address, and reject redirects.

## Register and use

1. As platform administrator, open **Workflow Studio → REST / MCP tools**.
2. Register `assets` with REST URL `http://context-provider:8090/rest` or MCP URL `http://context-provider:8090/mcp`, the disposable bearer credential, and explicit tenant grants.
3. Discover MCP tools, approve their input/output schemas, then save. Discovery alone grants no permission. REST uses the schemas from `server.py`.
4. Configure a standalone tool node:

```json
{
  "id": "asset-context",
  "type": "tool_call",
  "config": {
    "connector_code": "assets",
    "tool_name": "asset_context",
    "argument_paths": {"value": "alert.normalized_payload.host.name"}
  }
}
```

Evidence is available to later nodes as `nodes.asset-context.output.result` and as untrusted upstream LLM context. Both flat dotted ECS keys and nested dictionaries are supported.

An agent can instead declare `tools: ["connector:assets:asset_context"]`. Connect the matching tool node's purple `tool` port to the agent's `tools` port for visual documentation. A capability edge does not schedule a second request.

Tools: `asset_context`, `identity_context`, `indicator_reputation`, `maintenance_context`, `related_observations`. Input: `{"value":"subject"}`; output: `{source,subject,outcome,context}`. Synthetic subjects: `DB01`, `svc_backup`, `203.0.113.44`, `CHG-TEST-001`.

REST request:

```json
{"tool":"asset_context","arguments":{"value":"DB01"},"delivery_id":"stable-call-id"}
```

MCP uses Streamable HTTP initialization, `tools/list`, and `tools/call`; delivery identity is in `params._meta["tierx/delivery_id"]`. Completed calls are reused. Uncertain non-retry-safe calls fail closed. Providers must honor durable delivery identities before being marked retry-safe. Stdio, server-initiated sampling, and arbitrary scripts are unsupported.

## Verify

```sh
python -m pytest examples/workflow-providers/test_server.py -q
cd pipeline
PYTHONPATH=. pytest tests/test_workflow_runtime.py -q
```

The latter starts an ephemeral HTTP provider and verifies an agent's native tool-call round, actual MCP request, structured final output, and alert-owned persistence. `/v1/chat/completions` is a **synthetic protocol fixture**, not a real LLM or evidence of reasoning quality. Separately preflight a real model before rollout.

See [workflow setup](../../docs/workflows.md). Results belong to alerts even when correlation creates a cluster. No tenant-default workflow exists.
