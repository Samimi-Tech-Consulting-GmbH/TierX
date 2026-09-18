from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable
from uuid import uuid4

from app.core.config import settings

TracePublisher = Callable[[dict[str, Any]], Awaitable[None]]

STAGE_SEQUENCES = {
    "VALIDATION": 20,
    "NORMALIZATION": 30,
    "FINGERPRINT": 40,
    "ENRICHMENT": 50,
    "ENRICHMENT_ACTION": 55,
    "CORRELATION": 60,
    "ANALYSIS": 70,
    "DEAD_LETTER": 80,
}

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
    "prompt_footer",
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


def _json_safe(value: Any) -> Any:
    """Redact and normalize arbitrary trace metadata before Kafka serialization."""
    return json.loads(json.dumps(_redact(value), default=str, separators=(",", ":")))


def snapshot(value: Any) -> dict[str, Any]:
    safe = _json_safe(value)
    encoded_text = json.dumps(safe, separators=(",", ":"))
    encoded = encoded_text.encode("utf-8")
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
        publisher: TracePublisher,
        stage: str,
        service: str,
        data: dict[str, Any],
    ) -> None:
        self.publisher = publisher
        self.stage = stage
        self.service = service
        self.data = data
        self.span_id = str(uuid4())
        self.started_at = datetime.now(timezone.utc)
        self.started_monotonic = time.monotonic()
        self.finished = False

    def _base(self) -> dict[str, Any]:
        return {
            "span_id": self.span_id,
            "alert_id": self.data.get("alert_id", "unknown"),
            "tenant_id": self.data.get("tenant_id"),
            "alert_type": self.data.get("alert_type"),
            "source_system": self.data.get("source_system"),
            "stage": self.stage,
            "sequence": STAGE_SEQUENCES[self.stage],
            "service": self.service,
            "release_sha": settings.app_release_sha,
            "release_version": settings.app_release_version,
            "started_at": self.started_at.isoformat(),
            "input_snapshot": snapshot(self.data),
        }

    async def __aenter__(self) -> "TraceSpan":
        if settings.debug_trace_enabled:
            await self.publisher(
                {**self._base(), "phase": "STARTED", "outcome": "RUNNING"}
            )
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> bool:
        if exc is not None and not self.finished:
            await self.finish(
                "FAILED",
                error={
                    "type": "INTERNAL_ERROR",
                    "detail": str(exc),
                },
            )
        return False

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
        if not settings.debug_trace_enabled:
            return
        event = {
            **self._base(),
            "phase": "COMPLETED",
            "outcome": outcome,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "duration_ms": round((time.monotonic() - self.started_monotonic) * 1000, 3),
            "checks": _json_safe(checks or []),
            "decisions": _json_safe(decisions or {}),
        }
        if output_value is not None:
            event["output_snapshot"] = snapshot(output_value)
        if error:
            event["error"] = _json_safe(error)
        await self.publisher(event)
