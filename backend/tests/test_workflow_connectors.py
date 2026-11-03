import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest
from app.api.v2 import connectors
from test_workflows_v2 import setup, minimal
from tierx_workflows.connectors import ConnectorClient, ConnectorError, destination
from tierx_workflows.graph import validate_graph, GraphError


def test_connector_permissions_encryption_and_revision(setup, monkeypatch):
    client, mongo, user = setup
    client.app.include_router(connectors.router, prefix="/api/v2")
    monkeypatch.setattr(
        connectors,
        "destination",
        AsyncMock(return_value=("https://example.com", None, None)),
    )
    body = {
        "kind": "rest",
        "name": "Synthetic assets",
        "url": "https://example.com/context",
        "tenant_ids": ["one"],
        "credential": "synthetic-test-credential",
        "tools": [
            {
                "name": "asset_context",
                "description": "Synthetic asset context",
                "input_schema": {"type": "object"},
                "output_schema": {"type": "object"},
            }
        ],
    }
    assert client.put("/api/v2/admin/connectors/assets", json=body).status_code == 403
    user.role = "PLATFORM_ADMIN"
    response = client.put("/api/v2/admin/connectors/assets", json=body)
    assert response.status_code == 200
    assert "synthetic-test-credential" not in response.text
    stored = mongo.soc_mind_platform.v2_connectors.find_one({})
    assert connectors.decrypt(stored) == "synthetic-test-credential"
    assert "synthetic-test-credential" not in str(stored)
    assert client.put("/api/v2/admin/connectors/assets", json=body).status_code == 409


def test_entry_token_scope_rotation_and_raw_timestamp(setup, monkeypatch):
    monkeypatch.setenv("TIERX_WORKFLOW_ENGINE_ENABLED", "true")
    from app.api.v2 import definitions, entrypoints
    from app.api.v2 import workflows
    monkeypatch.setattr(entrypoints, "Tenant", workflows.Tenant)
    client, mongo, user = setup
    user.role = "PLATFORM_ADMIN"
    client.app.include_router(definitions.router, prefix="/api/v2")
    client.app.include_router(entrypoints.router, prefix="/api/v2")
    graph = minimal()
    graph["format_version"] = "2.0"
    graph["nodes"][0]["config"] = {
        "input_mode": "raw",
        "source_system": "SPLUNK",
        "alert_type": "synthetic",
        "timestamp_path": "result._time",
    }
    root = "/api/v2/admin/workflow-definitions/workflow/raw"
    assert client.put(root, json={"name": "Raw workflow", "tenant_ids": ["one"], "configuration": graph}).status_code == 200
    assert client.post(root + "/publish").status_code == 200
    # Publication, not a content-edit counter, pins newly resolved child/resources.
    assert client.post(root + "/publish").json()["revision"] == 2
    credential = client.post(
        root + "/entry-credentials", json={"tenant_id": "one"}
    )
    assert credential.status_code == 200
    token = credential.json()["token"]
    assert token not in str(mongo.soc_mind_platform.workflow_entries.find_one({}))
    endpoint = "/api/v2/workflows/raw/tenants/one/ingest"
    assert client.post(endpoint, json={}).status_code == 401
    headers = {"Authorization": "Bearer " + token}
    assert client.post(endpoint, headers=headers, json={}).status_code == 422
    payload = {"result": {"_time": "2026-01-01T12:00:00Z", "host": "synthetic"}}
    assert client.post(endpoint, headers=headers, json=payload).status_code == 202
    run = mongo.tenant_one.v2_runs.find_one({})
    assert run["input"]["raw_payload"] == payload
    assert run["input"]["timestamp"] == "2026-01-01T12:00:00+00:00"
    client.post(root + "/entry-credentials", json={"tenant_id": "one"})
    assert client.post(endpoint, headers=headers, json=payload).status_code == 401


