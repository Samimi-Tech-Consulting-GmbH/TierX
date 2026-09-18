import base64
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from main import app
from app.core.security import create_access_token
from test_playbooks import MockDatabaseManager

client = TestClient(app)
MASTER_KEY = base64.urlsafe_b64encode(b"a" * 32).decode().rstrip("=")


def headers(role="PLATFORM_ADMIN", tenant_id=None):
    token = create_access_token(
        user_id="action-test",
        email="action-test@example.com",
        role=role,
        tenant_id=tenant_id,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def environment(monkeypatch):
    monkeypatch.setenv("WEBHOOK_SECRET_ENCRYPTION_KEY", MASTER_KEY)
    monkeypatch.setattr(
        "app.services.enrichment_action_service.DatabaseManager", MockDatabaseManager
    )
    monkeypatch.setattr("app.services.tenant_service.DatabaseManager", MockDatabaseManager)
    monkeypatch.setattr("app.services.playbook_service.DatabaseManager", MockDatabaseManager)
    MockDatabaseManager.get_tenant_database("soc_mind_platform")[
        "enrichment_actions"
    ].delete_many({})


def create_tenant():
    response = client.post(
        "/api/v1/admin/tenants",
        json={
            "name": f"action-{uuid4().hex[:8]}",
            "display_name": "Action Tenant",
        },
        headers=headers(),
    )
    assert response.status_code == 201, response.text
    return response.json()


def action_payload(**values):
    return {
        "action_code": values.pop("action_code", f"observe-{uuid4().hex[:8]}"),
        "name": "Deterministic observer",
        "description": "Returns safe normalized evidence.",
        "url": "https://provider.example/action",
        "timeout_seconds": 300,
        "enabled": True,
        "tenant_scope": "ALL_TENANTS",
        "tenant_ids": [],
        **values,
    }


def test_platform_admin_lifecycle_copy_once_and_redaction():
    payload = action_payload()
    forbidden = client.post(
        "/api/v1/admin/enrichment-actions",
        json=payload,
        headers=headers("TENANT_ADMIN", "tenant-1"),
    )
    assert forbidden.status_code == 403

    created = client.post(
        "/api/v1/admin/enrichment-actions",
        json=payload,
        headers=headers(),
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["secret"].startswith("easec_")
    assert body["timeout_seconds"] == 300
    stored = MockDatabaseManager.get_tenant_database("soc_mind_platform")[
        "enrichment_actions"
    ].find_one({"action_code": payload["action_code"]})
    assert stored["ciphertext"]
    assert stored["aad_namespace"] == "tierx"
    assert body["secret"] not in str(stored)

    listed = client.get(
        "/api/v1/admin/enrichment-actions", headers=headers()
    ).json()
    assert listed["total"] == 1
    assert "secret" not in listed["items"][0]
    assert "ciphertext" not in listed["items"][0]
    assert "nonce" not in listed["items"][0]

    rotated = client.post(
        f"/api/v1/admin/enrichment-actions/{payload['action_code']}/rotate",
        headers=headers(),
    )
    assert rotated.status_code == 200
    assert rotated.json()["secret"] != body["secret"]
    assert rotated.json()["key_id"] != body["key_id"]
    checksum_before_delete = rotated.json()["configuration_checksum"]

    immutable = client.put(
        f"/api/v1/admin/enrichment-actions/{payload['action_code']}",
        json={**payload, "action_code": "replacement-code"},
        headers=headers(),
    )
    assert immutable.status_code == 422

    deleted = client.delete(
        f"/api/v1/admin/enrichment-actions/{payload['action_code']}",
        headers=headers(),
    )
    assert deleted.status_code == 200
    assert deleted.json()["enabled"] is False
    assert deleted.json()["configuration_checksum"] != checksum_before_delete
    assert client.get(
        f"/api/v1/admin/enrichment-actions/{payload['action_code']}",
        headers=headers(),
    ).status_code == 404


def test_selected_tenant_catalog_and_playbook_validation():
    tenant = create_tenant()
    tenant_id = tenant["tenant_id"]
    payload = action_payload(
        tenant_scope="SELECTED_TENANTS", tenant_ids=[tenant_id]
    )
    created = client.post(
        "/api/v1/admin/enrichment-actions",
        json=payload,
        headers=headers(),
    )
    assert created.status_code == 201, created.text

    catalog = client.get(
        f"/api/v1/tenants/{tenant_id}/enrichment-actions",
        headers=headers("TENANT_ADMIN", tenant_id),
    )
    assert [item["action_code"] for item in catalog.json()] == [payload["action_code"]]

    other = create_tenant()
    other_catalog = client.get(
        f"/api/v1/tenants/{other['tenant_id']}/enrichment-actions",
        headers=headers("TENANT_ADMIN", other["tenant_id"]),
    )
    assert other_catalog.json() == []

    yaml = f"""prompt: Analyze safely.
description: Managed action test.
alert_types: [endpoint.malware]
enrichment_actions: [{payload['action_code']}]
is_active: true
is_system: false
"""
    playbook = client.post(
        f"/api/v1/tenants/{tenant_id}/playbooks",
        headers=headers("TENANT_ADMIN", tenant_id),
        data={"name": "Managed action"},
        files={"file": ("playbook.yaml", yaml.encode(), "application/x-yaml")},
    )
    assert playbook.status_code == 201, playbook.text
    assert playbook.json()["enrichment_actions"] == [payload["action_code"]]


@pytest.mark.parametrize("timeout", [1, 300, 1800])
def test_timeout_boundaries(timeout):
    response = client.post(
        "/api/v1/admin/enrichment-actions",
        json=action_payload(timeout_seconds=timeout),
        headers=headers(),
    )
    assert response.status_code == 201, response.text


@pytest.mark.parametrize("timeout", [0, 1801])
def test_timeout_outside_contract_is_rejected(timeout):
    response = client.post(
        "/api/v1/admin/enrichment-actions",
        json=action_payload(timeout_seconds=timeout),
        headers=headers(),
    )
    assert response.status_code == 422


def test_url_and_scope_validation():
    for payload in (
        action_payload(url="http://provider.example/action"),
        action_payload(url="https://user:password@provider.example/action"),
        action_payload(url="https://127.0.0.1/action"),
        action_payload(tenant_scope="SELECTED_TENANTS", tenant_ids=[]),
    ):
        response = client.post(
            "/api/v1/admin/enrichment-actions",
            json=payload,
            headers=headers(),
        )
        assert response.status_code == 422
