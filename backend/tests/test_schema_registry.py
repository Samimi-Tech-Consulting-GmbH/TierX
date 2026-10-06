import pytest
import mongomock
import mongoengine
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


VALID_SCHEMA_YAML = """
alert_type: splunk.notable.endpoint_malware
version: "1.0.0"
description: Test schema for registry
field_mapping:
  host.hostname: result.host
  source.ip: result.src
critical_fields:
  - host.hostname
  - source.ip
severity: "5"
"""

SCHEMA_YAML_V2 = """
alert_type: splunk.notable.endpoint_malware
version: "1.1.0"
description: Second version
field_mapping:
  host.hostname: result.host
critical_fields:
  - host.hostname
"""


@pytest.fixture(autouse=True)
def mock_mongo(monkeypatch):
    monkeypatch.setattr(app.db.mongodb, "DatabaseManager", MockDatabaseManager)
    monkeypatch.setattr(app.services.tenant_service, "DatabaseManager", MockDatabaseManager)
    monkeypatch.setattr(app.services.playbook_service, "DatabaseManager", MockDatabaseManager)
    monkeypatch.setattr(
        app.services.alert_type_schema_service, "DatabaseManager", MockDatabaseManager
    )
    yield


@pytest.fixture(autouse=True)
def clean_db(mock_mongo):
    from app.models.tenant import Tenant
    from app.models.user import User
    from app.models.alert_type_schema import AlertTypeSchema
    from mongoengine.context_managers import switch_db
    from app.db.mongodb import DatabaseManager

    for t in Tenant.objects:
        alias = DatabaseManager.get_tenant_db_alias(t.db_name)
        with switch_db(Playbook, alias) as TP:
            TP.drop_collection()
        with switch_db(AlertTypeSchema, alias) as TAS:
            TAS.drop_collection()
    Tenant.drop_collection()
    User.drop_collection()
    yield


@pytest.fixture
def sample_tenant():
    r = client.post(
        "/api/v1/admin/tenants",
        json={"name": "schema-demo", "display_name": "Schema Demo"},
        headers=get_platform_headers(),
    )
    assert r.status_code == 201
    return r.json()


