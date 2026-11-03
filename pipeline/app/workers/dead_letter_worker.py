"""
Dead-Letter Worker
──────────────────
Consumes from the ``dead_letter_queue`` topic and persists each message into
the tenant's ``dead_letters`` MongoDB collection.

If the tenant cannot be resolved (e.g. UNKNOWN_TENANT), the document is
written to the platform database's ``dead_letters`` collection instead.
"""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from typing import Any
from bson import ObjectId

from app.core.config import settings
from app.db.mongodb import get_client, get_database
from app.services.schema_registry import get_tenant_db_name
from app.workers.base import BaseWorker

COLLECTION = "dead_letters"


class DeadLetterWorker(BaseWorker):

    def __init__(self):
        super().__init__(
            name="dead-letter",
            input_topic=settings.kafka_dead_letter_topic,
            output_topic=None,
        )

    # ------------------------------------------------------------------
    # Override _handle to prevent recursive dead-lettering
    # ------------------------------------------------------------------

    async def _handle(self, msg: Any):
        try:
            data = dict(msg.value)
            if all(getattr(msg, key, None) is not None for key in ("topic", "partition", "offset")):
                data["kafka_delivery"] = {key: getattr(msg, key) for key in ("topic", "partition", "offset")}
            await self.process(data)
        except Exception:
            self.logger.exception(
                "Failed to persist dead-letter document — retaining for replay"
            )
            raise

    async def _handle_malformed(self, msg):
        # Persist metadata directly, never recursively republish into the DLQ.
        data = self.malformed_message(msg)
        data["kafka_delivery"] = data["kafka_record"]
        await self.process(data)

    # ------------------------------------------------------------------
    # Processing
    # ------------------------------------------------------------------

    async def process(self, data: dict[str, Any]) -> dict[str, Any] | None:
        async with self.trace_span("DEAD_LETTER", data) as trace:
            tenant_id: str | None = data.get("tenant_id")
            db = await self._resolve_db(tenant_id)

            doc: dict[str, Any] = {
                "alert_id": data.get("alert_id"),
                "tenant_id": tenant_id,
                "alert_type": data.get("alert_type"),
                "source_system": data.get("source_system"),
                "status": data.get("status", "FAILED"),
                "kafka_state": data.get("kafka_state", "DLQ"),
                "error_type": data.get("error_type"),
                "error_detail": data.get("error_detail"),
                "failed_stage": data.get("failed_stage"),
                "failed_fields": data.get("failed_fields", []),
                "raw_payload": data.get("raw_payload"),
                "received_at": datetime.now(timezone.utc),
                "dead_lettered_at": data.get("dead_lettered_at"),
            }

            if data.get("source_alert"):
                doc["source_alert"] = data["source_alert"]
            if data.get("fingerprint"):
                doc["fingerprint"] = data["fingerprint"]
            for key in (
                "kafka_record",
                "analysis_run_id",
                "analysis_scope_type",
                "analysis_scope_id",
                "requested_analysis_version",
                "retry_cycle",
            ):
                if data.get(key) is not None:
                    doc[key] = data[key]

            delivery = data.get("kafka_delivery")
            if delivery:
                identity = f"{delivery['topic']}:{delivery['partition']}:{delivery['offset']}"
                # Preserve the ObjectId contract used by existing detail APIs.
                document_id = ObjectId(sha256(("tierx:dead-letter:" + identity).encode()).digest()[:12])
                doc["kafka_delivery"] = delivery
                await db[COLLECTION].update_one({"_id": document_id}, {"$setOnInsert": doc}, upsert=True)
            else:
                result = await db[COLLECTION].insert_one(doc)
                document_id = str(result.inserted_id)
            output = {
                "dead_letter_id": str(document_id),
                "database": db.name,
                "error_type": doc["error_type"],
            }
            await trace.finish(
                "SUCCEEDED",
                output_value=output,
                checks=[{"name": "dead_letter_persisted", "outcome": "SUCCEEDED"}],
                decisions={"storage_database": db.name},
            )

            self.logger.info(
                "Persisted dead-letter alert_id=%s error_type=%s → %s",
                doc["alert_id"],
                doc["error_type"],
                db.name,
            )
            return None

    async def _resolve_db(self, tenant_id: str | None):
        """
        Return the tenant's database if resolvable, otherwise fall back to the
        platform database.
        """
        if tenant_id:
            db_name = await get_tenant_db_name(tenant_id)
            if db_name:
                return get_client()[db_name]

        return get_database()
