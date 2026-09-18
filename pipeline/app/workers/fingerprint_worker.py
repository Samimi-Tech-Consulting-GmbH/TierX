"""
Fingerprint Worker
──────────────────
Consumes from the ``normalized`` topic.

1. Computes a deterministic SHA-256 hash over a fixed set of ECS fields
   extracted from ``normalized_payload``.  This hash is the platform-wide
   exact-match deduplication key.
2. Queries the tenant's ``alerts`` collection for any *other* alert that
   shares the same fingerprint within the configurable deduplication window
   (default 60 min).
3. **Distinct** → updates the alert document with the ``fingerprint``,
   produces to the ``distinct`` topic.
4. **Duplicate** → removes the alert from the ``alerts`` collection,
   produces to the dead-letter topic with ``error_type=DUPLICATED_ALERT``
   and ``source_alert`` pointing to the original alert's id.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.config import settings
from app.db.mongodb import get_client
from app.schemas.messages import DistinctAlertMessage, NormalizedAlertMessage
from app.services.schema_registry import get_tenant_db_name
from app.workers.base import BaseWorker

ALERTS_COLLECTION = "alerts"

HASH_FIELDS: list[str] = [
    "event.kind",
    "event.category",
    "event.type",
    "rule.name",
    "rule.id",
    "host.hostname",
    "source.ip",
    "destination.ip",
    "destination.port",
    "user.name",
    "process.name",
    "process.command_line",
    "file.path",
    "file.hash.sha256",
    "network.protocol",
    "url.domain",
    "dns.question.name",
    "threat.technique.id",
]


def compute_fingerprint(normalized_payload: dict[str, Any]) -> str:
    """
    Build a deterministic SHA-256 hex digest from the values of
    ``HASH_FIELDS`` present in the normalized payload.

    Only fields that exist (not None) contribute to the hash.  The fields
    are processed in the fixed order defined by ``HASH_FIELDS`` so the
    result is stable regardless of dict ordering.
    """
    parts: list[tuple[str, str]] = []
    for field in HASH_FIELDS:
        value = normalized_payload.get(field)
        if value is not None:
            parts.append((field, str(value)))

    canonical = json.dumps(parts, sort_keys=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class FingerprintWorker(BaseWorker):

    def __init__(self):
        super().__init__(
            name="fingerprint",
            input_topic=settings.kafka_normalized_topic,
            output_topic=settings.kafka_distinct_topic,
        )

    async def process(self, data: dict[str, Any]) -> dict[str, Any] | None:
        async with self.trace_span("FINGERPRINT", data) as trace:
            msg = NormalizedAlertMessage.model_validate(data)
            fingerprint_inputs = [
                {"field": field, "value": msg.normalized_payload.get(field)}
                for field in HASH_FIELDS
                if msg.normalized_payload.get(field) is not None
            ]
            fingerprint = compute_fingerprint(msg.normalized_payload)

            db_name = await get_tenant_db_name(msg.tenant_id)
            if db_name is None:
                detail = "Could not resolve tenant database in fingerprint stage"
                await trace.finish(
                    "FAILED",
                    decisions={
                        "fingerprint_inputs": fingerprint_inputs,
                        "fingerprint": fingerprint,
                    },
                    error={"type": "NORMALIZATION_FAILED", "detail": detail},
                )
                await self.produce_dead_letter(
                    alert_id=msg.alert_id,
                    tenant_id=msg.tenant_id,
                    alert_type=msg.alert_type,
                    source_system=msg.source_system,
                    raw_payload=msg.raw_payload,
                    error_type="NORMALIZATION_FAILED",
                    error_detail=detail,
                    failed_stage="FINGERPRINT",
                )
                return None

            tenant_db = get_client()[db_name]
            alerts_col = tenant_db[ALERTS_COLLECTION]

            await alerts_col.update_one(
                {"alert_id": msg.alert_id},
                {
                    "$set": {
                        "fingerprint": fingerprint,
                        "kafka_state": "DISTINCT",
                        "updated_at": datetime.now(timezone.utc),
                    }
                },
            )

            cutoff = datetime.now(timezone.utc) - timedelta(
                minutes=settings.deduplication_window_minutes,
            )
            original = await alerts_col.find_one(
                {
                    "fingerprint": fingerprint,
                    "tenant_id": msg.tenant_id,
                    "alert_id": {"$ne": msg.alert_id},
                    "created_at": {"$gte": cutoff},
                },
                {"alert_id": 1, "_id": 0},
            )

            decisions = {
                "fingerprint_inputs": fingerprint_inputs,
                "fingerprint": fingerprint,
                "deduplication_window_minutes": settings.deduplication_window_minutes,
                "duplicate": original is not None,
                "source_alert": original.get("alert_id") if original else None,
            }

            if original is not None:
                await alerts_col.delete_one({"alert_id": msg.alert_id})
                detail = (
                    f"Duplicate of alert_id={original['alert_id']} "
                    f"within {settings.deduplication_window_minutes}m window"
                )
                now = datetime.now(timezone.utc).isoformat()
                dlq_msg = {
                    "alert_id": msg.alert_id,
                    "tenant_id": msg.tenant_id,
                    "alert_type": msg.alert_type,
                    "source_system": msg.source_system,
                    "raw_payload": msg.raw_payload,
                    "status": "FAILED",
                    "kafka_state": "DLQ",
                    "dead_lettered_at": now,
                    "error_type": "DUPLICATED_ALERT",
                    "error_detail": detail,
                    "failed_stage": "FINGERPRINT",
                    "source_alert": original["alert_id"],
                    "fingerprint": fingerprint,
                    "failed_fields": [],
                }
                await trace.finish(
                    "FAILED",
                    decisions=decisions,
                    error={"type": "DUPLICATED_ALERT", "detail": detail},
                )
                await self.produce(settings.kafka_dead_letter_topic, dlq_msg)
                self.logger.warning(
                    "Duplicate alert_id=%s of source_alert=%s (fingerprint=%s…)",
                    msg.alert_id,
                    original["alert_id"],
                    fingerprint[:12],
                )
                return None

            distinct = DistinctAlertMessage(
                alert_id=msg.alert_id,
                tenant_id=msg.tenant_id,
                alert_type=msg.alert_type,
                source_system=msg.source_system,
                normalized_payload=msg.normalized_payload,
                raw_payload=msg.raw_payload,
                source_reference=msg.source_reference,
                fingerprint=fingerprint,
            )
            output = distinct.model_dump()
            await trace.finish(
                "SUCCEEDED",
                output_value=output,
                checks=[
                    {"name": "tenant_database", "outcome": "SUCCEEDED"},
                    {"name": "duplicate_lookup", "outcome": "SUCCEEDED"},
                ],
                decisions=decisions,
            )
            self.logger.info(
                "Distinct alert_id=%s fingerprint=%s…", msg.alert_id, fingerprint[:12],
            )
            return output
