import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock

import mongomock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.dependencies.auth import get_current_user
from app.api.v2 import workflows, llm_profiles
from app.schemas.user import AuthenticatedUser
from tierx_workflows import GraphError, checksum, decide, default_graph, validate_graph


def minimal():
    return {
        "format_version": "1.0",
        "nodes": [
            {"id": "start", "type": "entry", "config": {}},
            {"id": "done", "type": "complete", "config": {}},
        ],
        "edges": [
            {
                "id": "next",
                "source": "start",
                "target": "done",
                "sourceHandle": "success",
            }
        ],
    }


def test_examples_and_canvas_validation():
    from tierx_workflows.examples import examples

    assert len(examples()) == 4
    graph = minimal()
    graph["viewport"] = {"x": 5, "y": 10, "zoom": 0.5}
    assert validate_graph(graph)["viewport"]["zoom"] == 0.5
    graph["viewport"]["zoom"] = -1
    with pytest.raises(GraphError):
        validate_graph(graph)
    graph = minimal()
    graph["nodes"][1]["position"] = {"x": "invalid", "y": 1}
    with pytest.raises(GraphError):
        validate_graph(graph)


def test_unknown_tools_and_remote_schema_refs_fail_closed():
    graph = default_graph()
    model = next(n for n in graph["nodes"] if n["type"] == "llm_analysis")
    model["type"] = "llm_tools"
    model["config"]["tools"] = None
    with pytest.raises(GraphError):
        validate_graph(graph)
    model["config"]["tools"] = ["shell"]
    with pytest.raises(GraphError):
        validate_graph(graph)
    model["config"]["tools"] = []
    model["config"]["output_schema"] = {"$ref": "https://example.com/schema"}
    with pytest.raises(GraphError):
        validate_graph(graph)


@pytest.fixture
def setup(monkeypatch):
    mongo = mongomock.MongoClient(tz_aware=True)
    monkeypatch.setenv("TIERX_INGESTION_V2_ENABLED", "true")
    monkeypatch.setenv(
        "TIERX_WEBHOOK_SECRET_ENCRYPTION_KEY",
        base64.urlsafe_b64encode(b"x" * 32).decode(),
    )
    monkeypatch.setattr(
        workflows.DatabaseManager,
        "get_tenant_database",
        staticmethod(lambda name: mongo[name]),
    )
    monkeypatch.setattr(
        workflows,
        "Tenant",
        SimpleNamespace(
            objects=lambda **kw: SimpleNamespace(
                first=lambda: SimpleNamespace(
                    db_name=f"tenant_{kw['tenant_id']}",
                    status="ACTIVE",
                    allowed_source_systems=["SPLUNK"],
                )
            )
        ),
    )
    app = FastAPI()
    app.include_router(workflows.router, prefix="/api/v2")
    app.include_router(llm_profiles.router, prefix="/api/v2")
    user = AuthenticatedUser(
        user_id="operator",
        email="operator@example.com",
        role="TENANT_ADMIN",
        tenant_id="one",
    )
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app), mongo, user


def test_draft_conflict_publication_and_bindings(setup):
    client, mongo, _ = setup
    root = "/api/v2/tenants/one"
    row = client.post(
        root + "/flows", json={"name": "Synthetic", "graph": minimal()}
    ).json()
    flow = row["flow_id"]
    assert (
        client.put(
            root + f"/flows/{flow}",
            json={"name": "Changed", "graph": minimal(), "expected_version": 2},
        ).status_code
        == 409
    )
    published = client.post(root + f"/flows/{flow}/publish").json()
    assert published["revision"] == 1
    assert (
        client.put(
            root + "/flow-bindings", json={"flow_id": flow, "revision": 1}
        ).status_code
        == 200
    )
    assert (
        client.put(
            root + "/flow-bindings",
            json={"flow_id": flow, "revision": 1, "source_system": "SPLUNK"},
        ).status_code
        == 422
    )
    accepted = client.post(
        root + "/ingest",
        json={
            "source_system": "SPLUNK",
            "alert_type": "example",
            "raw_payload": {"event": "synthetic"},
        },
    )
    assert accepted.status_code == 202
    assert mongo.tenant_one.v2_runs.count_documents({}) == 1
    assert mongo.tenant_one.alerts.count_documents({}) == 0
    assert client.get(root + f"/flows/{flow}/export").json() == {
        "name": "Synthetic",
        "graph": minimal(),
    }
    assert (
        client.post(
            root + "/flows/import", json={"name": "Imported", "graph": minimal()}
        ).status_code
        == 201
    )


def test_tenant_isolation_operator_roles_and_disabled(setup, monkeypatch):
    client, _, user = setup
    assert client.get("/api/v2/tenants/two/flows").status_code == 403
    user.role = "TENANT_OPERATOR"
    assert client.get("/api/v2/tenants/one/flows").status_code == 200
    assert (
        client.post(
            "/api/v2/tenants/one/flows", json={"name": "no", "graph": minimal()}
        ).status_code
        == 403
    )
    monkeypatch.setenv("TIERX_INGESTION_V2_ENABLED", "false")
    assert client.get("/api/v2/tenants/one/flows").status_code == 404


