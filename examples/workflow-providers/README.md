# Synthetic workflow providers

This isolated development fixture supplies REST and remote MCP tools for alert-triage workflow tests. It does not scan networks, test passwords, call external services, or perform response actions. All observations are fixed synthetic examples. Unknown subjects return `UNKNOWN`, never an inferred benign verdict.

## Run the provider

From this directory, set a disposable token in your shell and start the container:

```sh
export EXAMPLE_PROVIDER_TOKEN="$(openssl rand -hex 32)"
docker compose up --build -d
curl http://127.0.0.1:18090/health
```

Only localhost port 18090 is published. Delivery records persist in a named SQLite volume. `docker compose down` preserves them. Do not use this example token for a production integration.

For an isolated TierX Compose network, add the provider service to the private network without publishing its port. Set `TIERX_V2_LOCAL_CONNECTOR_ORIGINS=http://context-provider:8090` on the backend and workflow worker. This deployment-only exemption is for the synthetic container, not arbitrary private-network access. Normal connectors require public HTTPS and reject private DNS results and redirects.

## Register tools

As a platform administrator, open **Ingestion V2 → Connectors**. Create either:

- REST: `http://context-provider:8090/rest`
- MCP: `http://context-provider:8090/mcp`

Choose the permitted tenant IDs and provide the token as the bearer credential. Credentials are encrypted, write-only and excluded from workflow exports. For MCP, discover the catalog, explicitly select the approved tools, then save. Discovery never grants permission by itself.

The five tools are `asset_context`, `identity_context`, `indicator_reputation`, `maintenance_context`, and `related_observations`. Each accepts `{"value":"subject"}` and returns `source`, `subject`, `outcome`, and `context`. Useful synthetic subjects include `DB01`, `svc_backup`, `203.0.113.44`, and `CHG-TEST-001`.

The REST request contract is:

```json
{"tool":"asset_context","arguments":{"value":"DB01"},"delivery_id":"stable-call-id"}
```

The endpoint returns the structured tool result directly. This implementation intentionally uses a fixed JSON POST contract; arbitrary HTTP templating is not supported. MCP uses Streamable HTTP initialization, `tools/list`, and `tools/call`, with JSON or bounded SSE responses. TierX sends its stable delivery identity in `params._meta["tierx/delivery_id"]`. Providers must explicitly honor it before being marked retry-safe. Completed local calls are reused; uncertain non-retry-safe calls fail rather than repeating a possible side effect.

Reference: [MCP transport specification](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports). This bounded client does not support stdio subprocesses, OAuth discovery, server-initiated sampling, or resumable SSE replay.

## Example workflows

The workflow gallery includes parity, parallel context with catch, CIDR routing, and agentic triage examples. References must be mapped to local resources before publication.

1. **Deterministic pipeline:** Alert entry → Validate → Normalize → Deduplicate → Resolve playbook → Knowledge enrichment → Correlate & cluster → Analyze → Output.
2. **Agent triage:** Alert entry → Validate → Normalize → Agent → Output. Connect approved Tool call nodes to the Agent using the purple `tool` ports. These capability edges do not schedule the tool independently.
3. **Partial provider failure:** parallel Knowledge Base and REST branches converge at a Join. The provider error goes through Catch & fallback. The run completes with warnings and retains the original failure.
4. **CIDR routing:** a typed condition matches `source.ip` against `10.0.0.0/8`. The false route goes to a dead letter.

For an agent result, configure matching strict output schemas on Agent and Output, then set the Output result path to `nodes.<agent-node-id>.output.result`. Correlation is optional. Clusterless results are stored on the V2 alert; clustered analysis retains versioned cluster summaries.

Knowledge enrichment retains MongoDB documents/citations. Its hybrid toggle adds the existing Mem0/Qdrant semantic channel when that deployment is configured; it does not create a second memory system or learn from agent answers. Unavailable semantic retrieval falls back according to the existing KB contract.

## Repeatable tests

```sh
export TIERX_LOCAL_URL=http://127.0.0.1:18083
export TIERX_LOCAL_TENANT=<disposable-tenant-id>
export TIERX_LOCAL_EMAIL=<local-platform-admin>
read -s TIERX_LOCAL_PASSWORD
export TIERX_LOCAL_PASSWORD
python3 examples/workflow-providers/smoke.py
```

Run from the repository root. The script only permits localhost. It creates synthetic connectors/profiles and new example drafts in the selected disposable tenant. It checks successful parity/agent runs, duplicates, required fields, catch handling, and both CIDR outcomes. It never changes production data or deletes prior runs.

The provider exposes `/v1/chat/completions` as an explicitly named **synthetic protocol fixture**, not an LLM. It makes integration tests reproducible but does not validate model reasoning quality. Configure a separately tested real Ollama/OpenAI-compatible profile to assess inference quality. `/fail`, `/malformed`, and `/slow` provide controlled failure cases.

To verify the existing private-ingestion adapter, first choose a valid published default binding, then run `cutover_smoke.py` with the same environment. It temporarily selects V2, sends through the admin debug endpoint, follows the V2 run, and restores the original engine in `finally`. Debug tracing and V2 support must be enabled in the local backend/proxy. New alerts follow the selected engine; old data and in-flight runs are not migrated.

Unit tests for the provider: `pytest examples/workflow-providers/test_server.py`. Worker tests cover leases, replay, bounded execution, native/emulated protocols, and unauthorized calls. No example asserts exactly-once external side effects.
