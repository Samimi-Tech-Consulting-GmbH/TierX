from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.config import settings
from app.db.mongodb import get_database
from app.workers.base import BaseWorker

COLLECTION = "alert_processing_events"


def _datetime(value: str | datetime | None) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class TraceWorker(BaseWorker):
    """Persist private debug events without producing pipeline output."""

    def __init__(self):
        super().__init__(
            name="trace",
            input_topic=settings.kafka_trace_topic,
            output_topic=None,
        )

    async def start(self):
        collection = get_database()[COLLECTION]
        await collection.create_index("span_id", unique=True)
        await collection.create_index([("alert_id", 1), ("sequence", 1), ("started_at", 1)])
        await collection.create_index([("tenant_id", 1), ("started_at", -1)])
        await collection.create_index([("release_version", 1), ("started_at", -1)])
        await collection.create_index([("release_sha", 1), ("started_at", -1)])
        await collection.create_index("expires_at", expireAfterSeconds=0)
        await super().start()

    async def _handle(self, msg: Any):
        try:
            await self.process(msg.value)
        except Exception:
            self.logger.exception("Failed to persist trace event")

    async def process(self, data: dict[str, Any]) -> None:
        span_id = data.get("span_id")
        alert_id = data.get("alert_id")
        if not span_id or not alert_id:
            raise ValueError("trace event requires span_id and alert_id")

        now = datetime.now(timezone.utc)
        base = {
            key: data.get(key)
            for key in (
                "span_id",
                "alert_id",
                "tenant_id",
                "alert_type",
                "source_system",
                "stage",
                "sequence",
                "service",
                "release_sha",
                "release_version",
                "submitted_by",
                "input_snapshot",
            )
            if data.get(key) is not None
        }
        base["started_at"] = _datetime(data.get("started_at")) or now
        base["recorded_at"] = now
        base["expires_at"] = base["started_at"] + timedelta(
            days=settings.debug_trace_retention_days
        )

        update: dict[str, Any]
        if data.get("phase") == "COMPLETED":
            update = {
                "$set": {
                    **base,
                    "outcome": data.get("outcome", "RUNNING"),
                    "completed_at": _datetime(data.get("completed_at")) or now,
                    "duration_ms": data.get("duration_ms"),
                    "checks": data.get("checks", []),
                    "decisions": data.get("decisions", {}),
                    "output_snapshot": data.get("output_snapshot"),
                    "error": data.get("error"),
                }
            }
        elif data.get("phase") == "PROGRESS":
            await get_database()[COLLECTION].update_one(
                {"span_id": span_id, "completed_at": {"$exists": False}},
                {
                    "$set": {
                        "outcome": "RUNNING",
                        "recorded_at": now,
                        "decisions": data.get("decisions", {}),
                    }
                },
            )
            return
        else:
            # A replayed STARTED event must never downgrade an already completed span.
            update = {"$setOnInsert": {**base, "outcome": "RUNNING"}}

        await get_database()[COLLECTION].update_one(
            {"span_id": span_id},
            update,
            upsert=True,
        )
