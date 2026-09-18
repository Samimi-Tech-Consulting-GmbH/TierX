import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.config import settings
from app.core.severity import canonical_severity
from app.workers.dead_letter_worker import DeadLetterWorker
from app.workers.enrichment_worker import EnrichmentWorker
from app.workers.fingerprint_worker import compute_fingerprint
from app.workers.fingerprint_worker import FingerprintWorker
from app.workers.normalization_worker import NormalizationWorker
from app.workers.validation_worker import ValidationWorker


def test_normalization_maps_only_resolved_fields():
    result = NormalizationWorker._apply_field_mapping(
        {"result": {"host": "WIN-1", "src": "10.0.0.1"}},
        {
            "host.hostname": "result.host",
            "source.ip": "result.src",
            "user.name": "result.user",
        },
    )
    assert result == {"host.hostname": "WIN-1", "source.ip": "10.0.0.1"}


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (5, "CRITICAL"),
        ("critical", "CRITICAL"),
        (4, "HIGH"),
        ("medium", "MEDIUM"),
        (2, "LOW"),
        (None, "UNKNOWN"),
        ("invalid", "UNKNOWN"),
    ],
)
def test_pipeline_canonical_severity(value, expected):
    assert canonical_severity(value) == expected


def test_fingerprint_is_stable_and_ignores_unlisted_fields():
    base = {"rule.id": "R-1", "source.ip": "10.0.0.1"}
    assert compute_fingerprint(base) == compute_fingerprint(
        {**base, "custom.unused": "different"}
    )


@pytest.mark.asyncio
async def test_validation_failure_trace_contains_missing_field(monkeypatch):
    worker = ValidationWorker()
    produced = []

    async def fake_produce(topic, message):
        produced.append((topic, message))

    async def fake_schema(tenant_id, alert_type):
        return {
            "schema_id": "schema-1",
            "version": "1.0.0",
            "critical_fields": ["source.ip"],
            "field_mapping": {"source.ip": "result.src"},
        }

    monkeypatch.setattr(settings, "debug_trace_enabled", True)
    monkeypatch.setattr(worker, "produce", fake_produce)
    monkeypatch.setattr(
        "app.workers.validation_worker.get_active_schema",
        fake_schema,
    )
    result = await worker.process(
        {
            "alert_id": "alert-1",
            "tenant_id": "tenant-1",
            "alert_type": "test.type",
            "source_system": "SPLUNK",
            "raw_payload": {"result": {}},
            "kafka_state": "RECEIVED",
            "status": "RECEIVED",
        }
    )

    assert result is None
    await asyncio.sleep(0)
    trace_events = [
        message for topic, message in produced if topic == settings.kafka_trace_topic
    ]
    assert trace_events[-1]["outcome"] == "FAILED"
    assert trace_events[-1]["error"]["failed_fields"] == ["source.ip"]
    dlq_events = [
        message
        for topic, message in produced
        if topic == settings.kafka_dead_letter_topic
    ]
    assert dlq_events[0]["failed_stage"] == "VALIDATION"


class FakeCollection:
    def __init__(self, find_result=None):
        self.find_result = find_result
        self.updated = []
        self.deleted = []
        self.inserted = []

    async def find_one(self, *args, **kwargs):
        return self.find_result

    async def update_one(self, query, update):
        self.updated.append((query, update))

    async def delete_one(self, query):
        self.deleted.append(query)

    async def insert_one(self, document):
        self.inserted.append(document)
        return SimpleNamespace(inserted_id="dead-letter-1")


class FakeDatabase:
    def __init__(self, name, collections):
        self.name = name
        self.collections = collections

    def __getitem__(self, name):
        return self.collections[name]


@pytest.mark.asyncio
async def test_normalization_persists_canonical_severity(monkeypatch):
    alerts = FakeCollection()
    database = FakeDatabase("tenant_db", {"alerts": alerts})
    worker = NormalizationWorker()

    async def active_schema(tenant_id, alert_type):
        return {
            "schema_id": "schema-1",
            "version": "1.0.0",
            "field_mapping": {"event.severity": "result.severity"},
        }

    async def tenant_database(tenant_id):
        return "tenant_db"

    monkeypatch.setattr(settings, "debug_trace_enabled", False)
    monkeypatch.setattr(
        "app.workers.normalization_worker.get_active_schema", active_schema
    )
    monkeypatch.setattr(
        "app.workers.normalization_worker.get_tenant_db_name", tenant_database
    )
    monkeypatch.setattr(
        "app.workers.normalization_worker.get_client",
        lambda: {"tenant_db": database},
    )

    result = await worker.process(
        {
            "alert_id": "alert-severity",
            "tenant_id": "tenant-1",
            "alert_type": "test.type",
            "source_system": "SPLUNK",
            "raw_payload": {"result": {"severity": "5"}},
            "kafka_state": "VALIDATED",
            "status": "ANALYZING",
            "validated": True,
        }
    )

    assert result is not None
    assert alerts.inserted[0]["severity"] == "CRITICAL"


