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
from typing import Any

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
            await self.process(msg.value)
        except Exception:
            self.logger.exception(
                "Failed to persist dead-letter document — skipping message"
            )

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
                "analysis_run_id",
                "analysis_scope_type",
                "analysis_scope_id",
                "requested_analysis_version",
                "retry_cycle",
            ):
                if data.get(key) is not None:
                    doc[key] = data[key]

            result = await db[COLLECTION].insert_one(doc)
            output = {
                "dead_letter_id": str(result.inserted_id),
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
