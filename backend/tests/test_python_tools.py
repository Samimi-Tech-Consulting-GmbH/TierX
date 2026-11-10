from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from app.api.v2 import python_tools
from test_workflows_v2 import setup


def value(**changes):
    return {"name": "Synthetic tool", "source": "def run(alert, cluster):\n return {'observed': True}",
        "tenant_ids": ["one"], "output_mode": "json", **changes}


def prepare(setup):
    client, mongo, user = setup
    client.app.include_router(python_tools.router, prefix="/api/v2")
    user.role = "PLATFORM_ADMIN"
    return client, mongo, user


def test_admin_authorization_revision_and_conflict(setup):
    client, mongo, user = prepare(setup)
    root = "/api/v2/admin/python-tools"
    user.role = "TENANT_ADMIN"
    assert client.get(root).status_code == 403
    user.role = "PLATFORM_ADMIN"
    saved = client.put(root + "/observe", json=value())
    assert saved.status_code == 200, saved.text
    assert client.post(root + "/observe/publish").json()["revision"] == 1
    assert client.put(root + "/observe", json=value()).status_code == 409
    assert client.put(root + "/observe", json=value(expected_version=1, source="def run(alert, cluster):\n return 'New'", output_mode="text")).status_code == 200
    versions = client.get(root + "/observe/versions").json()["items"]
    assert len(versions) == 1 and "observed" in versions[0]["source"]
    assert client.post(root + "/observe/publish").json()["revision"] == 2


def test_test_input_is_normalized_and_tenant_checked(setup, monkeypatch):
    client, mongo, _ = prepare(setup)
    root = "/api/v2/admin/python-tools/observe"
    client.put(root, json=value())
    transport = AsyncMock(return_value={"state": "PENDING"})
    monkeypatch.setattr(python_tools, "broker_request", transport)
    body = {"tenant_id": "one", "alert": {"tenant_id": "other"}}
    assert client.post(root + "/test", json=body).status_code == 422
    body["alert"] = {"tenant_id": "one", "alert_id": "a", "raw_payload": {"secret": "NEVER"}, "normalized_payload": {}}
    response = client.post(root + "/test", json=body)
    assert response.status_code == 202, response.text
    assert "NEVER" not in str(transport.call_args)


def test_grants_revocation_schema_errors_and_cancel_are_explicit(setup, monkeypatch):
    client, mongo, _ = prepare(setup)
    root = "/api/v2/admin/python-tools/observe"
    assert client.put(root, json=value(output_schema={"$ref": "https://example.test/schema"})).status_code == 422
    client.put(root, json=value())
    transport = AsyncMock(return_value={"state": "PENDING"})
    monkeypatch.setattr(python_tools, "broker_request", transport)
    body = {"tenant_id": "one", "alert": {"tenant_id": "one", "alert_id": "a", "normalized_payload": {}}}
    response = client.post(root + "/test", json=body)
    call = response.json()["call_id"]
    transport.return_value = {"state": "CANCELLED"}
    assert client.delete(root + "/tests/" + call).json()["state"] == "CANCELLED"
    assert transport.call_args.kwargs["cancel"] is True
    assert client.delete(root + "/tests/unknown").status_code == 404
    assert client.put(root, json=value(expected_version=1, enabled=False)).status_code == 200
    assert client.post(root + "/test", json=body).status_code == 404
