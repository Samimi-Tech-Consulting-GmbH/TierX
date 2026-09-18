"""
Normalization Worker
────────────────────
Consumes from the ``validated`` topic.

1. Loads the active alert-type schema for the alert's ``alert_type``.
2. Applies the schema's ``field_mapping`` to the ``raw_payload``, resolving
   each ECS key to its value from the source path.  The result is stored in
   ``normalized_payload``.
3. Persists the alert document to the tenant's ``alerts`` collection.
4. Produces the normalized message to the ``normalized`` topic.

On any exception the alert is **not** stored and a dead-letter message with
``error_type=NORMALIZATION_FAILED`` is produced instead.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.core.config import settings
from app.core.utils import resolve_path
from app.core.severity import canonical_severity
from app.db.mongodb import get_client
from app.schemas.messages import NormalizedAlertMessage, ValidatedAlertMessage
from app.services.schema_registry import get_active_schema, get_tenant_db_name
from app.workers.base import BaseWorker

ALERTS_COLLECTION = "alerts"


class NormalizationWorker(BaseWorker):

    def __init__(self):
        super().__init__(
            name="normalization",
            input_topic=settings.kafka_validated_topic,
            output_topic=settings.kafka_normalized_topic,
        )

    async def process(self, data: dict[str, Any]) -> dict[str, Any] | None:
        async with self.trace_span("NORMALIZATION", data) as trace:
            validated = ValidatedAlertMessage.model_validate(data)

            schema = await get_active_schema(validated.tenant_id, validated.alert_type)
            if schema is None:
                detail = (
                    f"No active schema found during normalization for "
                    f"alert_type={validated.alert_type!r}"
                )
                await trace.finish(
                    "FAILED",
                    checks=[{"name": "active_schema", "outcome": "FAILED"}],
                    error={"type": "NORMALIZATION_FAILED", "detail": detail},
                )
                await self.produce_dead_letter(
                    alert_id=validated.alert_id,
                    tenant_id=validated.tenant_id,
                    alert_type=validated.alert_type,
                    source_system=validated.source_system,
                    raw_payload=validated.raw_payload,
                    error_type="NORMALIZATION_FAILED",
                    error_detail=detail,
                    failed_stage="NORMALIZATION",
                )
                return None

            field_mapping = schema.get("field_mapping", {})
            mapping_results: list[dict[str, Any]] = []
            for ecs_key, source_path in field_mapping.items():
                value = resolve_path(validated.raw_payload, source_path)
                mapping_results.append(
                    {
                        "ecs_field": ecs_key,
                        "source_path": source_path,
                        "mapped": value is not None,
                        "value": value,
                    }
                )
            normalized_payload = {
                result["ecs_field"]: result["value"]
                for result in mapping_results
                if result["mapped"]
            }

            db_name = await get_tenant_db_name(validated.tenant_id)
            if db_name is None:
                detail = "Could not resolve tenant database"
                await trace.finish(
                    "FAILED",
                    checks=[{"name": "tenant_database", "outcome": "FAILED"}],
                    decisions={"field_mappings": mapping_results},
                    error={"type": "NORMALIZATION_FAILED", "detail": detail},
                )
                await self.produce_dead_letter(
                    alert_id=validated.alert_id,
                    tenant_id=validated.tenant_id,
                    alert_type=validated.alert_type,
                    source_system=validated.source_system,
                    raw_payload=validated.raw_payload,
                    error_type="NORMALIZATION_FAILED",
                    error_detail=detail,
                    failed_stage="NORMALIZATION",
                )
                return None

            now = datetime.now(timezone.utc)
            alert_doc = {
                "alert_id": validated.alert_id,
                "tenant_id": validated.tenant_id,
                "alert_type": validated.alert_type,
                "source_system": validated.source_system,
                "raw_payload": validated.raw_payload,
                "source_reference": validated.source_reference,
                "normalized_payload": normalized_payload,
                "severity": canonical_severity(
                    normalized_payload.get("event.severity")
                ),
                "status": "ANALYZING",
                "kafka_state": "NORMALIZED",
                "validated": True,
                "normalized": True,
                "created_at": now,
                "updated_at": now,
            }

            tenant_db = get_client()[db_name]
            await tenant_db[ALERTS_COLLECTION].insert_one(alert_doc)

            message = NormalizedAlertMessage(
                alert_id=validated.alert_id,
                tenant_id=validated.tenant_id,
                alert_type=validated.alert_type,
                source_system=validated.source_system,
                raw_payload=validated.raw_payload,
                source_reference=validated.source_reference,
                normalized_payload=normalized_payload,
            )

            output = message.model_dump()
            await trace.finish(
                "SUCCEEDED",
                output_value=output,
                checks=[
                    {"name": "active_schema", "outcome": "SUCCEEDED"},
                    {"name": "tenant_database", "outcome": "SUCCEEDED", "database": db_name},
                    {"name": "alert_persisted", "outcome": "SUCCEEDED"},
                ],
                decisions={
                    "schema_id": schema.get("schema_id"),
                    "schema_version": schema.get("version"),
                    "field_mappings": mapping_results,
                },
            )
            self.logger.info("Normalized alert_id=%s → %s", validated.alert_id, db_name)
            return output

    @staticmethod
    def _apply_field_mapping(
        raw_payload: dict[str, Any],
        field_mapping: dict[str, str],
    ) -> dict[str, Any]:
        """
        Build the normalized payload by resolving every ``field_mapping`` entry.

        Keys are ECS dotted paths (e.g. ``host.hostname``), values are the
        resolved data from ``raw_payload`` via the source path
        (e.g. ``result.host``).  Entries whose source path cannot be resolved
        are omitted.
        """
        normalized: dict[str, Any] = {}
        for ecs_key, source_path in field_mapping.items():
            value = resolve_path(raw_payload, source_path)
            if value is not None:
                normalized[ecs_key] = value
        return normalized
