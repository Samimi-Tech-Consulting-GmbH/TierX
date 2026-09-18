from datetime import datetime, timedelta, timezone

import httpx
import mongomock
import mongoengine
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.admin import debug as debug_api
from app.core.errors import ResourceNotFoundError
from app.core.security import create_access_token
from app.services.debug_trace_service import DebugTraceService, _processing_duration_ms


def _token(role="PLATFORM_ADMIN"):
    return create_access_token(
        user_id="debug-user",
        email="debug@example.com",
        role=role,
        tenant_id="tenant-1" if role != "PLATFORM_ADMIN" else None,
    )


def _headers(role="PLATFORM_ADMIN"):
    return {"Authorization": f"Bearer {_token(role)}"}


class FakeResponse:
    status_code = 200
    is_success = True

    def json(self):
        return {"alert_id": "alert-accepted", "status": "RECEIVED"}


class FakeAsyncClient:
    calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return FakeResponse()


def _api_client(monkeypatch):
    monkeypatch.setattr(debug_api, "DEBUG_TRACE_ENABLED", True)
    monkeypatch.setattr(debug_api.httpx, "AsyncClient", lambda **kwargs: FakeAsyncClient())
    app = FastAPI()
    app.include_router(debug_api.router, prefix="/api/v1/admin")
    return TestClient(app)


def test_debug_ingest_requires_platform_admin(monkeypatch):
    client = _api_client(monkeypatch)
    response = client.post(
        "/api/v1/admin/debug/ingest",
        json={"tenant_id": "tenant-1"},
        headers=_headers("TENANT_ADMIN"),
    )
    assert response.status_code == 403


def test_debug_ingest_requires_authentication(monkeypatch):
    client = _api_client(monkeypatch)
    response = client.post(
        "/api/v1/admin/debug/ingest",
        json={"tenant_id": "tenant-1"},
    )
    assert response.status_code in {401, 403}


def test_debug_ingest_returns_trace_location(monkeypatch):
    FakeAsyncClient.calls.clear()
    client = _api_client(monkeypatch)
    response = client.post(
        "/api/v1/admin/debug/ingest",
        json={"tenant_id": "tenant-1"},
        headers=_headers(),
    )
    assert response.status_code == 202
    assert response.json()["trace_path"].endswith("/alert-accepted")
    assert FakeAsyncClient.calls[0][1]["headers"]["X-TierX-Debug-Actor"] == (
        "debug@example.com"
    )


def test_debug_ingest_returns_503_when_private_service_fails(monkeypatch):
    class FailingClient(FakeAsyncClient):
        async def post(self, *args, **kwargs):
            raise httpx.ConnectError("offline")

    monkeypatch.setattr(debug_api, "DEBUG_TRACE_ENABLED", True)
    monkeypatch.setattr(debug_api.httpx, "AsyncClient", lambda **kwargs: FailingClient())
    app = FastAPI()
    app.include_router(debug_api.router, prefix="/api/v1/admin")
    response = TestClient(app).post(
        "/api/v1/admin/debug/ingest",
        json={"tenant_id": "tenant-1"},
        headers=_headers(),
    )
    assert response.status_code == 503


def test_processing_duration_counts_only_valid_completed_spans():
    now = datetime.now(timezone.utc)
    assert _processing_duration_ms(
        [
            {"completed_at": now, "duration_ms": 12.5},
            {"completed_at": now, "duration_ms": 87.5},
            {"outcome": "RUNNING", "duration_ms": 999_999},
            {"completed_at": now, "duration_ms": -1},
            {"completed_at": now, "duration_ms": True},
        ]
    ) == 100


