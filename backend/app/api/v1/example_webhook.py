from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pymongo import ASCENDING
from pymongo.errors import DuplicateKeyError

from app.services.webhook_signing_service import WebhookSigningService
from app.core.brand_compat import compatible_header

router = APIRouter(prefix="/examples", tags=["Examples"])


class ReferenceAlert(BaseModel):
    model_config = ConfigDict(extra="forbid")
    alert_id: str
    alert_type: str
    source_system: str
    fingerprint: str
    normalized_payload: dict[str, Any]


class ReferencePlaybook(BaseModel):
    model_config = ConfigDict(extra="forbid")
    playbook_id: str
    version: int = Field(ge=1)


class ReferenceRelease(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str
    sha: str


class ReferenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    spec_version: str
    delivery_id: str
    sent_at: datetime
    tenant_id: str
    alert: ReferenceAlert
    playbook: ReferencePlaybook
    release: ReferenceRelease


def _scalar(payload: dict[str, Any], dotted: str) -> str | None:
    value: Any = payload
    for part in dotted.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    if isinstance(value, (str, int, float, bool)) and str(value).strip():
        return str(value)
    return None


def _sample_footer(body: ReferenceRequest) -> str:
    payload = body.alert.normalized_payload
    evidence = []
    for field in ("host.hostname", "source.ip", "destination.ip", "user.name"):
        value = _scalar(payload, field)
        if value is not None:
            evidence.append(f"{field}={value}")
    suffix = "; ".join(evidence) if evidence else "no selected reference fields present"
    return (
        "Reference webhook context: analyze alert "
        f"{body.alert.alert_id} as {body.alert.alert_type} from "
        f"{body.alert.source_system}. Observed normalized evidence: {suffix}."
    )


@router.post("/playbook-context-webhook")
async def playbook_context_webhook(
    request: Request,
) -> dict[str, str]:
    version = compatible_header(request, "webhook-version", required=True)
    delivery_id = compatible_header(request, "delivery-id", required=True)
    timestamp_header = compatible_header(request, "timestamp", required=True)
    key_id = compatible_header(request, "key-id", required=True)
    signature = compatible_header(request, "signature", required=True)
    assert version and delivery_id and timestamp_header and key_id and signature
    if not WebhookSigningService.enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    if version != "1" or not signature.startswith("v1="):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")
    try:
        UUID(delivery_id)
        signed_at = int(timestamp_header)
    except (ValueError, TypeError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid delivery metadata")
    tolerance = int(os.getenv("PLAYBOOK_WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS", "300"))
    if abs(int(time.time()) - signed_at) > tolerance:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Expired signature")

    raw = await request.body()
    if len(raw) > int(os.getenv("PLAYBOOK_WEBHOOK_MAX_REQUEST_BYTES", "262144")):
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Request too large")
    try:
        parsed = ReferenceRequest.model_validate_json(raw)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors(include_input=False))
    if parsed.spec_version != "1.0" or parsed.delivery_id != delivery_id:
        raise HTTPException(status_code=400, detail="Delivery metadata mismatch")

    credential = WebhookSigningService.resolve_by_key_id(
        parsed.tenant_id, parsed.playbook.playbook_id, key_id
    )
    if not credential:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")
    signing_input = timestamp_header.encode() + b"." + delivery_id.encode() + b"." + raw
    expected = hmac.new(
        credential["secret"].encode(), signing_input, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(signature[3:], expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")

    footer = _sample_footer(parsed)
    response_sha = hashlib.sha256(footer.encode()).hexdigest()
    collection = WebhookSigningService._database(parsed.tenant_id)[
        "webhook_reference_deliveries"
    ]
    collection.create_index([("delivery_id", ASCENDING)], unique=True)
    collection.create_index(
        [("expires_at", ASCENDING)], expireAfterSeconds=0
    )
    request_sha = hashlib.sha256(raw).hexdigest()
    existing = collection.find_one({"delivery_id": delivery_id}, {"_id": 0})
    if existing:
        return {"prompt_footer": existing["prompt_footer"]}
    try:
        collection.insert_one(
            {
                "delivery_id": delivery_id,
                "tenant_id": parsed.tenant_id,
                "playbook_id": parsed.playbook.playbook_id,
                "request_sha256": request_sha,
                "response_sha256": response_sha,
                "prompt_footer": footer,
                "created_at": datetime.now(timezone.utc),
                "expires_at": datetime.now(timezone.utc) + timedelta(days=7),
            }
        )
    except DuplicateKeyError:
        existing = collection.find_one({"delivery_id": delivery_id}, {"_id": 0})
        if existing:
            return {"prompt_footer": existing["prompt_footer"]}
        raise
    return {"prompt_footer": footer}
