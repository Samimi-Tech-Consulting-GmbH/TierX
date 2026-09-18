import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import ingest
from app.core.config import settings
from app.services import trace
from app.services.kafka_publisher import KafkaPublisher


class FakePublisher:
    def __init__(self):
        self.received = []
        self.dead_letters = []
        self.traces = []

    async def publish_received(self, message):
        self.received.append(message)

    async def publish_dead_letter(self, message):
        self.dead_letters.append(message)

    async def publish_trace(self, message):
        self.traces.append(message)


class FakeTenantCache:
    def is_active_tenant(self, tenant_id):
        return tenant_id == "tenant-good"

    def is_source_allowed(self, tenant_id, source):
        return tenant_id == "tenant-good" and source == "SPLUNK"

    def get_allowed_sources(self, tenant_id):
        return {"SPLUNK"}


def _client(monkeypatch):
    publisher = FakePublisher()
    monkeypatch.setattr(ingest, "kafka_publisher", publisher)
    monkeypatch.setattr(trace, "kafka_publisher", publisher)
    monkeypatch.setattr(ingest, "tenant_cache", FakeTenantCache())
    monkeypatch.setattr(settings, "debug_trace_enabled", True)
    app = FastAPI()
    app.include_router(ingest.router, prefix="/api/v1/alerts")
    return TestClient(app), publisher


def _body(tenant_id="tenant-good"):
    return {
        "tenant_id": tenant_id,
        "source_system": "SPLUNK",
        "alert_type": "splunk.notable.endpoint_malware",
        "timestamp": "2026-07-27T10:00:00Z",
        "raw_payload": {"result": {"host": "HOST-1"}},
    }


def test_success_emits_received_and_completed_trace(monkeypatch):
    client, publisher = _client(monkeypatch)
    response = client.post(
        "/api/v1/alerts/ingest",
        json=_body(),
        headers={"X-TierX-Debug-Actor": "admin@example.com"},
    )

    assert response.status_code == 200
    assert len(publisher.received) == 1
    assert [event["phase"] for event in publisher.traces] == ["STARTED", "COMPLETED"]
    assert publisher.traces[-1]["outcome"] == "SUCCEEDED"
    assert publisher.traces[-1]["submitted_by"] == "admin@example.com"
    assert publisher.traces[-1]["alert_id"] == response.json()["alert_id"]


def test_unknown_tenant_reuses_alert_id_for_trace_and_dead_letter(monkeypatch):
    client, publisher = _client(monkeypatch)
    response = client.post("/api/v1/alerts/ingest", json=_body("missing"))

    assert response.status_code == 422
    alert_id = response.json()["alert_id"]
    assert publisher.traces[-1]["outcome"] == "FAILED"
    assert publisher.traces[-1]["alert_id"] == alert_id
    assert publisher.dead_letters[0]["alert_id"] == alert_id
    assert publisher.dead_letters[0]["error_type"] == "UNKNOWN_TENANT"


def test_private_caller_can_reserve_alert_id(monkeypatch):
    client, publisher = _client(monkeypatch)
    reserved = "00000000-0000-4000-8000-000000000201"
    response = client.post(
        "/api/v1/alerts/ingest",
        json=_body(),
        headers={"X-TierX-Requested-Alert-ID": reserved},
    )

    assert response.status_code == 200
    assert response.json()["alert_id"] == reserved
    assert publisher.received[0]["alert_id"] == reserved
    assert publisher.traces[-1]["alert_id"] == reserved


def test_legacy_private_header_is_accepted_and_conflict_is_rejected(monkeypatch):
    client, _ = _client(monkeypatch)
    reserved = "00000000-0000-4000-8000-000000000201"
    legacy = client.post(
        "/api/v1/alerts/ingest",
        json=_body(),
        headers={"X-SOC-Mind-Requested-Alert-ID": reserved},
    )
    assert legacy.status_code == 200
    assert legacy.json()["alert_id"] == reserved
    conflict = client.post(
        "/api/v1/alerts/ingest",
        json=_body(),
        headers={
            "X-TierX-Requested-Alert-ID": reserved,
            "X-SOC-Mind-Requested-Alert-ID": "00000000-0000-4000-8000-000000000202",
        },
    )
    assert conflict.status_code == 400


def test_jira_source_reference_is_forwarded_without_changing_raw_alert(monkeypatch):
    client, publisher = _client(monkeypatch)
    body = _body()
    body["source_reference"] = {
        "type": "JIRA",
        "jira_cloud_id": "cloud-1",
        "project_key": "DEMO",
        "issue_key": "DEMO-5",
        "content_sha256": "a" * 64,
    }

    response = client.post("/api/v1/alerts/ingest", json=body)

    assert response.status_code == 200
    assert publisher.received[0]["raw_payload"] == body["raw_payload"]
    assert publisher.received[0]["source_system"] == "SPLUNK"
    assert publisher.received[0]["source_reference"] == body["source_reference"]


@pytest.mark.asyncio
async def test_trace_publication_does_not_wait_for_broker(monkeypatch):
    release = asyncio.Event()

    class SlowProducer:
        async def send_and_wait(self, topic, message):
            await release.wait()

    publisher = KafkaPublisher()
    publisher._producer = SlowProducer()
    monkeypatch.setattr(settings, "debug_trace_enabled", True)

    await publisher.publish_trace({"span_id": "span-1"})
    assert len(publisher._trace_tasks) == 1
    assert not next(iter(publisher._trace_tasks)).done()

    release.set()
    await asyncio.gather(*publisher._trace_tasks)