def test_mcp_discovery_and_call_validate_actual_protocol(monkeypatch):
    monkeypatch.setenv("TIERX_V2_LOCAL_CONNECTOR_ORIGINS", "http://provider:8090")
    methods = []

    def handle(request):
        import json

        body = json.loads(request.content)
        methods.append(body["method"])
        assert request.headers["authorization"] == "Bearer synthetic"
        if body["method"] == "notifications/initialized":
            return httpx.Response(202)
        results = {
            "initialize": {"protocolVersion": "2025-11-25"},
            "tools/list": {"tools": [{"name": "asset_context"}]},
            "tools/call": {"structuredContent": {"outcome": "UNKNOWN"}},
        }
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": results[body["method"]],
            },
        )

    async def check():
        client = ConnectorClient(
            {"kind": "mcp", "url": "http://provider:8090/mcp"},
            "synthetic",
            httpx.MockTransport(handle),
        )
        assert (await client.discover())[0]["name"] == "asset_context"
        tool = {
            "name": "asset_context",
            "input_schema": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            "output_schema": {"type": "object", "required": ["outcome"]},
        }
        assert await client.call(tool, {}, "one") == {"outcome": "UNKNOWN"}
        with pytest.raises(ConnectorError, match="ARGUMENTS"):
            await client.call(tool, {"unexpected": True}, "two")

    asyncio.run(check())
    assert methods == [
        "initialize",
        "notifications/initialized",
        "tools/list",
        "initialize",
        "notifications/initialized",
        "tools/call",
    ]


def test_tool_capability_edges_are_not_execution_edges():
    graph = minimal()
    graph["format_version"] = "2.0"
    graph["nodes"][1:1] = [
        {"id": "valid", "type": "validation", "config": {}},
        {"id": "normal", "type": "normalization", "config": {}},
        {"id": "agent", "type": "llm_tools", "config": {"profile_code": "local", "tools": ["connector:assets:asset_context"]}},
        {
            "id": "tool",
            "type": "tool_call",
            "config": {"connector_code": "assets", "tool_name": "asset_context"},
        },
    ]
    graph["edges"] = [
        {"id": str(i), "source": source, "target": target}
        for i, (source, target) in enumerate(
            zip(
                ["start", "valid", "normal", "agent"],
                ["valid", "normal", "agent", "done"],
            )
        )
    ]
    graph["edges"].append(
        {
            "id": "capability",
            "source": "tool",
            "target": "agent",
            "sourceHandle": "tool",
            "targetHandle": "tools",
        }
    )
    assert validate_graph(graph)
    graph["edges"][-1]["target"] = "normal"
    with pytest.raises(GraphError):
        validate_graph(graph)


def test_mcp_handshake_and_call_share_one_outer_deadline(monkeypatch):
    monkeypatch.setenv("TIERX_V2_LOCAL_CONNECTOR_ORIGINS","http://provider:8090")
    import json
    async def handler(request):
        await asyncio.sleep(0.035)
        body=json.loads(request.content)
        if body["method"]=="notifications/initialized": return httpx.Response(202)
        return httpx.Response(200,json={"jsonrpc":"2.0","id":body["id"],"result":{"protocolVersion":"2025-11-25"}})
    async def check():
        client=ConnectorClient({"url":"http://provider:8090/mcp","kind":"mcp","timeout_seconds":0.08},transport=httpx.MockTransport(handler))
        with pytest.raises(ConnectorError):
            await client.call({"name":"observe","input_schema":{"type":"object"},"output_schema":{"type":"object"}},{},"one")
    asyncio.run(check())


def test_connector_rejects_private_addresses_and_url_credentials(monkeypatch):
    monkeypatch.delenv("TIERX_V2_LOCAL_CONNECTOR_ORIGINS", raising=False)
    monkeypatch.setattr(
        "tierx_workflows.connectors.socket.getaddrinfo",
        lambda *args: [(2, 1, 6, "", ("127.0.0.1", 443))],
    )
    for url in [
        "https://example.com/context",
        "https://user:password@example.com",
        "http://example.com",
        "https://example.com/?token=test",
    ]:
        with pytest.raises(ConnectorError):
            asyncio.run(destination(url))


def test_connector_pins_public_dns_and_limits_response(monkeypatch):
    monkeypatch.setattr(
        "tierx_workflows.connectors.socket.getaddrinfo",
        lambda *args: [(2, 1, 6, "", ("8.8.8.8", 443))],
    )
    assert asyncio.run(destination("https://example.com/context")) == (
        "https://8.8.8.8:443/context",
        "example.com",
        "example.com",
    )

    def handle(request):
        assert (
            str(request.url) == "https://8.8.8.8/context"
            or str(request.url) == "https://8.8.8.8:443/context"
        )
        assert request.headers["host"] == "example.com"
        return httpx.Response(200, content=b"x" * (256 * 1024 + 1))

    with pytest.raises(ConnectorError, match="TOO_LARGE"):
        asyncio.run(
            ConnectorClient(
                {"kind": "rest", "url": "https://example.com/context"},
                transport=httpx.MockTransport(handle),
            ).request({})
        )
