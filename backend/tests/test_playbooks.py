import pytest
import mongomock
import mongoengine
from datetime import datetime, timezone
from fastapi.testclient import TestClient

from main import app
from app.core.security import create_access_token
from app.models.playbook import Playbook

client = TestClient(app)

mongoengine.disconnect_all()
mongoengine.connect(
    "soc_mind_platform",
    host="mongodb://root:example@mongodb:27017/",
    mongo_client_class=mongomock.MongoClient,
    alias="default",
    uuidRepresentation="standard",
)

import app.db.mongodb
import app.services.tenant_service


class MockDatabaseManager:
    @staticmethod
    def initialize():
        pass

    @staticmethod
    def get_tenant_db_alias(db_name: str) -> str:
        alias = f"tenant_{db_name}"
        if alias not in mongoengine.connection._connections:
            mongoengine.connect(
                db_name,
                host="mongodb://root:example@mongodb:27017/",
                mongo_client_class=mongomock.MongoClient,
                alias=alias,
                uuidRepresentation="standard",
            )
        return alias

    @staticmethod
    def get_tenant_database(db_name: str):
        alias = MockDatabaseManager.get_tenant_db_alias(db_name)
        return mongoengine.connection.get_db(alias)


def get_platform_headers() -> dict:
    tok = create_access_token(
        user_id="p-admin",
        email="admin@example.com",
        role="PLATFORM_ADMIN",
        tenant_id=None,
    )
    return {"Authorization": f"Bearer {tok}"}


def ta_headers(tenant_id: str) -> dict:
    tok = create_access_token(
        user_id="ta-1",
        email="ta@example.com",
        role="TENANT_ADMIN",
        tenant_id=tenant_id,
    )
    return {"Authorization": f"Bearer {tok}"}


def op_headers(tenant_id: str) -> dict:
    tok = create_access_token(
        user_id="op-1",
        email="op@example.com",
        role="TENANT_OPERATOR",
        tenant_id=tenant_id,
    )
    return {"Authorization": f"Bearer {tok}"}


# 3.18 / 3.19 — YAML supplies all fields except playbook_name (form) and server identity.
VALID_YAML = """
actions:
  - name: Splunk context
    adapter: SPLUNK_SPL
    query_template: 'search index=alerts earliest=-24h'
    query_input_fields:
      - alert_id
    time: "2026-05-05T12:00:00+00:00"
    result: splunk_raw
prompt: Analyze the following alert context and propose next steps.
description: Phishing triage using Splunk SPL.
alert_types:
  - PHISHING
is_active: true
is_system: false
"""


@pytest.fixture(autouse=True)
def mock_mongo(monkeypatch):
    monkeypatch.setattr(app.db.mongodb, "DatabaseManager", MockDatabaseManager)
    monkeypatch.setattr(app.services.tenant_service, "DatabaseManager", MockDatabaseManager)
    monkeypatch.setattr(app.services.playbook_service, "DatabaseManager", MockDatabaseManager)
    yield


@pytest.fixture(autouse=True)
def clean_db(mock_mongo):
    from app.models.tenant import Tenant
    from app.models.user import User
    from mongoengine.context_managers import switch_db
    from app.db.mongodb import DatabaseManager

    for t in Tenant.objects:
        alias = DatabaseManager.get_tenant_db_alias(t.db_name)
        with switch_db(Playbook, alias) as TP:
            TP.drop_collection()
    Tenant.drop_collection()
    User.drop_collection()
    yield


@pytest.fixture
def sample_tenant():
    r = client.post(
        "/api/v1/admin/tenants",
        json={"name": "pb-demo", "display_name": "PB Demo"},
        headers=get_platform_headers(),
    )
    assert r.status_code == 201
    return r.json()


