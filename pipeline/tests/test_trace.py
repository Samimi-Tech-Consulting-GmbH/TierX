from datetime import datetime, timezone
import json

import pytest

from app.core.config import settings
from app.services.trace import TraceSpan, snapshot
from app.workers.trace_worker import TraceWorker


@pytest.mark.asyncio
async def test_trace_span_emits_idempotent_start_and_completion(monkeypatch):
    monkeypatch.setattr(settings, "debug_trace_enabled", True)
    monkeypatch.setattr(settings, "app_release_version", "0.1.0")
    events = []

    async def publish(event):
        events.append(event)

    data = {
        "alert_id": "alert-1",
        "tenant_id": "tenant-1",
        "alert_type": "test.type",
        "source_system": "SPLUNK",
        "raw_payload": {"password": "must-not-leak", "event": "ok"},
    }
    async with TraceSpan(
        publisher=publish,
        stage="VALIDATION",
        service="test-worker",
        data=data,
    ) as span:
        await span.finish("SUCCEEDED", output_value={"validated": True})

    assert len(events) == 2
    assert events[0]["span_id"] == events[1]["span_id"]
    assert events[0]["outcome"] == "RUNNING"
    assert events[1]["outcome"] == "SUCCEEDED"
    assert events[0]["release_version"] == "0.1.0"
    assert events[0]["input_snapshot"]["value"]["raw_payload"]["password"] == "[REDACTED]"


@pytest.mark.asyncio
async def test_trace_span_normalizes_and_redacts_completion_metadata(monkeypatch):
    monkeypatch.setattr(settings, "debug_trace_enabled", True)
    events = []

    async def publish(event):
        # Match the production Kafka serializer so non-JSON values fail the test.
        json.dumps(event)
        events.append(event)

    completed_at = datetime(2026, 8, 10, 7, 43, 57, tzinfo=timezone.utc)
    async with TraceSpan(
        publisher=publish,
        stage="ENRICHMENT",
        service="pipeline-enrichment",
        data={"alert_id": "alert-1"},
    ) as span:
        await span.finish(
            "SUCCEEDED",
            checks=[{"name": "provider", "checked_at": completed_at}],
            decisions={
                "playbook_context_webhooks": [
                    {
                        "webhook_id": "threat-intel",
                        "completed_at": completed_at,
                        "prompt_footer": "must-not-be-passed-by-callers",
                        "signing_secret": "must-not-leak",
                    }
                ]
            },
            error={"observed_at": completed_at, "access_token": "must-not-leak"},
        )

    completed = events[-1]
    assert completed["checks"][0]["checked_at"] == str(completed_at)
    provider = completed["decisions"]["playbook_context_webhooks"][0]
    assert provider["completed_at"] == str(completed_at)
    assert provider["prompt_footer"] == "[REDACTED]"
    assert provider["signing_secret"] == "[REDACTED]"
    assert completed["error"]["access_token"] == "[REDACTED]"


def test_snapshot_truncates_and_hashes_large_payload(monkeypatch):
    monkeypatch.setattr(settings, "debug_trace_max_snapshot_bytes", 32)
    result = snapshot({"value": "x" * 100})
    assert result["truncated"] is True
    assert result["size_bytes"] > 32
    assert len(result["sha256"]) == 64


def test_snapshot_normalizes_datetime_to_json_safe_value():
    value = {"generated_at": datetime(2026, 7, 27, 1, 2, 3, tzinfo=timezone.utc)}
    result = snapshot(value)
    assert result["value"]["generated_at"] == "2026-07-27 01:02:03+00:00"
    json.dumps(result)


class FakeCollection:
    def __init__(self):
        self.documents = {}

    async def update_one(self, query, update, upsert=False):
        exists = query["span_id"] in self.documents
        document = self.documents.setdefault(query["span_id"], {})
        if not exists:
            document.update(update.get("$setOnInsert", {}))
        document.update(update.get("$set", {}))


class FakeDatabase:
    def __init__(self, collection):
        self.collection = collection

    def __getitem__(self, name):
        return self.collection


@pytest.mark.asyncio
async def test_trace_worker_upserts_start_and_completion(monkeypatch):
    collection = FakeCollection()
    monkeypatch.setattr(
        "app.workers.trace_worker.get_database",
        lambda: FakeDatabase(collection),
    )
    worker = TraceWorker()
    base = {
        "span_id": "span-1",
        "alert_id": "alert-1",
        "stage": "VALIDATION",
        "sequence": 20,
        "service": "pipeline-validation",
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    await worker.process({**base, "phase": "STARTED", "outcome": "RUNNING"})
    await worker.process(
        {
            **base,
            "phase": "COMPLETED",
            "outcome": "SUCCEEDED",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "checks": [{"name": "schema", "outcome": "SUCCEEDED"}],
        }
    )

    stored = collection.documents["span-1"]
    assert stored["outcome"] == "SUCCEEDED"
    assert stored["checks"][0]["name"] == "schema"

    # Idempotent replay: a late STARTED event cannot downgrade completion.
    await worker.process({**base, "phase": "STARTED", "outcome": "RUNNING"})
    assert collection.documents["span-1"]["outcome"] == "SUCCEEDED"
