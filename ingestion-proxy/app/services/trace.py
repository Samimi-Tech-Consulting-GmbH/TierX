from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.core.config import settings
from app.services.kafka_publisher import kafka_publisher

REDACTED_KEYS = {
    "authorization",
    "password",
    "token",
    "access_token",
    "jwt",
    "jwt_secret_key",
    "mongo_url",
    "database_url",
    "mongodb_url",
    "db_url",
}


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            name = str(key)
            normalized = name.lower()
            is_sensitive = (
                normalized in REDACTED_KEYS
                or "password" in normalized
                or "secret" in normalized
                or normalized.endswith("_token")
                or normalized.endswith("_api_key")
                or normalized in {"cookie", "set-cookie"}
            )
            redacted[name] = "[REDACTED]" if is_sensitive else _redact(item)
        return redacted
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def snapshot(value: Any) -> dict[str, Any]:
    safe = _redact(value)
    encoded = json.dumps(safe, default=str, separators=(",", ":")).encode("utf-8")
    limit = settings.debug_trace_max_snapshot_bytes
    if len(encoded) <= limit:
        return {"value": safe, "truncated": False, "size_bytes": len(encoded)}
    return {
        "value": encoded[:limit].decode("utf-8", errors="replace"),
        "truncated": True,
        "size_bytes": len(encoded),
        "sha256": hashlib.sha256(encoded).hexdigest(),
    }


class TraceSpan:
    def __init__(
        self,
        *,
        alert_id: str,
        tenant_id: str | None,
        alert_type: str | None,
        source_system: str | None,
        input_value: Any,
        submitted_by: str | None = None,
    ) -> None:
        self.span_id = str(uuid4())
        self.alert_id = alert_id
        self.tenant_id = tenant_id
        self.alert_type = alert_type
        self.source_system = source_system
        self.input_snapshot = snapshot(input_value)
        self.submitted_by = submitted_by
        self.started_at = datetime.now(timezone.utc)
        self.started_monotonic = time.monotonic()
        self.finished = False

    def _base(self) -> dict[str, Any]:
        return {
            "span_id": self.span_id,
            "alert_id": self.alert_id,
            "tenant_id": self.tenant_id,
            "alert_type": self.alert_type,
            "source_system": self.source_system,
            "stage": "INGESTION",
            "sequence": 10,
            "service": "ingestion-proxy",
            "release_sha": settings.app_release_sha,
            "release_version": settings.app_release_version,
            "submitted_by": self.submitted_by,
            "started_at": self.started_at.isoformat(),
            "input_snapshot": self.input_snapshot,
        }

    async def start(self) -> None:
        if not settings.debug_trace_enabled:
            return
        await kafka_publisher.publish_trace(
            {**self._base(), "phase": "STARTED", "outcome": "RUNNING"}
        )

    async def finish(
        self,
        outcome: str,
        *,
        output_value: Any = None,
        checks: list[dict[str, Any]] | None = None,
        decisions: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
    ) -> None:
        if self.finished:
            return
        self.finished = True
        completed_at = datetime.now(timezone.utc)
        event = {
            **self._base(),
            "phase": "COMPLETED",
            "outcome": outcome,
            "completed_at": completed_at.isoformat(),
            "duration_ms": round((time.monotonic() - self.started_monotonic) * 1000, 3),
            "checks": checks or [],
            "decisions": decisions or {},
        }
        if output_value is not None:
            event["output_snapshot"] = snapshot(output_value)
        if error:
            event["error"] = error
        await kafka_publisher.publish_trace(event)