def test_create_list_get_playbook(sample_tenant):
    tid = sample_tenant["tenant_id"]
    r = client.post(
        f"/api/v1/tenants/{tid}/playbooks",
        headers=get_platform_headers(),
        data={"name": "Phishing runbook"},
        files={"file": ("runbook.yaml", VALID_YAML.encode(), "application/x-yaml")},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["playbook_name"] == "Phishing runbook"
    assert body["version"] == 1
    assert body["tenant_id"] == tid
    assert body["alert_types"] == ["PHISHING"]
    assert len(body["actions"]) == 1
    assert body["actions"][0]["adapter"] == "SPLUNK_SPL"
    assert body["is_system"] is False
    assert "prompt" in body
    pid = body["playbook_id"]

    listed = client.get(
        f"/api/v1/tenants/{tid}/playbooks?alert_type=PHISHING",
        headers=get_platform_headers(),
    )
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["playbook_id"] == pid
    assert listed.json()[0]["playbook_name"] == "Phishing runbook"
    assert listed.json()[0]["version"] == 1

    one = client.get(
        f"/api/v1/tenants/{tid}/playbooks/{pid}",
        headers=op_headers(tid),
    )
    assert one.status_code == 200
    assert one.json()["actions"][0]["name"] == "Splunk context"


def test_playbook_stats_count_only_latest_logical_revision(sample_tenant):
    from app.models.tenant import Tenant

    tenant_id = sample_tenant["tenant_id"]
    tenant = Tenant.objects(tenant_id=tenant_id).first()
    assert tenant is not None
    db = MockDatabaseManager.get_tenant_database(str(tenant.db_name))
    now = datetime.now(timezone.utc)
    common = {
        "tenant_id": tenant_id,
        "actions": [],
        "prompt": "Analyze",
        "description": "Test",
        "created_by": "test@example.com",
        "created_at": now,
        "updated_at": now,
    }
    db.playbooks.insert_many(
        [
            {
                **common,
                "playbook_id": "playbook-1",
                "playbook_name": "First v1",
                "version": 1,
                "alert_types": ["OLD.TYPE"],
                "is_active": True,
                "is_system": False,
            },
            {
                **common,
                "playbook_id": "playbook-1",
                "playbook_name": "First v2",
                "version": 2,
                "alert_types": ["CURRENT.TYPE"],
                "is_active": False,
                "is_system": True,
            },
            {
                **common,
                "playbook_id": "playbook-2",
                "playbook_name": "Second",
                "version": 1,
                "alert_types": ["CURRENT.TYPE", "SECOND.TYPE"],
                "is_active": True,
                "is_system": False,
            },
        ]
    )

    response = client.get(
        f"/api/v1/tenants/{tenant_id}/playbooks/stats",
        headers=op_headers(tenant_id),
    )

    assert response.status_code == 200
    assert response.json() == {
        "total_playbooks": 2,
        "active_playbooks": 1,
        "system_playbooks": 1,
        "covered_alert_types": 2,
    }


MINIMAL_PLAYBOOK_YAML = """
prompt: Instructions only.
description: No actions nor alert_types in this YAML.
is_active: true
is_system: false
"""


def test_create_optional_actions_and_alert_types(sample_tenant):
    tid = sample_tenant["tenant_id"]
    r = client.post(
        f"/api/v1/tenants/{tid}/playbooks",
        headers=get_platform_headers(),
        data={"name": "Bare"},
        files={
            "file": (
                "bare.yaml",
                MINIMAL_PLAYBOOK_YAML.strip().encode(),
                "application/x-yaml",
            )
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["actions"] == []
    assert body["alert_types"] == []


def test_operator_cannot_create(sample_tenant):
    tid = sample_tenant["tenant_id"]
    r = client.post(
        f"/api/v1/tenants/{tid}/playbooks",
        headers=op_headers(tid),
        data={"name": "X"},
        files={"file": ("x.yaml", VALID_YAML.encode(), "application/x-yaml")},
    )
    assert r.status_code == 403


def test_yaml_validation_errors(sample_tenant):
    tid = sample_tenant["tenant_id"]
    bad = "alert_types:\n  - PHISHING\nis_active: true\nis_system: false\n"
    r = client.post(
        f"/api/v1/tenants/{tid}/playbooks",
        headers=get_platform_headers(),
        data={"name": "Bad"},
        files={"file": ("bad.yaml", bad.encode(), "application/x-yaml")},
    )
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert "errors" in detail
    assert len(detail["errors"]) >= 1


def test_wrong_tenant_returns_404(sample_tenant):
    tid = sample_tenant["tenant_id"]
    r = client.post(
        f"/api/v1/tenants/{tid}/playbooks",
        headers=get_platform_headers(),
        data={"name": "A"},
        files={"file": ("a.yaml", VALID_YAML.encode(), "application/x-yaml")},
    )
    pid = r.json()["playbook_id"]
    other = "00000000-0000-0000-0000-000000000099"
    r2 = client.get(
        f"/api/v1/tenants/{other}/playbooks/{pid}",
        headers=get_platform_headers(),
    )
    assert r2.status_code == 404


def test_put_replace(sample_tenant):
    tid = sample_tenant["tenant_id"]
    r = client.post(
        f"/api/v1/tenants/{tid}/playbooks",
        headers=ta_headers(tid),
        data={"name": "V"},
        files={"file": ("v.yaml", VALID_YAML.encode(), "application/x-yaml")},
    )
    pid = r.json()["playbook_id"]

    ok = client.put(
        f"/api/v1/tenants/{tid}/playbooks/{pid}",
        headers=ta_headers(tid),
        json={
            "playbook_name": "V2",
            "prompt": "Updated prompt",
            "description": "Updated description",
            "alert_types": ["PHISHING", "BEC"],
            "is_active": True,
            "is_system": True,
            "actions": [
                {
                    "name": "HTTP enrich",
                    "adapter": "GENERIC_HTTP",
                    "query_template": "GET /api/v1/events/{id}",
                    "query_input_fields": ["id"],
                    "time": "2026-05-06T10:00:00+00:00",
                    "result": "http_json",
                }
            ],
        },
    )
    assert ok.status_code == 200
    data = ok.json()
    assert data["playbook_name"] == "V2"
    assert data["version"] == 2
    assert data["is_system"] is True
    assert data["alert_types"] == ["PHISHING", "BEC"]
    assert data["actions"][0]["adapter"] == "GENERIC_HTTP"

    listed = client.get(
        f"/api/v1/tenants/{tid}/playbooks",
        headers=ta_headers(tid),
    )
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["version"] == 2

    vers = client.get(
        f"/api/v1/tenants/{tid}/playbooks/{pid}/versions",
        headers=ta_headers(tid),
    )
    assert vers.status_code == 200
    assert len(vers.json()) == 2
    assert vers.json()[0]["version"] == 2
    assert vers.json()[1]["version"] == 1


def test_put_yaml_appends_revision(sample_tenant):
    tid = sample_tenant["tenant_id"]
    r = client.post(
        f"/api/v1/tenants/{tid}/playbooks",
        headers=get_platform_headers(),
        data={"name": "Yaml rev"},
        files={"file": ("v.yaml", VALID_YAML.encode(), "application/x-yaml")},
    )
    assert r.status_code == 201
    pid = r.json()["playbook_id"]
    yaml_v2 = VALID_YAML.replace(
        "prompt: Analyze the following alert context and propose next steps.",
        "prompt: Second revision.",
    )
    up = client.put(
        f"/api/v1/tenants/{tid}/playbooks/{pid}/yaml",
        headers=get_platform_headers(),
        data={"name": "Yaml rev"},
        files={"file": ("v2.yaml", yaml_v2.encode(), "application/x-yaml")},
    )
    assert up.status_code == 200
    assert up.json()["version"] == 2
    assert up.json()["prompt"] == "Second revision."


def test_soft_delete(sample_tenant):
    tid = sample_tenant["tenant_id"]
    r = client.post(
        f"/api/v1/tenants/{tid}/playbooks",
        headers=get_platform_headers(),
        data={"name": "Del"},
        files={"file": ("d.yaml", VALID_YAML.encode(), "application/x-yaml")},
    )
    pid = r.json()["playbook_id"]
    d = client.delete(
        f"/api/v1/tenants/{tid}/playbooks/{pid}",
        headers=get_platform_headers(),
    )
    assert d.status_code == 200
    assert d.json()["is_active"] is False


def test_yaml_revision_succeeds_after_legacy_playbook_id_unique_index(sample_tenant):
    """Simulates DBs created before versioning: unique on playbook_id blocked v2 inserts."""
    from app.models.tenant import Tenant

    tid = sample_tenant["tenant_id"]
    r = client.post(
        f"/api/v1/tenants/{tid}/playbooks",
        headers=get_platform_headers(),
        data={"name": "Legacy idx"},
        files={"file": ("v.yaml", VALID_YAML.encode(), "application/x-yaml")},
    )
    assert r.status_code == 201
    pid = r.json()["playbook_id"]

    tenant = Tenant.objects(tenant_id=tid).first()
    assert tenant is not None
    db = mongoengine.connection.get_db(f"tenant_{tenant.db_name}")
    db["playbooks"].create_index(
        [("playbook_id", 1)],
        unique=True,
        name="legacy_unique_playbook_id_test",
    )

    yaml_v2 = VALID_YAML.replace(
        "prompt: Analyze the following alert context and propose next steps.",
        "prompt: Second.",
    )
    up = client.put(
        f"/api/v1/tenants/{tid}/playbooks/{pid}/yaml",
        headers=get_platform_headers(),
        data={"name": "Legacy idx"},
        files={"file": ("v2.yaml", yaml_v2.encode(), "application/x-yaml")},
    )
    assert up.status_code == 200, up.text
    assert up.json()["version"] == 2


def test_invalid_adapter_rejected(sample_tenant):
    tid = sample_tenant["tenant_id"]
    bad_yaml = VALID_YAML.replace("SPLUNK_SPL", "UNKNOWN_ADAPTER")
    r = client.post(
        f"/api/v1/tenants/{tid}/playbooks",
        headers=get_platform_headers(),
        data={"name": "Bad adapter"},
        files={"file": ("bad.yaml", bad_yaml.encode(), "application/x-yaml")},
    )
    assert r.status_code == 422