def test_create_draft_list_get_activate(sample_tenant):
    tid = sample_tenant["tenant_id"]
    r = client.post(
        f"/api/v1/tenants/{tid}/schema-registry",
        headers=get_platform_headers(),
        files={"file": ("schema.yaml", VALID_SCHEMA_YAML.encode(), "application/x-yaml")},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["is_active"] is False
    assert body["tenant_id"] == tid
    assert len(body["schema_id"]) == 36
    sid = body["schema_id"]
    alert_type = body["alert_type"]

    listed = client.get(f"/api/v1/tenants/{tid}/schema-registry", headers=ta_headers(tid))
    assert listed.status_code == 200
    pack = listed.json()
    assert pack["total"] == 1
    assert pack["items"][0]["schema_id"] == sid

    active_missing = client.get(
        f"/api/v1/tenants/{tid}/schema-registry/{alert_type}",
        headers=ta_headers(tid),
    )
    assert active_missing.status_code == 404

    act = client.post(
        f"/api/v1/tenants/{tid}/schema-registry/{alert_type}/{sid}/activate",
        headers=get_platform_headers(),
    )
    assert act.status_code == 200
    assert act.json()["is_active"] is True

    active = client.get(
        f"/api/v1/tenants/{tid}/schema-registry/{alert_type}",
        headers=ta_headers(tid),
    )
    assert active.status_code == 200
    assert active.json()["schema_id"] == sid

    hist = client.get(
        f"/api/v1/tenants/{tid}/schema-registry/{alert_type}/history",
        headers=ta_headers(tid),
    )
    assert hist.status_code == 200
    assert len(hist.json()) == 1


def test_duplicate_version_conflict(sample_tenant):
    tid = sample_tenant["tenant_id"]
    first = client.post(
        f"/api/v1/tenants/{tid}/schema-registry",
        headers=get_platform_headers(),
        files={"file": ("s.yaml", VALID_SCHEMA_YAML.encode(), "application/x-yaml")},
    )
    assert first.status_code == 201
    dup = client.post(
        f"/api/v1/tenants/{tid}/schema-registry",
        headers=get_platform_headers(),
        files={"file": ("s.yaml", VALID_SCHEMA_YAML.encode(), "application/x-yaml")},
    )
    assert dup.status_code == 409


def test_activate_replaces_active(sample_tenant):
    tid = sample_tenant["tenant_id"]
    a = client.post(
        f"/api/v1/tenants/{tid}/schema-registry",
        headers=get_platform_headers(),
        files={"file": ("a.yaml", VALID_SCHEMA_YAML.encode(), "application/x-yaml")},
    ).json()
    b = client.post(
        f"/api/v1/tenants/{tid}/schema-registry",
        headers=get_platform_headers(),
        files={"file": ("b.yaml", SCHEMA_YAML_V2.encode(), "application/x-yaml")},
    ).json()
    alert_type = a["alert_type"]
    client.post(
        f"/api/v1/tenants/{tid}/schema-registry/{alert_type}/{a['schema_id']}/activate",
        headers=get_platform_headers(),
    )
    client.post(
        f"/api/v1/tenants/{tid}/schema-registry/{alert_type}/{b['schema_id']}/activate",
        headers=get_platform_headers(),
    )
    active = client.get(
        f"/api/v1/tenants/{tid}/schema-registry/{alert_type}",
        headers=get_platform_headers(),
    ).json()
    assert active["schema_id"] == b["schema_id"]
    assert active["version"] == "1.1.0"


def test_incomplete_draft_cannot_replace_active_schema(sample_tenant):
    tid = sample_tenant["tenant_id"]
    base = f"/api/v1/tenants/{tid}/schema-registry"
    headers = get_platform_headers()
    valid = client.post(base, headers=headers, files={
        "file": ("valid.yaml", VALID_SCHEMA_YAML.encode(), "application/x-yaml")
    }).json()
    active_url = f"{base}/{valid['alert_type']}/{valid['schema_id']}/activate"
    assert client.post(active_url, headers=headers).status_code == 200
    invalid = SCHEMA_YAML_V2.replace("host.hostname: result.host", "result.host: host.hostname")
    draft_response = client.post(base, headers=headers, files={
        "file": ("draft.yaml", invalid.encode(), "application/x-yaml")
    })
    assert draft_response.status_code == 201
    draft = draft_response.json()
    response = client.post(
        f"{base}/{draft['alert_type']}/{draft['schema_id']}/activate", headers=headers
    )
    assert response.status_code == 422
    assert "host.hostname" in response.text
    assert "source mapping" in response.text
    active = client.get(f"{base}/{valid['alert_type']}", headers=headers).json()
    assert active["schema_id"] == valid["schema_id"]


def test_yaml_validation_error(sample_tenant):
    tid = sample_tenant["tenant_id"]
    bad = "not: [ broken"
    r = client.post(
        f"/api/v1/tenants/{tid}/schema-registry",
        headers=get_platform_headers(),
        files={"file": ("bad.yaml", bad.encode(), "application/x-yaml")},
    )
    assert r.status_code == 422


def test_put_returns_405(sample_tenant):
    tid = sample_tenant["tenant_id"]
    body = client.post(
        f"/api/v1/tenants/{tid}/schema-registry",
        headers=get_platform_headers(),
        files={"file": ("s.yaml", VALID_SCHEMA_YAML.encode(), "application/x-yaml")},
    ).json()
    r = client.put(
        f"/api/v1/tenants/{tid}/schema-registry/{body['alert_type']}/{body['schema_id']}",
        headers=get_platform_headers(),
    )
    assert r.status_code == 405


def test_operator_cannot_create(sample_tenant):
    tid = sample_tenant["tenant_id"]
    tok = create_access_token(
        user_id="op",
        email="op@example.com",
        role="TENANT_OPERATOR",
        tenant_id=tid,
    )
    r = client.post(
        f"/api/v1/tenants/{tid}/schema-registry",
        headers={"Authorization": f"Bearer {tok}"},
        files={"file": ("s.yaml", VALID_SCHEMA_YAML.encode(), "application/x-yaml")},
    )
    assert r.status_code == 403


def test_unknown_playbook_id(sample_tenant):
    tid = sample_tenant["tenant_id"]
    r = client.post(
        f"/api/v1/tenants/{tid}/schema-registry",
        headers=get_platform_headers(),
        data={"playbook_id": "00000000-0000-0000-0000-000000000099"},
        files={"file": ("s.yaml", VALID_SCHEMA_YAML.encode(), "application/x-yaml")},
    )
    assert r.status_code == 422


SCHEMA_YAML_OTHER = """
alert_type: corp.email.PHISHING_RULE
version: "1.0.0"
description: Other type
field_mapping:
  email.subject: subj
critical_fields:
  - email.subject
"""


def test_list_free_text_search_and_is_active_filter(sample_tenant):
    tid = sample_tenant["tenant_id"]
    assert (
        client.post(
            f"/api/v1/tenants/{tid}/schema-registry",
            headers=get_platform_headers(),
            files={"file": ("a.yaml", VALID_SCHEMA_YAML.encode(), "application/x-yaml")},
        ).status_code
        == 201
    )
    assert (
        client.post(
            f"/api/v1/tenants/{tid}/schema-registry",
            headers=get_platform_headers(),
            files={"file": ("b.yaml", SCHEMA_YAML_OTHER.encode(), "application/x-yaml")},
        ).status_code
        == 201
    )
    r_phish = client.get(
        f"/api/v1/tenants/{tid}/schema-registry?q=PHISHING",
        headers=get_platform_headers(),
    )
    assert r_phish.status_code == 200
    assert r_phish.json()["total"] == 1
    assert "PHISHING" in r_phish.json()["items"][0]["alert_type"]

    r_mal = client.get(
        f"/api/v1/tenants/{tid}/schema-registry?q=malware",
        headers=get_platform_headers(),
    )
    assert r_mal.json()["total"] == 1
    assert "malware" in r_mal.json()["items"][0]["alert_type"].lower()

    r_draft = client.get(
        f"/api/v1/tenants/{tid}/schema-registry?is_active=false",
        headers=get_platform_headers(),
    )
    assert r_draft.json()["total"] == 2

    r_active = client.get(
        f"/api/v1/tenants/{tid}/schema-registry?is_active=true",
        headers=get_platform_headers(),
    )
    assert r_active.json()["total"] == 0


def test_get_schema_by_id(sample_tenant):
    tid = sample_tenant["tenant_id"]
    body = client.post(
        f"/api/v1/tenants/{tid}/schema-registry",
        headers=get_platform_headers(),
        files={"file": ("s.yaml", VALID_SCHEMA_YAML.encode(), "application/x-yaml")},
    ).json()
    sid = body["schema_id"]
    r = client.get(
        f"/api/v1/tenants/{tid}/schema-registry/by-id/{sid}",
        headers=get_platform_headers(),
    )
    assert r.status_code == 200
    assert r.json()["schema_id"] == sid
    assert r.json()["alert_type"] == body["alert_type"]


def test_get_schema_by_id_not_found(sample_tenant):
    tid = sample_tenant["tenant_id"]
    r = client.get(
        f"/api/v1/tenants/{tid}/schema-registry/by-id/00000000-0000-0000-0000-000000000001",
        headers=get_platform_headers(),
    )
    assert r.status_code == 404


DUPLICATE_ECS_KEY_YAML = """
alert_type: splunk.notable.endpoint_malware
version: "1.0.0"
field_mapping:
  host.hostname: result.host
  source.ip: result.src
  host.hostname: result.computer_name
critical_fields:
  - host.hostname
"""


def test_duplicate_ecs_key_in_field_mapping_rejected(sample_tenant):
    tid = sample_tenant["tenant_id"]
    r = client.post(
        f"/api/v1/tenants/{tid}/schema-registry",
        headers=get_platform_headers(),
        files={"file": ("dup.yaml", DUPLICATE_ECS_KEY_YAML.encode(), "application/x-yaml")},
    )
    assert r.status_code == 422
    body = r.json()
    errs = body["detail"]["errors"]
    assert any(
        e["type"] == "duplicate_key" and "host.hostname" in e["msg"] for e in errs
    ), errs


DUPLICATE_SOURCE_PATH_YAML = """
alert_type: splunk.notable.endpoint_malware
version: "1.0.0"
field_mapping:
  host.hostname: result.host
  host.name: result.host
  source.ip: result.src
critical_fields:
  - host.hostname
"""


def test_duplicate_source_path_in_field_mapping_rejected(sample_tenant):
    tid = sample_tenant["tenant_id"]
    r = client.post(
        f"/api/v1/tenants/{tid}/schema-registry",
        headers=get_platform_headers(),
        files={
            "file": (
                "dup-source.yaml",
                DUPLICATE_SOURCE_PATH_YAML.encode(),
                "application/x-yaml",
            )
        },
    )
    assert r.status_code == 422
    body = r.json()
    errs = body["detail"]["errors"]
    assert any(
        "same source path mapped to multiple ECS" in e["msg"]
        and "result.host" in e["msg"]
        and "host.hostname" in e["msg"]
        and "host.name" in e["msg"]
        for e in errs
    ), errs
