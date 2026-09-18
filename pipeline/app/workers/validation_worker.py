"""
Validation Worker
─────────────────
Consumes from the ``received`` topic.

1. Loads the active alert-type schema for the alert's ``alert_type`` from the
   tenant's schema registry in MongoDB.
2. Validates the ``raw_payload`` against the schema's type-specific required
   fields and value constraints.
3. On success  → produces to the ``validated`` topic.
4. On failure  → produces to the dead-letter queue with the appropriate
   error_type (``ALERT_SCHEMA_MISSING``).
"""

from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.core.utils import resolve_path
from app.schemas.messages import ReceivedAlertMessage, ValidatedAlertMessage
from app.services.schema_registry import get_active_schema
from app.workers.base import BaseWorker


class ValidationWorker(BaseWorker):

    def __init__(self):
        super().__init__(
            name="validation",
            input_topic=settings.kafka_received_topic,
            output_topic=settings.kafka_validated_topic,
        )

    async def process(self, data: dict[str, Any]) -> dict[str, Any] | None:
        async with self.trace_span("VALIDATION", data) as trace:
            received = ReceivedAlertMessage.model_validate(data)
            schema = await get_active_schema(received.tenant_id, received.alert_type)
            checks: list[dict[str, Any]] = []

            if schema is None:
                detail = (
                    f"No active alert-type schema found for "
                    f"alert_type={received.alert_type!r} "
                    f"in tenant {received.tenant_id}"
                )
                checks.append({"name": "active_schema", "outcome": "FAILED", "detail": detail})
                await trace.finish(
                    "FAILED",
                    checks=checks,
                    error={"type": "ALERT_SCHEMA_MISSING", "detail": detail},
                )
                await self.produce_dead_letter(
                    alert_id=received.alert_id,
                    tenant_id=received.tenant_id,
                    alert_type=received.alert_type,
                    source_system=received.source_system,
                    raw_payload=received.raw_payload,
                    error_type="ALERT_SCHEMA_MISSING",
                    error_detail=detail,
                    failed_stage="VALIDATION",
                )
                return None

            checks.append(
                {
                    "name": "active_schema",
                    "outcome": "SUCCEEDED",
                    "schema_id": schema.get("schema_id"),
                    "version": schema.get("version"),
                }
            )
            field_mapping: dict[str, str] = schema.get("field_mapping", {})
            field_checks = []
            for field in schema.get("critical_fields", []):
                source_path = field_mapping.get(field)
                value = resolve_path(received.raw_payload, source_path) if source_path else None
                field_checks.append(
                    {
                        "field": field,
                        "source_path": source_path,
                        "present": value is not None,
                    }
                )
            missing_fields = [item["field"] for item in field_checks if not item["present"]]
            checks.append(
                {
                    "name": "critical_fields",
                    "outcome": "FAILED" if missing_fields else "SUCCEEDED",
                    "fields": field_checks,
                }
            )

            if missing_fields:
                detail = f"Critical fields missing in raw_payload: {', '.join(missing_fields)}"
                await trace.finish(
                    "FAILED",
                    checks=checks,
                    decisions={
                        "schema_id": schema.get("schema_id"),
                        "schema_version": schema.get("version"),
                    },
                    error={
                        "type": "MISSING_REQUIRED_FIELD",
                        "detail": detail,
                        "failed_fields": missing_fields,
                    },
                )
                await self.produce_dead_letter(
                    alert_id=received.alert_id,
                    tenant_id=received.tenant_id,
                    alert_type=received.alert_type,
                    source_system=received.source_system,
                    raw_payload=received.raw_payload,
                    error_type="MISSING_REQUIRED_FIELD",
                    error_detail=detail,
                    failed_fields=missing_fields,
                    failed_stage="VALIDATION",
                )
                return None

            validated = ValidatedAlertMessage(
                alert_id=received.alert_id,
                tenant_id=received.tenant_id,
                alert_type=received.alert_type,
                source_system=received.source_system,
                raw_payload=received.raw_payload,
                source_reference=received.source_reference,
            )
            output = validated.model_dump()
            await trace.finish(
                "SUCCEEDED",
                output_value=output,
                checks=checks,
                decisions={
                    "schema_id": schema.get("schema_id"),
                    "schema_version": schema.get("version"),
                },
            )
            self.logger.info("Validated alert_id=%s", received.alert_id)
            return output

    def _validate_critical_fields(
        self,
        raw_payload: dict[str, Any],
        schema: dict[str, Any],
    ) -> list[str]:
        """
        Check that every ``critical_field`` defined in the schema is present
        in the raw_payload (resolved through ``field_mapping``).

        Returns a list of missing critical field names (empty if all present).
        """
        field_mapping: dict[str, str] = schema.get("field_mapping", {})
        critical_fields: list[str] = schema.get("critical_fields", [])

        missing: list[str] = []
        for cf in critical_fields:
            source_path = field_mapping.get(cf)
            if source_path is None:
                missing.append(cf)
                continue
            value = resolve_path(raw_payload, source_path)
            if value is None:
                missing.append(cf)

        return missing
