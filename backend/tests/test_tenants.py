import pytest
import mongomock
import mongoengine
from datetime import datetime, timezone
from fastapi.testclient import TestClient

from main import app
from app.core.tenant_resolver import tenant_resolver
from app.core.security import create_access_token
from app.schemas.tenant import TenantCreate
from app.services.tenant_service import TenantService

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


def get_admin_token() -> str:
    return create_access_token(
        user_id="test-admin-id",
        email="admin@example.com",
        role="PLATFORM_ADMIN",
        tenant_id=None,
    )


def get_auth_headers() -> dict:
    return {"Authorization": f"Bearer {get_admin_token()}"}


@pytest.fixture(autouse=True)
def mock_mongo(monkeypatch):
    monkeypatch.setattr(app.db.mongodb, "DatabaseManager", MockDatabaseManager)
    monkeypatch.setattr(app.services.tenant_service, "DatabaseManager", MockDatabaseManager)
    yield


@pytest.fixture(autouse=True)
def clean_db(mock_mongo):
    from app.models.tenant import Tenant
    from app.models.user import User

    Tenant.drop_collection()
    User.drop_collection()
    tenant_resolver._status_cache.clear()
    yield


def test_health_check():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["release_version"]
    assert response.json()["release_sha"]


def test_unauthenticated_request_rejected():
    response = client.post("/api/v1/admin/tenants", json={"name": "x", "display_name": "X"})
    assert response.status_code in (401, 403)


def test_invalid_token_rejected():
    headers = {"Authorization": "Bearer invalid-token"}
    response = client.get("/api/v1/admin/tenants", headers=headers)
    assert response.status_code == 401


def test_tenant_creation():
    headers = get_auth_headers()
    tenant_data = {
        "name": "test-org-1",
        "display_name": "Test Organization 1",
        "allowed_source_systems": ["SPLUNK"],
    }

    response = client.post("/api/v1/admin/tenants", json=tenant_data, headers=headers)
    assert response.status_code == 201

    data = response.json()
    assert "tenant_id" in data
    assert data["name"] == "test-org-1"
    assert data["db_name"] == "soc_mind_tenant_test_org_1"
    assert data["status"] == "ONBOARDING"

    db_name = data["db_name"]
    alias = MockDatabaseManager.get_tenant_db_alias(db_name)
    mongo_client = mongoengine.connection.get_connection(alias)
    assert db_name in mongo_client.list_database_names()

    tdb = mongoengine.connection.get_db(alias)
    col_names = tdb.list_collection_names()
    assert "alerts" in col_names
    assert "knowledge_base" in col_names
    assert "onboarding_status" in col_names


def test_tenant_duplicate_name():
    headers = get_auth_headers()
    tenant_data = {"name": "test-org-dup", "display_name": "Test Organization"}
    client.post("/api/v1/admin/tenants", json=tenant_data, headers=headers)

    response = client.post("/api/v1/admin/tenants", json=tenant_data, headers=headers)
    assert response.status_code == 409
    assert response.json()["detail"] == "A tenant with this name already exists"


def test_tenant_page_reports_total_and_applies_server_paging():
    for index in range(15):
        TenantService.create_tenant(
            TenantCreate(name=f"page-{index}", display_name=f"Page {index}"),
            created_by="admin@example.com",
        )

    response = client.get(
        "/api/v1/admin/tenants/page?skip=10&limit=4&search=Page",
        headers=get_auth_headers(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 15
    assert body["skip"] == 10
    assert body["limit"] == 4
    assert len(body["items"]) == 4


def test_tenant_status_suspension():
    headers = get_auth_headers()
    tenant_data = {"name": "suspend-org", "display_name": "Suspend Org"}
    r = client.post("/api/v1/admin/tenants", json=tenant_data, headers=headers)
    tenant_id = r.json()["tenant_id"]

    client.patch(
        f"/api/v1/admin/tenants/{tenant_id}/status",
        json={"status": "ACTIVE"},
        headers=headers,
    )

    ingest_r = client.post(f"/api/v1/ingest/{tenant_id}/events")
    assert ingest_r.status_code == 200

    client.patch(
        f"/api/v1/admin/tenants/{tenant_id}/status",
        json={"status": "SUSPENDED"},
        headers=headers,
    )

    ingest_fail = client.post(f"/api/v1/ingest/{tenant_id}/events")
    assert ingest_fail.status_code == 403
    assert "suspended" in ingest_fail.json()["detail"].lower()


def test_tenant_onboarding_status():
    headers = get_auth_headers()
    tenant_data = {"name": "onboard-org", "display_name": "Onboarding Org"}
    r = client.post("/api/v1/admin/tenants", json=tenant_data, headers=headers)
    tenant_id = r.json()["tenant_id"]

    r_obs = client.get(
        f"/api/v1/admin/tenants/{tenant_id}/onboarding-status", headers=headers
    )
    assert r_obs.status_code == 200

    obs_data = r_obs.json()
    assert obs_data["base_schema_configured"] is True


def test_delete_unsupported_but_soft_delete_works():
    headers = get_auth_headers()
    tenant_data = {"name": "del-org", "display_name": "Delete Org"}
    r = client.post("/api/v1/admin/tenants", json=tenant_data, headers=headers)
    tenant_id = r.json()["tenant_id"]

    del_res = client.delete(f"/api/v1/admin/tenants/{tenant_id}", headers=headers)
    assert del_res.status_code == 405

    status_r = client.patch(
        f"/api/v1/admin/tenants/{tenant_id}/status",
        json={"status": "DELETED"},
        headers=headers,
    )
    assert status_r.status_code == 200
    assert status_r.json()["status"] == "DELETED"


def test_get_dead_letter_by_id():
    headers = get_auth_headers()
    tenant_data = {"name": "dl-detail-org", "display_name": "DL Detail Org"}
    r = client.post("/api/v1/admin/tenants", json=tenant_data, headers=headers)
    assert r.status_code == 201
    body = r.json()
    tenant_id = body["tenant_id"]
    db_name = body["db_name"]
    alias = MockDatabaseManager.get_tenant_db_alias(db_name)
    tdb = mongoengine.connection.get_db(alias)
    ins = tdb.dead_letters.insert_one(
        {
            "alert_id": "alert-dl-1",
            "tenant_id": tenant_id,
            "source_system": "splunk",
            "error_type": "MISSING_REQUIRED_FIELD",
            "failed_fields": ["subject"],
            "raw_payload": {"foo": "bar"},
            "received_at": datetime.now(timezone.utc),
            "dead_lettered_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    oid = str(ins.inserted_id)
    gr = client.get(
        f"/api/v1/admin/tenants/{tenant_id}/dead-letters/{oid}",
        headers=headers,
    )
    assert gr.status_code == 200
    assert gr.json()["alert_id"] == "alert-dl-1"
    assert gr.json()["error_type"] == "MISSING_REQUIRED_FIELD"

    nf = client.get(
        f"/api/v1/admin/tenants/{tenant_id}/dead-letters/not-an-objectid",
        headers=headers,
    )
    assert nf.status_code == 404