@pytest.mark.asyncio
async def test_duplicate_fingerprint_records_source_and_dead_letters(monkeypatch):
    alerts = FakeCollection(find_result={"alert_id": "original-1"})
    database = FakeDatabase("tenant_db", {"alerts": alerts})
    worker = FingerprintWorker()
    produced = []

    async def fake_produce(topic, message):
        produced.append((topic, message))

    async def fake_db_name(tenant_id):
        return "tenant_db"

    monkeypatch.setattr(settings, "debug_trace_enabled", False)
    monkeypatch.setattr(worker, "produce", fake_produce)
    monkeypatch.setattr(
        "app.workers.fingerprint_worker.get_tenant_db_name", fake_db_name
    )
    monkeypatch.setattr(
        "app.workers.fingerprint_worker.get_client",
        lambda: {"tenant_db": database},
    )
    result = await worker.process(
        {
            "alert_id": "duplicate-1",
            "tenant_id": "tenant-1",
            "alert_type": "test.type",
            "source_system": "SPLUNK",
            "normalized_payload": {"rule.id": "R-1", "source.ip": "10.0.0.1"},
            "raw_payload": {"result": {}},
        }
    )

    assert result is None
    dlq = next(
        message
        for topic, message in produced
        if topic == settings.kafka_dead_letter_topic
    )
    assert dlq["error_type"] == "DUPLICATED_ALERT"
    assert dlq["source_alert"] == "original-1"
    assert dlq["failed_stage"] == "FINGERPRINT"
    assert alerts.deleted == [{"alert_id": "duplicate-1"}]


@pytest.mark.asyncio
async def test_playbook_resolution_reports_schema_match_and_no_match(monkeypatch):
    worker = EnrichmentWorker()
    playbooks = FakeCollection(
        find_result={
            "playbook_id": "pb-1",
            "version": "2",
            "prompt": "Investigate",
        }
    )
    database = FakeDatabase("tenant_db", {"playbooks": playbooks})

    async def fake_db_name(tenant_id):
        return "tenant_db"

    async def linked_schema(tenant_id, alert_type):
        return {"playbook_id": "pb-1"}

    monkeypatch.setattr(
        "app.workers.enrichment_worker.get_tenant_db_name", fake_db_name
    )
    monkeypatch.setattr(
        "app.workers.enrichment_worker.get_active_schema", linked_schema
    )
    monkeypatch.setattr(
        "app.workers.enrichment_worker.get_client",
        lambda: {"tenant_db": database},
    )

    matched, matched_decision = await worker._resolve_playbook("tenant-1", "test.type")
    assert matched["playbook_id"] == "pb-1"
    assert matched_decision["resolution"] == "SCHEMA_LINK"

    playbooks.find_result = None
    missing, missing_decision = await worker._resolve_playbook("tenant-1", "test.type")
    assert missing is None
    assert missing_decision["alert_type_fallback_attempted"] is True
    assert missing_decision["resolution"] == "NONE"


@pytest.mark.asyncio
async def test_enrichment_persists_optional_knowledge_base_results(monkeypatch):
    worker = EnrichmentWorker()
    alerts = FakeCollection(find_result={})
    playbooks = FakeCollection()
    database = FakeDatabase("tenant_db", {"alerts": alerts, "playbooks": playbooks})
    playbook = {
        "playbook_id": "pb-1",
        "version": 2,
        "prompt": "Investigate",
        "knowledge_base": {"enabled": True, "top_k": 3},
    }

    async def fake_db_name(_tenant_id):
        return "tenant_db"

    expected = {
        "status": "OK",
        "retrieval_version": "kb-retrieval-v1",
        "query_sha256": "query-sha",
        "query_summary": {"field_count": 2},
        "matches": [
            {
                "document_id": "doc-1",
                "document_version": 1,
                "chunk_id": "chunk-1",
                "text": "Tenant evidence",
                "text_sha256": "chunk-sha",
                "score": 120.0,
                "matched_by": [{"method": "CIDR_CONTAINS"}],
            }
        ],
    }
    monkeypatch.setattr(settings, "debug_trace_enabled", False)
    monkeypatch.setattr(settings, "knowledge_base_retrieval_enabled", True)
    monkeypatch.setattr(
        worker,
        "_resolve_playbook",
        AsyncMock(return_value=(playbook, {"resolution": "SCHEMA_LINK"})),
    )
    monkeypatch.setattr(
        worker._knowledge_base, "search_alert", AsyncMock(return_value=expected)
    )
    monkeypatch.setattr(
        "app.workers.enrichment_worker.get_tenant_db_name", fake_db_name
    )
    monkeypatch.setattr(
        "app.workers.enrichment_worker.get_client", lambda: {"tenant_db": database}
    )

    output = await worker.process(
        {
            "alert_id": "alert-1",
            "tenant_id": "tenant-1",
            "alert_type": "test.type",
            "source_system": "SPLUNK",
            "normalized_payload": {"source.ip": "198.51.100.50"},
            "raw_payload": {"result": {"src": "198.51.100.50"}},
            "fingerprint": "fingerprint",
        }
    )

    assert output["kafka_state"] == "ENRICHED"
    worker._knowledge_base.search_alert.assert_awaited_once()
    persisted = alerts.updated[-1][1]["$set"]["enrichment.kb_context"]
    assert persisted == expected


@pytest.mark.asyncio
async def test_dead_letter_persists_extended_debug_fields(monkeypatch):
    dead_letters = FakeCollection()
    database = FakeDatabase("soc_mind_platform", {"dead_letters": dead_letters})
    worker = DeadLetterWorker()

    async def fake_resolve_db(tenant_id):
        return database

    monkeypatch.setattr(settings, "debug_trace_enabled", False)
    monkeypatch.setattr(worker, "_resolve_db", fake_resolve_db)
    await worker.process(
        {
            "alert_id": "failed-1",
            "tenant_id": None,
            "alert_type": "test.type",
            "source_system": "SPLUNK",
            "error_type": "UNKNOWN_TENANT",
            "error_detail": "Tenant is not active",
            "failed_stage": "INGESTION",
            "failed_fields": ["tenant_id"],
            "status": "FAILED",
            "kafka_state": "DLQ",
        }
    )

    stored = dead_letters.inserted[0]
    assert stored["alert_type"] == "test.type"
    assert stored["error_detail"] == "Tenant is not active"
    assert stored["failed_stage"] == "INGESTION"
    assert stored["status"] == "FAILED"
    assert stored["kafka_state"] == "DLQ"