def test_exact_binding_precedence_and_cluster_reads(setup):
    client, mongo, _ = setup
    root = "/api/v2/tenants/one"
    ids = []
    for name in ("default", "override"):
        row = client.post(
            root + "/flows", json={"name": name, "graph": minimal()}
        ).json()
        client.post(root + f"/flows/{row['flow_id']}/publish")
        ids.append(row["flow_id"])
    client.put(root + "/flow-bindings", json={"flow_id": ids[0], "revision": 1})
    client.put(
        root + "/flow-bindings",
        json={
            "flow_id": ids[1],
            "revision": 1,
            "source_system": "SPLUNK",
            "alert_type": "example",
        },
    )
    for alert_type, expected in (("example", ids[1]), ("other", ids[0])):
        row = client.post(
            root + "/ingest",
            json={
                "source_system": "SPLUNK",
                "alert_type": alert_type,
                "raw_payload": {"synthetic": True},
            },
        ).json()
        assert (
            mongo.tenant_one.v2_runs.find_one({"run_id": row["run_id"]})["flow_id"]
            == expected
        )
    assert len(client.get(root + f"/flows/{ids[0]}/revisions").json()["items"]) == 1
    mongo.tenant_one.v2_clusters.insert_one(
        {
            "cluster_id": "cluster",
            "tenant_id": "one",
            "summary": {"headline": "Synthetic"},
        }
    )
    mongo.tenant_one.v2_alerts.insert_one(
        {
            "alert_id": "a",
            "cluster_id": "cluster",
            "raw_payload": {"private": "raw"},
            "playbook_snapshot": {"prompt": "full prompt"},
        }
    )
    response = client.get(root + "/clusters/cluster")
    assert response.status_code == 200
    assert (
        "raw_payload" not in response.text and "playbook_snapshot" not in response.text
    )
    assert client.get("/api/v2/tenants/two/clusters/cluster").status_code == 403


def test_unauthenticated_and_source_rejection(setup):
    client, _, _ = setup
    assert (
        client.post(
            "/api/v2/tenants/one/ingest",
            json={
                "source_system": "UNKNOWN",
                "alert_type": "example",
                "raw_payload": {},
            },
        ).status_code
        == 422
    )
    client.app.dependency_overrides.clear()
    assert client.get("/api/v2/tenants/one/flows").status_code in (401, 403)


def test_profile_credentials_encrypted_and_capability_test(setup, monkeypatch):
    client, mongo, user = setup
    user.role = "PLATFORM_ADMIN"
    body = {
        "profile_code": "test-profile",
        "provider": "ollama",
        "base_url": "http://ollama:11434",
        "model": "test-model",
        "tenant_ids": ["one"],
        "api_key": "synthetic-provider-key",
        "tool_mode": "json_emulated",
    }
    created = client.put("/api/v2/admin/llm-profiles/test-profile", json=body)
    assert created.status_code == 200
    assert "credentials" not in created.json() and "api_key" not in created.json()
    stored = mongo.soc_mind_platform.v2_llm_profiles.find_one({})
    assert "synthetic-provider-key" not in str(stored)
    assert llm_profiles.decrypt(stored) == body["api_key"]
    monkeypatch.setattr(
        llm_profiles,
        "infer",
        AsyncMock(
            side_effect=[
                {"kind": "final", "result": {"ready": True}},
                {
                    "kind": "final",
                    "result": {
                        "kind": "tool_calls",
                        "calls": [{"name": "echo", "arguments": {"value": "test"}}],
                    },
                },
            ]
        ),
    )
    assert (
        client.post("/api/v2/admin/llm-profiles/test-profile/test").status_code == 200
    )
    assert mongo.soc_mind_platform.v2_llm_profile_revisions.count_documents({}) == 1
    assert "credentials" not in client.get("/api/v2/admin/llm-profiles").text
    assert (
        client.put("/api/v2/admin/llm-profiles/test-profile", json=body).status_code
        == 409
    )


@pytest.mark.parametrize(
    "provider,url,consent",
    [
        ("other", "http://ollama:11434", False),
        ("ollama", "https://provider.example", False),
        ("ollama", "http://ollama:11434", True),
        ("ollama", "http://user:secret@ollama:11434", False),
    ],
)
def test_invalid_profile_wiring(setup, provider, url, consent):
    client, _, user = setup
    user.role = "PLATFORM_ADMIN"
    assert (
        client.put(
            "/api/v2/admin/llm-profiles/test",
            json={
                "profile_code": "test",
                "provider": provider,
                "base_url": url,
                "model": "test",
                "tenant_ids": ["one"],
                "allow_external_data": consent,
            },
        ).status_code
        == 422
    )


def test_default_graph_and_strict_comparisons():
    assert validate_graph(default_graph())
    assert checksum(minimal()) == checksum(minimal())
    assert not decide({"value": 1}, {"path": "value", "operator": "eq", "value": True})
    assert decide(
        {"ip": "10.2.3.4"},
        {"path": "ip", "operator": "cidr_contains", "value": "10.0.0.0/8"},
    )
    assert not decide(
        {"ip": "192.0.2.1"},
        {"path": "ip", "operator": "cidr_contains", "value": "10.0.0.0/8"},
    )


@pytest.mark.parametrize(
    "mutation", ["cycle", "unknown", "unreachable", "duplicate", "code"]
)
def test_rejects_invalid_graphs(mutation):
    graph = minimal()
    if mutation == "cycle":
        graph["edges"].append({"id": "cycle", "source": "done", "target": "start"})
    if mutation == "unknown":
        graph["nodes"][0]["type"] = "shell"
    if mutation == "unreachable":
        graph["nodes"].append({"id": "other", "type": "complete"})
    if mutation == "duplicate":
        graph["nodes"][1]["id"] = "start"
    if mutation == "code":
        graph["nodes"][0]["config"] = {"script": "arbitrary code"}
    with pytest.raises(GraphError):
        validate_graph(graph)