def test_trace_service_lists_and_reads_spans():
    mongoengine.disconnect_all()
    mongoengine.connect(
        "soc_mind_platform",
        host="mongodb://unit-test.invalid/",
        mongo_client_class=mongomock.MongoClient,
        alias="default",
        uuidRepresentation="standard",
    )
    collection = mongoengine.connection.get_db("default")["alert_processing_events"]
    now = datetime.now(timezone.utc)
    collection.insert_many(
        [
            {
                "span_id": "span-1",
                "alert_id": "alert-1",
                "tenant_id": "tenant-1",
                "stage": "INGESTION",
                "sequence": 10,
                "outcome": "SUCCEEDED",
                "started_at": now,
                "completed_at": now,
                "duration_ms": 12.5,
                "release_version": "0.1.0",
                "release_sha": "a" * 40,
            },
            {
                "span_id": "span-2",
                "alert_id": "alert-1",
                "tenant_id": "tenant-1",
                "stage": "ENRICHMENT",
                "sequence": 50,
                "outcome": "SUCCEEDED",
                "started_at": now + timedelta(minutes=30),
                "completed_at": now + timedelta(minutes=30),
                "duration_ms": 87.5,
                "release_version": "0.1.0",
                "release_sha": "a" * 40,
            },
        ]
    )

    page = DebugTraceService.list_traces(tenant_id="tenant-1")
    filtered = DebugTraceService.list_traces(stage="INGESTION")
    version_filtered = DebugTraceService.list_traces(release_version="0.1.0")
    detail = DebugTraceService.get_trace("alert-1")
    assert page["total"] == 1
    assert page["items"][0]["processing_duration_ms"] == 100
    assert page["items"][0]["terminal_state"] == "SUCCEEDED"
    assert page["items"][0]["release_version"] == "0.1.0"
    assert page["items"][0]["mixed_releases"] is False
    assert version_filtered["total"] == 1
    assert filtered["items"][0]["current_stage"] == "ENRICHMENT"
    assert [span["stage"] for span in detail["spans"]] == ["INGESTION", "ENRICHMENT"]

    DebugTraceService.ensure_indexes()
    indexes = collection.index_information()
    assert indexes["span_id_1"]["unique"] is True
    assert indexes["expires_at_1"]["expireAfterSeconds"] == 0

    with pytest.raises(ResourceNotFoundError):
        DebugTraceService.get_trace("historical-without-trace")


def test_trace_summary_distinguishes_mixed_and_legacy_release_metadata():
    now = datetime.now(timezone.utc)
    mixed = DebugTraceService._summary(
        [
            {
                "alert_id": "mixed",
                "stage": "INGESTION",
                "sequence": 10,
                "outcome": "SUCCEEDED",
                "started_at": now,
                "release_version": "0.1.0",
                "release_sha": "a" * 40,
            },
            {
                "alert_id": "mixed",
                "stage": "CORRELATION",
                "sequence": 60,
                "outcome": "SUCCEEDED",
                "started_at": now,
                "release_version": "0.1.1",
                "release_sha": "b" * 40,
            },
        ]
    )
    assert mixed["release_version"] is None
    assert mixed["release_sha"] is None
    assert mixed["release_versions"] == ["0.1.0", "0.1.1"]
    assert mixed["mixed_releases"] is True

    legacy = DebugTraceService._summary(
        [
            {
                "alert_id": "legacy",
                "stage": "INGESTION",
                "sequence": 10,
                "outcome": "SUCCEEDED",
                "started_at": now,
                "release_sha": "c" * 40,
            }
        ]
    )
    assert legacy["release_version"] is None
    assert legacy["release_versions"] == []
    assert legacy["release_sha"] == "c" * 40
    assert legacy["mixed_releases"] is False

    partial = DebugTraceService._summary(
        [
            {
                "alert_id": "partial",
                "stage": "INGESTION",
                "sequence": 10,
                "outcome": "SUCCEEDED",
                "started_at": now,
                "release_sha": "d" * 40,
            },
            {
                "alert_id": "partial",
                "stage": "ANALYSIS",
                "sequence": 70,
                "outcome": "SUCCEEDED",
                "started_at": now,
                "release_version": "0.1.0",
                "release_sha": "d" * 40,
            },
        ]
    )
    assert partial["release_version"] is None
    assert partial["release_sha"] == "d" * 40
    assert partial["mixed_releases"] is True
