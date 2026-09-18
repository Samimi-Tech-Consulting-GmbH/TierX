import base64
import hashlib
import hmac
import json
import os
import time
from datetime import datetime, timezone
from uuid import uuid4

import pytest
import yaml as yaml_module
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi.testclient import TestClient

from main import app
from app.core.security import create_access_token
from app.services.webhook_signing_service import WebhookSigningService

from test_playbooks import MockDatabaseManager


client = TestClient(app)
MASTER_KEY = base64.urlsafe_b64encode(b"w" * 32).decode().rstrip("=")


def headers(role="PLATFORM_ADMIN", tenant_id=None):
    token = create_access_token(
        user_id="webhook-test",
        email="webhook@example.com",
        role=role,
        tenant_id=tenant_id,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def webhook_environment(monkeypatch):
    monkeypatch.setenv("WEBHOOK_SECRET_ENCRYPTION_KEY", MASTER_KEY)
    monkeypatch.setenv("PLAYBOOK_CONTEXT_WEBHOOKS_ENABLED", "true")
    monkeypatch.setattr(
        "app.services.webhook_signing_service.DatabaseManager", MockDatabaseManager
    )
    monkeypatch.setattr(
        "app.services.playbook_service.DatabaseManager", MockDatabaseManager
    )
    monkeypatch.setattr(
        "app.services.tenant_service.DatabaseManager", MockDatabaseManager
    )


@pytest.fixture
def tenant_and_playbook():
    tenant = client.post(
        "/api/v1/admin/tenants",
        json={"name": f"webhook-{uuid4().hex[:8]}", "display_name": "Webhook Test"},
        headers=headers(),
    ).json()
    yaml = b"""prompt: Analyze safely.
description: Signed context test.
alert_types: [endpoint.malware]
is_active: true
is_system: false
context_webhook:
  enabled: true
  url: https://customer.example/context
  timeout_seconds: 5
"""
    response = client.post(
        f"/api/v1/tenants/{tenant['tenant_id']}/playbooks",
        headers=headers(),
        data={"name": "Signed context"},
        files={"file": ("playbook.yaml", yaml, "application/x-yaml")},
    )
    assert response.status_code == 201, response.text
    return tenant, response.json()


def test_playbook_webhook_url_validation_and_compatibility(tenant_and_playbook):
    tenant, playbook = tenant_and_playbook
    assert playbook["context_webhook"]["timeout_seconds"] == 5
    legacy = b"""prompt: Legacy.
description: No webhook.
is_active: true
is_system: false
"""
    response = client.post(
        f"/api/v1/tenants/{tenant['tenant_id']}/playbooks",
        headers=headers(),
        data={"name": "Legacy"},
        files={"file": ("legacy.yaml", legacy, "application/x-yaml")},
    )
    assert response.status_code == 201
    assert response.json()["context_webhook"] is None

    invalid = b"""prompt: Bad.
description: Reject credentials and query.
is_active: true
is_system: false
context_webhook:
  enabled: true
  url: https://user:pass@example.com/context?token=no
"""
    response = client.post(
        f"/api/v1/tenants/{tenant['tenant_id']}/playbooks",
        headers=headers(),
        data={"name": "Invalid"},
        files={"file": ("bad.yaml", invalid, "application/x-yaml")},
    )
    assert response.status_code == 422


def test_multiple_context_providers_are_ordered_versioned_and_validated(
    tenant_and_playbook, monkeypatch
):
    tenant, _ = tenant_and_playbook
    tenant_id = tenant["tenant_id"]
    yaml = b"""prompt: Analyze with provider context.
description: Multiple signed context providers.
alert_types: [endpoint.malware]
is_active: true
is_system: false
context_webhooks:
  - webhook_id: threat-intel
    name: Threat intelligence
    enabled: true
    url: https://customer.example/threat
    timeout_seconds: 4
  - webhook_id: asset-context
    name: Asset context
    enabled: false
    url: https://customer.example/assets
    timeout_seconds: 2
"""
    created = client.post(
        f"/api/v1/tenants/{tenant_id}/playbooks",
        headers=headers(),
        data={"name": "Multiple providers"},
        files={"file": ("multiple.yaml", yaml, "application/x-yaml")},
    )
    assert created.status_code == 201, created.text
    playbook = created.json()
    assert playbook["context_webhook"] is None
    assert [item["webhook_id"] for item in playbook["context_webhooks"]] == [
        "threat-intel",
        "asset-context",
    ]

    replacement = {
        "playbook_name": playbook["playbook_name"],
        "prompt": playbook["prompt"],
        "description": playbook["description"],
        "alert_types": playbook["alert_types"],
        "is_active": playbook["is_active"],
        "is_system": playbook["is_system"],
        "actions": playbook["actions"],
        "context_webhooks": playbook["context_webhooks"],
    }
    revised = client.put(
        f"/api/v1/tenants/{tenant_id}/playbooks/{playbook['playbook_id']}",
        headers=headers(),
        json=replacement,
    )
    assert revised.status_code == 200, revised.text
    assert revised.json()["version"] == 2
    assert revised.json()["context_webhooks"] == playbook["context_webhooks"]
    listed = client.get(
        f"/api/v1/tenants/{tenant_id}/playbooks", headers=headers()
    ).json()
    listed_item = next(
        item for item in listed if item["playbook_id"] == playbook["playbook_id"]
    )
    assert listed_item["context_webhooks"] == playbook["context_webhooks"]
    versions = client.get(
        f"/api/v1/tenants/{tenant_id}/playbooks/{playbook['playbook_id']}/versions",
        headers=headers(),
    ).json()
    assert [version["version"] for version in versions] == [2, 1]
    assert all(version["context_webhooks"] for version in versions)

    invalid_documents = [
        yaml
        + b"""context_webhook:
  enabled: true
  url: https://customer.example/legacy
""",
        b"""prompt: Duplicate.
description: Duplicate IDs.
is_active: true
is_system: false
context_webhooks:
  - {webhook_id: duplicate, name: First, url: https://customer.example/one}
  - {webhook_id: duplicate, name: Second, url: https://customer.example/two}
""",
        b"""prompt: Invalid.
description: Invalid ID.
is_active: true
is_system: false
context_webhooks:
  - {webhook_id: Bad.ID, name: Invalid, url: https://customer.example/invalid}
""",
    ]
    for index, invalid in enumerate(invalid_documents):
        response = client.post(
            f"/api/v1/tenants/{tenant_id}/playbooks",
            headers=headers(),
            data={"name": f"Invalid multiple {index}"},
            files={"file": ("invalid.yaml", invalid, "application/x-yaml")},
        )
        assert response.status_code == 422, response.text

    too_many = {
        "prompt": "Too many.",
        "description": "Provider limit.",
        "is_active": True,
        "is_system": False,
        "context_webhooks": [
            {
                "webhook_id": f"provider-{index}",
                "name": f"Provider {index}",
                "url": f"https://customer.example/{index}",
            }
            for index in range(11)
        ],
    }
    response = client.post(
        f"/api/v1/tenants/{tenant_id}/playbooks",
        headers=headers(),
        data={"name": "Too many providers"},
        files={
            "file": (
                "too-many.yaml",
                yaml_module.safe_dump(too_many).encode(),
                "application/x-yaml",
            )
        },
    )
    assert response.status_code == 422

    monkeypatch.setenv("PLAYBOOK_WEBHOOK_MAX_COUNT", "1")
    response = client.post(
        f"/api/v1/tenants/{tenant_id}/playbooks",
        headers=headers(),
        data={"name": "Configured provider limit"},
        files={"file": ("limited.yaml", yaml, "application/x-yaml")},
    )
    assert response.status_code == 422


def test_copy_once_encryption_precedence_rotation_and_permissions(tenant_and_playbook):
    tenant, playbook = tenant_and_playbook
    tenant_id = tenant["tenant_id"]
    playbook_id = playbook["playbook_id"]
    tenant_headers = headers("TENANT_ADMIN", tenant_id)

    created = client.post(
        f"/api/v1/tenants/{tenant_id}/webhook-signing-secret",
        headers=tenant_headers,
    )
    assert created.status_code == 201
    first = created.json()
    assert first["secret"].startswith("whsec_")
    metadata = client.get(
        f"/api/v1/tenants/{tenant_id}/webhook-signing-secret",
        headers=tenant_headers,
    ).json()
    assert metadata["configured"] is True
    assert "secret" not in metadata

    collection = WebhookSigningService._collection(tenant_id)
    stored = collection.find_one({"key_id": first["key_id"]})
    assert stored["aad_namespace"] == "tierx"
    assert first["secret"] not in json.dumps(stored, default=str)
    assert (
        WebhookSigningService.resolve(tenant_id, playbook_id)["effective_scope"]
        == "TENANT"
    )

    legacy_secret = "whsec_legacy_credential"
    legacy_nonce = os.urandom(12)
    legacy_key_id = "whk_legacy"
    legacy_ciphertext = AESGCM(WebhookSigningService.encryption_key()).encrypt(
        legacy_nonce,
        legacy_secret.encode(),
        WebhookSigningService._aad(
            tenant_id, "TENANT", tenant_id, legacy_key_id, "soc-mind"
        ),
    )
    legacy_record = {
        "scope_type": "TENANT", "scope_id": tenant_id, "key_id": legacy_key_id,
        "nonce": base64.urlsafe_b64encode(legacy_nonce).decode().rstrip("="),
        "ciphertext": base64.urlsafe_b64encode(legacy_ciphertext).decode().rstrip("="),
    }
    assert WebhookSigningService.decrypt(tenant_id, legacy_record) == legacy_secret

    override = client.post(
        f"/api/v1/tenants/{tenant_id}/playbooks/{playbook_id}/webhook-signing-secret",
        headers=tenant_headers,
    ).json()
    assert (
        WebhookSigningService.resolve(tenant_id, playbook_id)["key_id"]
        == override["key_id"]
    )
    deleted = client.delete(
        f"/api/v1/tenants/{tenant_id}/playbooks/{playbook_id}/webhook-signing-secret",
        headers=tenant_headers,
    )
    assert deleted.status_code == 200
    assert (
        WebhookSigningService.resolve(tenant_id, playbook_id)["key_id"]
        == first["key_id"]
    )

    operator = headers("TENANT_OPERATOR", tenant_id)
    assert (
        client.get(
            f"/api/v1/tenants/{tenant_id}/webhook-signing-secret", headers=operator
        ).status_code
        == 403
    )
    other = headers("TENANT_ADMIN", str(uuid4()))
    assert (
        client.get(
            f"/api/v1/tenants/{tenant_id}/webhook-signing-secret", headers=other
        ).status_code
        == 403
    )


def test_reference_endpoint_hmac_timestamp_and_replay(tenant_and_playbook):
    tenant, playbook = tenant_and_playbook
    tenant_id = tenant["tenant_id"]
    created = client.post(
        f"/api/v1/tenants/{tenant_id}/webhook-signing-secret", headers=headers()
    ).json()
    delivery_id = str(uuid4())
    body = {
        "spec_version": "1.0",
        "delivery_id": delivery_id,
        "sent_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "tenant_id": tenant_id,
        "alert": {
            "alert_id": str(uuid4()),
            "alert_type": "endpoint.malware",
            "source_system": "splunk",
            "fingerprint": "a" * 64,
            "normalized_payload": {"host": {"hostname": "host-17"}},
        },
        "playbook": {"playbook_id": playbook["playbook_id"], "version": 1},
        "release": {"version": "0.1.7", "sha": "b" * 40},
    }
    raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    timestamp = str(int(time.time()))
    digest = hmac.new(
        created["secret"].encode(),
        timestamp.encode() + b"." + delivery_id.encode() + b"." + raw,
        hashlib.sha256,
    ).hexdigest()
    signature_headers = {
        "Content-Type": "application/json",
        "X-TierX-Webhook-Version": "1",
        "X-TierX-Delivery-ID": delivery_id,
        "X-TierX-Timestamp": timestamp,
        "X-TierX-Key-ID": created["key_id"],
        "X-TierX-Signature": f"v1={digest}",
    }
    first = client.post(
        "/api/v1/examples/playbook-context-webhook",
        content=raw,
        headers=signature_headers,
    )
    assert first.status_code == 200, first.text
    assert "host.hostname=host-17" in first.json()["prompt_footer"]
    replay = client.post(
        "/api/v1/examples/playbook-context-webhook",
        content=raw,
        headers=signature_headers,
    )
    assert replay.json() == first.json()

    bad = {**signature_headers, "X-TierX-Signature": "v1=" + "0" * 64}
    assert (
        client.post(
            "/api/v1/examples/playbook-context-webhook", content=raw, headers=bad
        ).status_code
        == 401
    )
    expired = {**signature_headers, "X-TierX-Timestamp": str(int(time.time()) - 301)}
    assert (
        client.post(
            "/api/v1/examples/playbook-context-webhook", content=raw, headers=expired
        ).status_code
        == 401
    )
