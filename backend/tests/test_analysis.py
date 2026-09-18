from datetime import datetime, timezone

import mongomock
import mongoengine
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.v1 import analysis as analysis_api
from app.core.security import create_access_token
from app.services.analysis_service import (
    AnalysisService,
    LEGACY_SYSTEM_PROMPT_ID,
    SYSTEM_PROMPT_ID,
)


@pytest.fixture
def tenant_db(monkeypatch):
    database = mongomock.MongoClient()["tenant"]
    monkeypatch.setattr(
        AnalysisService,
        "_db",
        staticmethod(lambda tenant_id: database),
    )
    return database


def _run(state="FAILED"):
    now = datetime.now(timezone.utc)
    return {
        "analysis_run_id": "run-1",
        "tenant_id": "tenant-1",
        "analysis_scope_type": "ALERT",
        "analysis_scope_id": "alert-1",
        "requested_analysis_version": 1,
        "state": state,
        "retry_cycle": 0,
        "attempts_total": 4,
        "attempts_in_cycle": 4,
        "created_at": now,
        "updated_at": now,
    }


def test_list_and_retry_failed_standalone_run(tenant_db):
    tenant_db.alerts.insert_one(
        {
            "alert_id": "alert-1",
            "cluster_id": None,
            "requested_analysis_version": 1,
        }
    )
    tenant_db.analysis_runs.insert_one(_run())
    page = AnalysisService.list_runs(
        "tenant-1", "ALERT", "alert-1", skip=0, limit=50
    )
    retry = AnalysisService.retry("tenant-1", "ALERT", "alert-1")
    assert page.total == 1
    assert retry.state == "PENDING"
    assert retry.retry_cycle == 1
    persisted = tenant_db.analysis_runs.find_one({"analysis_run_id": "run-1"})
    assert persisted["attempts_total"] == 4
    assert persisted["attempts_in_cycle"] == 0


def test_retry_rejects_promoted_standalone_alert(tenant_db):
    tenant_db.alerts.insert_one(
        {
            "alert_id": "alert-1",
            "cluster_id": "cluster-1",
            "requested_analysis_version": 1,
        }
    )
    tenant_db.analysis_runs.insert_one(_run())
    with pytest.raises(HTTPException) as error:
        AnalysisService.retry("tenant-1", "ALERT", "alert-1")
    assert error.value.status_code == 409


def test_system_prompt_is_seeded_and_versioned():
    mongoengine.disconnect_all()
    mongoengine.connect(
        "soc_mind_platform",
        host="mongodb://unit-test.invalid/",
        mongo_client_class=mongomock.MongoClient,
        alias="default",
        uuidRepresentation="standard",
    )
    AnalysisService.ensure_system_prompt()
    first = AnalysisService.get_system_prompt()
    second = AnalysisService.update_system_prompt(
        "Updated evidence-only system prompt", "admin@example.com", first.version
    )
    assert first.template_id == SYSTEM_PROMPT_ID
    assert second.version == first.version + 1
    assert AnalysisService.get_system_prompt().prompt.startswith("Updated")


def test_active_legacy_prompt_is_copied_idempotently():
    mongoengine.disconnect_all()
    mongoengine.connect(
        "soc_mind_platform",
        host="mongodb://unit-test.invalid/",
        mongo_client_class=mongomock.MongoClient,
        alias="default",
        uuidRepresentation="standard",
    )
    collection = mongoengine.connection.get_db("default").prompt_templates
    collection.insert_one({
        "template_id": LEGACY_SYSTEM_PROMPT_ID,
        "version": 7,
        "prompt": "Approved legacy prompt",
        "is_active": True,
    })
    AnalysisService.ensure_system_prompt()
    AnalysisService.ensure_system_prompt()
    copied = list(collection.find({"template_id": SYSTEM_PROMPT_ID}))
    assert len(copied) == 1
    assert copied[0]["version"] == 7
    assert copied[0]["prompt"] == "Approved legacy prompt"
    assert copied[0]["migrated_from_template_id"] == LEGACY_SYSTEM_PROMPT_ID


def _headers(role: str, tenant_id: str | None = "tenant-1"):
    token = create_access_token(
        user_id="user-1",
        email="user@example.com",
        role=role,
        tenant_id=None if role == "PLATFORM_ADMIN" else tenant_id,
    )
    return {"Authorization": f"Bearer {token}"}


def test_alert_runs_are_read_only_and_cluster_retry_requires_admin(monkeypatch):
    monkeypatch.setattr(
        AnalysisService,
        "list_runs",
        lambda *args, **kwargs: {"items": [], "total": 0},
    )
    monkeypatch.setattr(
        AnalysisService,
        "retry",
        lambda *args, **kwargs: {
            "analysis_run_id": "run-1",
            "analysis_scope_type": "CLUSTER",
            "analysis_scope_id": "cluster-1",
            "requested_analysis_version": 1,
            "retry_cycle": 1,
            "state": "PENDING",
        },
    )
    app = FastAPI()
    app.include_router(analysis_api.router, prefix="/api/v1")
    client = TestClient(app)
    read = client.get(
        "/api/v1/tenants/tenant-1/alerts/alert-1/analysis/runs",
        headers=_headers("TENANT_OPERATOR"),
    )
    denied = client.post(
        "/api/v1/tenants/tenant-1/clusters/cluster-1/analysis/retry",
        headers=_headers("TENANT_OPERATOR"),
    )
    allowed = client.post(
        "/api/v1/tenants/tenant-1/clusters/cluster-1/analysis/retry",
        headers=_headers("TENANT_ADMIN"),
    )
    cross_tenant = client.get(
        "/api/v1/tenants/tenant-2/alerts/alert-1/analysis/runs",
        headers=_headers("TENANT_OPERATOR"),
    )
    assert read.status_code == 200
    assert denied.status_code == 403
    assert client.post(
        "/api/v1/tenants/tenant-1/alerts/alert-1/analysis/retry",
        headers=_headers("TENANT_ADMIN"),
    ).status_code == 404
    assert allowed.status_code == 200
    assert cross_tenant.status_code == 403
