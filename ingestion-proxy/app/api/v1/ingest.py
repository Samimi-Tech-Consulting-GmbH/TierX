from datetime import datetime, timezone
from uuid import uuid4
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.schemas.alert import (
    DeadLetterMessage,
    ErrorType,
    IngestAlertRequest,
    IngestAlertResponse,
    ReceivedAlertMessage,
)
from app.services.kafka_publisher import kafka_publisher
from app.services.tenant_cache import tenant_cache
from app.core.brand_compat import compatible_header

router = APIRouter()


async def _dead_letter(
    raw: dict,
    alert_id: str,
    error_type: ErrorType,
    error_detail: str,
) -> JSONResponse:
    now = datetime.now(timezone.utc).isoformat()

    dlq_message = DeadLetterMessage(
        alert_id=alert_id,
        tenant_id=raw.get("tenant_id"),
        alert_type=raw.get("alert_type"),
        source_system=raw.get("source_system"),
        raw_payload=raw.get("raw_payload"),
        dead_lettered_at=now,
        error_type=error_type,
        error_detail=error_detail,
    )

    await kafka_publisher.publish_dead_letter(dlq_message.model_dump())

    return JSONResponse(
        status_code=422,
        content={
            "alert_id": alert_id,
            "status": "FAILED",
            "kafka_state": "DLQ",
            "error_type": error_type.value,
            "error_detail": error_detail,
        },
    )


@router.post(
    "/ingest",
    summary="Ingest raw alert",
    responses={
        200: {"model": IngestAlertResponse},
        422: {"description": "Validation failed; alert published to dead-letter queue"},
    },
)
async def ingest_alert(request: Request):
    parsed = await request.json()
    raw: dict = parsed if isinstance(parsed, dict) else {"payload": parsed}
    requested_alert_id = compatible_header(request, "requested-alert-id")
    try:
        alert_id = str(UUID(requested_alert_id)) if requested_alert_id else str(uuid4())
    except (ValueError, TypeError, AttributeError):
        alert_id = str(uuid4())
    submitted_by = compatible_header(request, "debug-actor")

    from app.services.trace import TraceSpan

    span = TraceSpan(
        alert_id=alert_id,
        tenant_id=raw.get("tenant_id"),
        alert_type=raw.get("alert_type"),
        source_system=raw.get("source_system"),
        input_value=raw,
        submitted_by=submitted_by,
    )
    await span.start()
    checks: list[dict] = []

    try:
        body = IngestAlertRequest.model_validate(raw)
    except ValidationError as exc:
        detail = str(exc)
        checks.append({"name": "envelope_validation", "outcome": "FAILED", "detail": detail})
        await span.finish(
            "FAILED",
            checks=checks,
            error={"type": ErrorType.ALERT_SCHEMA_MISSING.value, "detail": detail},
        )
        return await _dead_letter(
            raw, alert_id, ErrorType.ALERT_SCHEMA_MISSING, detail,
        )
    checks.append({"name": "envelope_validation", "outcome": "SUCCEEDED"})

    if not tenant_cache.is_active_tenant(body.tenant_id):
        detail = f"tenant_id '{body.tenant_id}' is not an active tenant"
        checks.append({"name": "tenant_active", "outcome": "FAILED", "detail": detail})
        await span.finish(
            "FAILED",
            checks=checks,
            error={"type": ErrorType.UNKNOWN_TENANT.value, "detail": detail},
        )
        return await _dead_letter(
            raw, alert_id, ErrorType.UNKNOWN_TENANT, detail,
        )
    checks.append({"name": "tenant_active", "outcome": "SUCCEEDED"})

    if not tenant_cache.is_source_allowed(body.tenant_id, body.source_system):
        allowed = tenant_cache.get_allowed_sources(body.tenant_id)
        detail = (
            f"source_system '{body.source_system}' is not allowed for tenant "
            f"'{body.tenant_id}'. Allowed sources: {sorted(allowed)}"
        )
        checks.append({"name": "source_allowed", "outcome": "FAILED", "detail": detail})
        await span.finish(
            "FAILED",
            checks=checks,
            decisions={"allowed_sources": sorted(allowed)},
            error={"type": ErrorType.UNKNOWN_SOURCE.value, "detail": detail},
        )
        return await _dead_letter(
            raw, alert_id, ErrorType.UNKNOWN_SOURCE, detail,
        )
    checks.append({"name": "source_allowed", "outcome": "SUCCEEDED"})

    message = ReceivedAlertMessage(
        alert_id=alert_id,
        tenant_id=body.tenant_id,
        alert_type=body.alert_type,
        source_system=body.source_system,
        raw_payload=body.raw_payload,
        source_reference=body.source_reference,
    )

    await kafka_publisher.publish_received(message.model_dump())
    checks.append({"name": "kafka_publish_received", "outcome": "SUCCEEDED"})
    await span.finish(
        "SUCCEEDED",
        output_value=message.model_dump(),
        checks=checks,
        decisions={"received_topic": "received"},
    )

    return IngestAlertResponse(
        alert_id=alert_id,
        tenant_id=body.tenant_id,
        source_system=body.source_system,
        alert_type=body.alert_type,
        raw_payload=body.raw_payload,
        timestamp=body.timestamp,
        source_reference=body.source_reference,
        kafka_state="RECEIVED",
        status="RECEIVED",
    )
