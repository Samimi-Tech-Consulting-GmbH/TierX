from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

import mongomock
import mongomock.gridfs
import mongoengine
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import jira_integrations as jira_api
from app.api.v1.admin import jira_integrations as admin_jira_api
from app.core.security import create_access_token
from app.models.tenant import Tenant
from app.schemas.jira_integration import (
    MAX_JIRA_ATTACHMENT_BYTES,
    JiraAttachmentManifest,
    JiraIntegrationCreate,
    JiraProjectRouteCreate,
    JiraRawAlertSource,
    JiraSubmissionCreate,
    JiraSubmissionFailure,
)
from app.services import jira_integration_service as service_module
from app.services.jira_integration_service import JiraIntegrationService


@pytest.fixture
def jira_db():
    mongoengine.disconnect_all()
    mongomock.gridfs.enable_gridfs_integration()
    mongoengine.connect(
        "soc_mind_platform",
        host="mongodb://unit-test.invalid/",
        mongo_client_class=mongomock.MongoClient,
        alias="default",
        uuidRepresentation="standard",
    )
    tenant = Tenant(
        tenant_id="tenant-1",
        name="tenant-one",
        display_name="Tenant One",
        db_name="soc_mind_tenant_one",
        status="ACTIVE",
        allowed_source_systems=["SPLUNK"],
    ).save()
    tenant_db = JiraIntegrationService._tenant_db("tenant-1")
    tenant_db.alert_type_schemas.insert_one(
        {
            "schema_id": "schema-splunk-malware",
            "tenant_id": "tenant-1",
            "alert_type": "splunk.notable.endpoint_malware",
            "version": "1.0.0",
            "field_mapping": {"event.created": "result._time"},
            "critical_fields": ["event.created"],
            "fields": [],
            "is_active": True,
            "created_by": "test",
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
    )
    JiraIntegrationService.ensure_indexes()
    yield mongoengine.connection.get_db("default"), tenant


def _integration(jira_db):
    created = JiraIntegrationService.create_integration(
        JiraIntegrationCreate(
            name="Forge testing",
            jira_cloud_id="cloud-1",
            jira_site_url="https://example.atlassian.net",
        ),
        "admin@example.com",
    )
    JiraIntegrationService.create_route(
        created.integration_id,
        JiraProjectRouteCreate(
            project_key="SEC",
            tenant_id="tenant-1",
            source_system="SPLUNK",
            alert_type="splunk.notable.endpoint_malware",
        ),
        "admin@example.com",
    )
    authenticated = JiraIntegrationService.authenticate(
        created.integration_id, created.secret
    )
    return created, authenticated


def _submission_body(
    *, attachments=None, updated=None, project_key="SEC", rule_id="JIRA-TRANSPORT-1"
):
    return JiraSubmissionCreate(
        jira_cloud_id="cloud-1",
        jira_site_url="https://example.atlassian.net",
        issue_id="10001",
        issue_key="SEC-1",
        project_key=project_key,
        issue_created_at=datetime(2026, 8, 10, tzinfo=timezone.utc),
        issue_updated_at=updated or datetime(2026, 8, 10, tzinfo=timezone.utc),
        submitted_by={"account_id": "user-1"},
        raw_alert={
            "result": {
                "_time": "2026-08-10T00:00:00Z",
                "rule_id": rule_id,
            }
        },
        raw_alert_source=JiraRawAlertSource(
            kind="DESCRIPTION",
            sha256="a" * 64,
        ),
        attachments=attachments or [],
    )


def test_credential_lifecycle_and_site_binding(jira_db):
    created, authenticated = _integration(jira_db)
    assert created.secret.startswith("socjira_")
    stored = jira_db[0].jira_integrations.find_one(
        {"integration_id": created.integration_id}
    )
    assert "secret" not in stored
    assert stored["secret_hash"] == hashlib.sha256(created.secret.encode()).hexdigest()

    with pytest.raises(Exception) as wrong_secret:
        JiraIntegrationService.authenticate(created.integration_id, "wrong")
    assert wrong_secret.value.status_code == 401

    info = JiraIntegrationService.connection_info(authenticated)
    assert info.jira_cloud_id == "cloud-1"
    assert info.route_count == 1
    rotated = JiraIntegrationService.rotate_secret(created.integration_id)
    with pytest.raises(Exception):
        JiraIntegrationService.authenticate(created.integration_id, created.secret)
    JiraIntegrationService.authenticate(created.integration_id, rotated.secret)
    revoked = JiraIntegrationService.revoke(created.integration_id)
    assert revoked.state == "REVOKED"


def test_raw_alert_submission_is_idempotent_when_jira_comments_update_issue(jira_db):
    _, integration = _integration(jira_db)
    first = JiraIntegrationService.create_submission(integration, _submission_body())
    second = JiraIntegrationService.create_submission(integration, _submission_body())
    comment_updated_issue = JiraIntegrationService.create_submission(
        integration,
        _submission_body(updated=datetime(2026, 8, 10, 0, 1, tzinfo=timezone.utc)),
    )
    assert first.submission_id == second.submission_id
    assert first.alert_id == second.alert_id
    assert second.idempotent_replay is True
    assert comment_updated_issue.submission_id == first.submission_id
    assert comment_updated_issue.alert_id == first.alert_id
    assert comment_updated_issue.idempotent_replay is True


def test_changed_raw_alert_creates_a_new_submission(jira_db):
    _, integration = _integration(jira_db)
    first = JiraIntegrationService.create_submission(integration, _submission_body())
    changed = JiraIntegrationService.create_submission(
        integration,
        _submission_body(
            updated=datetime(2026, 8, 10, 0, 1, tzinfo=timezone.utc),
            rule_id="JIRA-TRANSPORT-2",
        ),
    )
    assert changed.submission_id != first.submission_id
    assert changed.alert_id != first.alert_id


def test_route_revision_changes_submission_identity(jira_db):
    created, integration = _integration(jira_db)
    first = JiraIntegrationService.create_submission(integration, _submission_body())
    route = JiraIntegrationService.list_routes(created.integration_id)[0]
    JiraIntegrationService.update_route(
        created.integration_id,
        route.route_id,
        JiraProjectRouteCreate(
            project_key="SEC",
            tenant_id="tenant-1",
            source_system="SPLUNK",
            alert_type="splunk.notable.endpoint_malware",
        ),
        "admin@example.com",
    )
    second = JiraIntegrationService.create_submission(integration, _submission_body())
    assert second.submission_id != first.submission_id


def test_project_routes_are_scoped_to_tenant(jira_db):
    created, integration = _integration(jira_db)
    Tenant(
        tenant_id="tenant-2",
        name="tenant-two",
        display_name="Tenant Two",
        db_name="soc_mind_tenant_two",
        status="ACTIVE",
        allowed_source_systems=["SPLUNK"],
    ).save()
    tenant_db = JiraIntegrationService._tenant_db("tenant-2")
    tenant_db.alert_type_schemas.insert_one(
        {
            "schema_id": "schema-two",
            "tenant_id": "tenant-2",
            "alert_type": "splunk.notable.endpoint_malware",
            "version": "1.0.0",
            "field_mapping": {"event.created": "result._time"},
            "critical_fields": ["event.created"],
            "fields": [],
            "is_active": True,
            "created_by": "test",
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
    )
    JiraIntegrationService.create_route(
        created.integration_id,
        JiraProjectRouteCreate(
            project_key="OPS",
            tenant_id="tenant-2",
            source_system="SPLUNK",
            alert_type="splunk.notable.endpoint_malware",
        ),
        "admin@example.com",
    )
    first = JiraIntegrationService.create_submission(integration, _submission_body())
    second = JiraIntegrationService.create_submission(
        integration, _submission_body(project_key="OPS")
    )
    assert first.submission_id != second.submission_id
    assert first.tenant_id == "tenant-1"
    assert second.tenant_id == "tenant-2"


def test_submission_rechecks_routed_source_authorization(jira_db):
    _, integration = _integration(jira_db)
    Tenant.objects(tenant_id="tenant-1").update_one(
        set__allowed_source_systems=["SENTINEL"]
    )
    with pytest.raises(Exception) as denied:
        JiraIntegrationService.create_submission(integration, _submission_body())
    assert denied.value.status_code == 409
    route = JiraIntegrationService.list_routes(
        integration["integration_id"]
    )[0]
    assert route.last_error
    assert route.last_error["detail"] == (
        "The Jira project route source system is no longer allowed."
    )


def test_deleted_project_route_can_be_recreated(jira_db):
    created, _ = _integration(jira_db)
    route = JiraIntegrationService.list_routes(created.integration_id)[0]
    JiraIntegrationService.delete_route(
        created.integration_id, route.route_id, "admin@example.com"
    )
    deleted = jira_db[0].jira_project_routes.find_one({"route_id": route.route_id})
    assert "route_identity" not in deleted
    replacement = JiraIntegrationService.create_route(
        created.integration_id,
        JiraProjectRouteCreate(
            project_key="SEC",
            tenant_id="tenant-1",
            source_system="SPLUNK",
            alert_type="splunk.notable.endpoint_malware",
        ),
        "admin@example.com",
    )
    assert replacement.route_id != route.route_id
    assert jira_db[0].jira_project_routes.index_information()[
        "jira_route_identity_unique"
    ]["unique"]


def test_raw_alert_size_is_enforced_by_backend_contract(jira_db):
    with pytest.raises(ValueError, match="exceeds the 1 MiB limit"):
        JiraSubmissionCreate(
            **{
                **_submission_body().model_dump(),
                "raw_alert": {"oversized": "x" * (1024 * 1024)},
            }
        )


def test_attachment_upload_is_hashed_quarantined_and_idempotent(jira_db):
    _, integration = _integration(jira_db)
    content = b"quarantined evidence"
    body = _submission_body(
        attachments=[
            JiraAttachmentManifest(
                attachment_id="att-1",
                filename="evidence.bin",
                size=len(content),
                media_type="application/octet-stream",
            )
        ]
    )
    submission = JiraIntegrationService.create_submission(integration, body)
    digest = hashlib.sha256(content).hexdigest()
    upload = JiraIntegrationService.upload_attachment(
        integration,
        submission.submission_id,
        "att-1",
        content,
        digest,
        "application/octet-stream",
    )
    replay = JiraIntegrationService.upload_attachment(
        integration,
        submission.submission_id,
        "att-1",
        content,
        digest,
        "application/octet-stream",
    )
    assert upload.sha256 == replay.sha256 == digest
    refreshed = JiraIntegrationService.get_submission(
        integration, submission.submission_id
    )
    assert refreshed.state == "ACCEPTED"
    assert refreshed.uploaded_attachment_ids == ["att-1"]

    tenant_db = JiraIntegrationService._tenant_db("tenant-1")
    file_doc = tenant_db.jira_quarantine.files.find_one()
    assert file_doc["metadata"]["quarantine_status"] == "UNSCANNED"
    assert file_doc["metadata"]["expires_at"] > datetime.now(timezone.utc).replace(
        tzinfo=None
    )


@pytest.mark.asyncio
async def test_finalize_forwards_reserved_alert_id(jira_db, monkeypatch):
    _, integration = _integration(jira_db)
    submission = JiraIntegrationService.create_submission(
        integration, _submission_body()
    )

    class Response:
        is_success = True

        def json(self):
            return {"alert_id": submission.alert_id, "status": "RECEIVED"}

    class Client:
        calls = []

        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            return Response()

    monkeypatch.setattr(service_module.httpx, "AsyncClient", Client)
    result = await JiraIntegrationService.finalize_submission(
        integration, submission.submission_id
    )
    assert result.state == "PROCESSING"
    assert (
        Client.calls[0][1]["headers"]["X-TierX-Requested-Alert-ID"]
        == submission.alert_id
    )
    forwarded = Client.calls[0][1]["json"]
    assert {
        key: forwarded[key]
        for key in ("tenant_id", "source_system", "alert_type", "timestamp", "raw_payload")
    } == {
        "tenant_id": "tenant-1",
        "source_system": "SPLUNK",
        "alert_type": "splunk.notable.endpoint_malware",
        "timestamp": "2026-08-10T00:00:00Z",
        "raw_payload": {
            "result": {
                "_time": "2026-08-10T00:00:00Z",
                "rule_id": "JIRA-TRANSPORT-1",
            }
        },
    }
    assert forwarded["source_reference"]["project_key"] == "SEC"


def test_unmapped_project_cannot_choose_a_tenant(jira_db):
    _, integration = _integration(jira_db)
    with pytest.raises(Exception) as denied:
        JiraIntegrationService.create_submission(
            integration, _submission_body(project_key="UNMAPPED")
        )
    assert denied.value.status_code == 422


@pytest.mark.asyncio
async def test_ambiguous_finalize_failure_remains_retryable_and_reconciles(
    jira_db, monkeypatch
):
    _, integration = _integration(jira_db)
    submission = JiraIntegrationService.create_submission(
        integration, _submission_body()
    )

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            raise service_module.httpx.ReadTimeout("response was lost")

    monkeypatch.setattr(service_module.httpx, "AsyncClient", Client)
    ambiguous = await JiraIntegrationService.finalize_submission(
        integration, submission.submission_id
    )
    assert ambiguous.state == "FINALIZING"
    assert ambiguous.failure is None

    tenant_db = JiraIntegrationService._tenant_db("tenant-1")
    tenant_db.alerts.insert_one({"alert_id": submission.alert_id})
    reconciled = JiraIntegrationService.get_submission(
        integration, submission.submission_id
    )
    assert reconciled.state == "PROCESSING"


@pytest.mark.asyncio
async def test_ambiguous_finalize_can_retry_with_same_reserved_alert_id(
    jira_db, monkeypatch
):
    _, integration = _integration(jira_db)
    submission = JiraIntegrationService.create_submission(
        integration, _submission_body()
    )

    class Response:
        is_success = True

        def json(self):
            return {"alert_id": submission.alert_id, "status": "RECEIVED"}

    class Client:
        calls = 0

        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            self.__class__.calls += 1
            if self.__class__.calls == 1:
                raise service_module.httpx.ReadTimeout("response was lost")
            assert kwargs["headers"]["X-TierX-Requested-Alert-ID"] == submission.alert_id
            return Response()

    monkeypatch.setattr(service_module.httpx, "AsyncClient", Client)
    first = await JiraIntegrationService.finalize_submission(
        integration, submission.submission_id
    )
    assert first.state == "FINALIZING"
    jira_db[0].jira_integration_submissions.update_one(
        {"submission_id": submission.submission_id},
        {
            "$set": {
                "ingestion_delivery.next_retry_at": datetime.now(timezone.utc)
                - timedelta(seconds=1)
            }
        },
    )
    retried = await JiraIntegrationService.finalize_submission(
        integration, submission.submission_id
    )
    assert retried.state == "PROCESSING"
    assert Client.calls == 2


@pytest.mark.asyncio
async def test_definitive_ingestion_rejection_fails_submission(jira_db, monkeypatch):
    _, integration = _integration(jira_db)
    submission = JiraIntegrationService.create_submission(
        integration, _submission_body()
    )

    class Response:
        is_success = False
        status_code = 422

        def json(self):
            return {"error_type": "UNKNOWN_SOURCE", "error_detail": "JIRA denied"}

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            return Response()

    monkeypatch.setattr(service_module.httpx, "AsyncClient", Client)
    rejected = await JiraIntegrationService.finalize_submission(
        integration, submission.submission_id
    )
    assert rejected.state == "FAILED"
    assert rejected.failure["error_type"] == "INGESTION_REJECTED"


def test_status_resolves_cluster_analysis_and_explicit_failure(jira_db):
    _, integration = _integration(jira_db)
    analyzed = JiraIntegrationService.create_submission(integration, _submission_body())
    platform = jira_db[0]
    platform.jira_integration_submissions.update_one(
        {"submission_id": analyzed.submission_id}, {"$set": {"state": "PROCESSING"}}
    )
    tenant_db = JiraIntegrationService._tenant_db("tenant-1")
    tenant_db.alerts.insert_one(
        {
            "alert_id": analyzed.alert_id,
            "status": "ANALYZED",
            "analysis_status": "SUCCEEDED",
            "cluster_id": "cluster-1",
        }
    )
    tenant_db.clusters.insert_one(
        {
            "cluster_id": "cluster-1",
            "summary": {
                "headline": "Suspicious Jira report",
                "narrative": "Evidence summary",
                "confidence": "MEDIUM",
                "recommended_actions": ["Validate endpoint evidence"],
            },
        }
    )
    status_result = JiraIntegrationService.get_submission(
        integration, analyzed.submission_id
    )
    assert status_result.state == "ANALYZED"
    assert status_result.result["headline"] == "Suspicious Jira report"
    assert status_result.cluster_path.endswith("/cluster-1")

    failed = JiraIntegrationService.create_submission(
        integration,
        _submission_body(
            updated=datetime(2026, 8, 10, 0, 2, tzinfo=timezone.utc),
            rule_id="JIRA-TRANSFER-FAILURE",
        ),
    )
    failure = JiraIntegrationService.fail_submission(
        integration,
        failed.submission_id,
        JiraSubmissionFailure(
            failed_stage="JIRA_TRANSFER",
            error_type="CHECKSUM_MISMATCH",
            error_detail="Safe failure detail",
        ),
    )
    assert failure.state == "FAILED"
    assert failure.failure["error_detail"] == "Safe failure detail"


def test_cluster_analysis_failure_is_terminal_even_when_alert_exists(jira_db):
    _, integration = _integration(jira_db)
    submission = JiraIntegrationService.create_submission(
        integration, _submission_body()
    )
    jira_db[0].jira_integration_submissions.update_one(
        {"submission_id": submission.submission_id},
        {"$set": {"state": "PROCESSING"}},
    )
    tenant_db = JiraIntegrationService._tenant_db("tenant-1")
    tenant_db.alerts.insert_one(
        {"alert_id": submission.alert_id, "cluster_id": "cluster-failed"}
    )
    tenant_db.clusters.insert_one(
        {
            "cluster_id": "cluster-failed",
            "analysis_status": "FAILED",
            "analysis_error": {"type": "LLM_FAILURE", "detail": "Safe detail"},
        }
    )
    result = JiraIntegrationService.get_submission(
        integration, submission.submission_id
    )
    assert result.state == "FAILED"
    assert result.failure["failed_stage"] == "ANALYSIS"
    assert result.failure["error_type"] == "LLM_FAILURE"


def test_dead_letter_is_terminal_even_when_alert_exists(jira_db):
    _, integration = _integration(jira_db)
    submission = JiraIntegrationService.create_submission(
        integration,
        _submission_body(updated=datetime(2026, 8, 10, 0, 3, tzinfo=timezone.utc)),
    )
    jira_db[0].jira_integration_submissions.update_one(
        {"submission_id": submission.submission_id},
        {"$set": {"state": "PROCESSING"}},
    )
    tenant_db = JiraIntegrationService._tenant_db("tenant-1")
    tenant_db.alerts.insert_one(
        {"alert_id": submission.alert_id, "cluster_id": "cluster-pending"}
    )
    tenant_db.dead_letters.insert_one(
        {
            "alert_id": submission.alert_id,
            "failed_stage": "CORRELATION",
            "error_type": "CORRELATION_EXCEPTION",
            "error_detail": "Safe correlation error",
            "received_at": datetime.now(timezone.utc),
        }
    )
    result = JiraIntegrationService.get_submission(
        integration, submission.submission_id
    )
    assert result.state == "FAILED"
    assert result.failure["failed_stage"] == "CORRELATION"
    assert result.failure["error_type"] == "CORRELATION_EXCEPTION"


def test_transfer_failure_cannot_overwrite_processing_submission(jira_db):
    _, integration = _integration(jira_db)
    submission = JiraIntegrationService.create_submission(
        integration, _submission_body()
    )
    jira_db[0].jira_integration_submissions.update_one(
        {"submission_id": submission.submission_id},
        {"$set": {"state": "PROCESSING"}},
    )
    result = JiraIntegrationService.fail_submission(
        integration,
        submission.submission_id,
        JiraSubmissionFailure(
            failed_stage="JIRA_TRANSFER",
            error_type="KVS_FAILURE",
            error_detail="Forge failed after ingestion",
        ),
    )
    assert result.state == "PROCESSING"
    assert result.idempotent_replay is True


def test_public_api_requires_both_credential_parts(jira_db):
    created, _ = _integration(jira_db)
    app = FastAPI()
    app.include_router(jira_api.router, prefix="/api/v1")
    client = TestClient(app)
    assert client.get("/api/v1/integrations/jira/connection").status_code == 401
    assert (
        client.get(
            "/api/v1/integrations/jira/connection",
            headers={
                "X-TierX-Integration-ID": created.integration_id,
                "Authorization": f"Bearer {created.secret}",
            },
        ).status_code
        == 200
    )


def test_admin_site_and_route_apis_require_platform_admin(jira_db):
    app = FastAPI()
    app.include_router(admin_jira_api.router, prefix="/api/v1/admin")
    client = TestClient(app)

    def headers(role: str) -> dict[str, str]:
        return {
            "Authorization": "Bearer "
            + create_access_token(
                user_id="user-1",
                email="admin@example.com",
                role=role,
                tenant_id="tenant-1" if role != "PLATFORM_ADMIN" else None,
            )
        }

    assert client.get("/api/v1/admin/integrations/jira").status_code in {401, 403}
    assert (
        client.get(
            "/api/v1/admin/integrations/jira", headers=headers("TENANT_ADMIN")
        ).status_code
        == 403
    )
    created = client.post(
        "/api/v1/admin/integrations/jira",
        headers=headers("PLATFORM_ADMIN"),
        json={
            "name": "Samimi Jira",
            "jira_cloud_id": "cloud-admin",
            "jira_site_url": "https://example.atlassian.net",
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["secret"].startswith("socjira_")
    route = client.post(
        f"/api/v1/admin/integrations/jira/{body['integration_id']}/routes",
        headers=headers("PLATFORM_ADMIN"),
        json={
            "project_key": "DEMO",
            "tenant_id": "tenant-1",
            "source_system": "SPLUNK",
            "alert_type": "splunk.notable.endpoint_malware",
            "enabled": True,
        },
    )
    assert route.status_code == 201
    assert route.json()["project_key"] == "DEMO"


def test_attachment_api_streams_and_rejects_oversized_body(jira_db):
    created, integration = _integration(jira_db)
    submission = JiraIntegrationService.create_submission(
        integration,
        _submission_body(
            attachments=[
                JiraAttachmentManifest(
                    attachment_id="too-large",
                    filename="large.bin",
                    size=MAX_JIRA_ATTACHMENT_BYTES,
                )
            ]
        ),
    )
    app = FastAPI()
    app.include_router(jira_api.router, prefix="/api/v1")
    client = TestClient(app)
    response = client.put(
        (
            f"/api/v1/integrations/jira/submissions/{submission.submission_id}"
            "/attachments/too-large"
        ),
        content=b"x" * (MAX_JIRA_ATTACHMENT_BYTES + 1),
        headers={
            "X-TierX-Integration-ID": created.integration_id,
            "Authorization": f"Bearer {created.secret}",
            "X-Content-SHA256": "0" * 64,
            # Deliberately understate the client-controlled header. The
            # streaming byte counter remains authoritative.
            "Content-Length": "1",
        },
    )
    assert response.status_code == 413


def test_cleanup_removes_expired_gridfs_files(jira_db):
    _, integration = _integration(jira_db)
    content = b"expired"
    submission = JiraIntegrationService.create_submission(
        integration,
        _submission_body(
            attachments=[
                JiraAttachmentManifest(
                    attachment_id="expired-1", filename="expired.bin", size=len(content)
                )
            ]
        ),
    )
    JiraIntegrationService.upload_attachment(
        integration,
        submission.submission_id,
        "expired-1",
        content,
        hashlib.sha256(content).hexdigest(),
        None,
    )
    tenant_db = JiraIntegrationService._tenant_db("tenant-1")
    tenant_db.jira_quarantine.files.update_many(
        {},
        {
            "$set": {
                "metadata.expires_at": datetime.now(timezone.utc)
                - timedelta(seconds=1)
            }
        },
    )
    Tenant.objects(tenant_id="tenant-1").update_one(set__status="SUSPENDED")
    assert JiraIntegrationService.cleanup_expired_quarantine() == 1
    assert tenant_db.jira_quarantine.files.count_documents({}) == 0
