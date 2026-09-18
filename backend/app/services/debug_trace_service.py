from __future__ import annotations

import math
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import mongoengine as me
from pymongo import ASCENDING, DESCENDING

from app.core.errors import ResourceNotFoundError

COLLECTION = "alert_processing_events"
STALLED_AFTER_SECONDS = 60
CORRELATION_ENABLED = os.getenv("CORRELATION_ENABLED", "false").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
LLM_ANALYSIS_ENABLED = os.getenv("LLM_ANALYSIS_ENABLED", "false").lower() in {
    "1",
    "true",
    "yes",
    "on",
}


def _iso(value: Any) -> Any:
    return value.isoformat() if isinstance(value, datetime) else value


def _serialize_span(raw: dict[str, Any]) -> dict[str, Any]:
    result = {key: value for key, value in raw.items() if key != "_id"}
    for key in ("started_at", "completed_at", "recorded_at", "expires_at"):
        if key in result:
            result[key] = _iso(result[key])
    return result


def _terminal_state(spans: list[dict[str, Any]]) -> str:
    if any(span.get("outcome") == "FAILED" for span in spans):
        return "FAILED"
    terminal_stage = (
        "ANALYSIS"
        if LLM_ANALYSIS_ENABLED
        else ("CORRELATION" if CORRELATION_ENABLED else "ENRICHMENT")
    )
    if any(
        span.get("stage") == terminal_stage and span.get("outcome") == "SUCCEEDED"
        for span in spans
    ):
        return "SUCCEEDED"
    running = [span for span in spans if span.get("outcome") == "RUNNING"]
    if running:
        started = [span.get("started_at") for span in running if span.get("started_at")]
        oldest = min(started) if started else None
        if isinstance(oldest, str):
            oldest = datetime.fromisoformat(oldest.replace("Z", "+00:00"))
        if isinstance(oldest, datetime) and oldest.tzinfo is None:
            oldest = oldest.replace(tzinfo=timezone.utc)
        if oldest and datetime.now(timezone.utc) - oldest > timedelta(
            seconds=STALLED_AFTER_SECONDS
        ):
            return "STALLED"
    return "RUNNING"


def _processing_duration_ms(spans: list[dict[str, Any]]) -> float | None:
    durations = [
        float(duration)
        for span in spans
        if span.get("completed_at") is not None
        and isinstance((duration := span.get("duration_ms")), (int, float))
        and not isinstance(duration, bool)
        and math.isfinite(float(duration))
        and duration >= 0
    ]
    return round(sum(durations), 3) if durations else None


class DebugTraceService:
    @staticmethod
    def _collection():
        return me.connection.get_db("default")[COLLECTION]

    @classmethod
    def ensure_indexes(cls) -> None:
        collection = cls._collection()
        collection.create_index("span_id", unique=True)
        collection.create_index(
            [("alert_id", ASCENDING), ("sequence", ASCENDING), ("started_at", ASCENDING)]
        )
        collection.create_index([("tenant_id", ASCENDING), ("started_at", DESCENDING)])
        collection.create_index([("release_version", ASCENDING), ("started_at", DESCENDING)])
        collection.create_index([("release_sha", ASCENDING), ("started_at", DESCENDING)])
        collection.create_index("expires_at", expireAfterSeconds=0)

    @classmethod
    def _summary(cls, spans: list[dict[str, Any]]) -> dict[str, Any]:
        ordered = sorted(
            spans,
            key=lambda item: (item.get("sequence", 0), str(item.get("started_at", ""))),
        )
        first = ordered[0]
        current = max(ordered, key=lambda item: item.get("sequence", 0))
        started_values = [span.get("started_at") for span in ordered if span.get("started_at")]
        completed_values = [
            span.get("completed_at") for span in ordered if span.get("completed_at")
        ]
        release_versions = sorted(
            {
                str(span["release_version"])
                for span in ordered
                if span.get("release_version")
            }
        )
        release_shas = sorted(
            {str(span["release_sha"]) for span in ordered if span.get("release_sha")}
        )
        version_metadata_incomplete = bool(release_versions) and any(
            not span.get("release_version") for span in ordered
        )
        sha_metadata_incomplete = bool(release_shas) and any(
            not span.get("release_sha") for span in ordered
        )
        return {
            "alert_id": first.get("alert_id"),
            "tenant_id": first.get("tenant_id"),
            "alert_type": first.get("alert_type"),
            "source_system": first.get("source_system"),
            "current_stage": current.get("stage"),
            "current_outcome": current.get("outcome"),
            "terminal_state": _terminal_state(ordered),
            "first_seen_at": _iso(min(started_values)) if started_values else None,
            "last_seen_at": _iso(max(completed_values or started_values))
            if completed_values or started_values
            else None,
            "processing_duration_ms": _processing_duration_ms(ordered),
            "span_count": len(ordered),
            "release_sha": release_shas[0] if len(release_shas) == 1 else None,
            "release_version": (
                release_versions[0]
                if len(release_versions) == 1 and not version_metadata_incomplete
                else None
            ),
            "release_versions": release_versions,
            "release_shas": release_shas,
            "mixed_releases": (
                len(release_versions) > 1
                or len(release_shas) > 1
                or version_metadata_incomplete
                or sha_metadata_incomplete
            ),
        }

    @classmethod
    def list_traces(
        cls,
        *,
        tenant_id: Optional[str] = None,
        alert_id: Optional[str] = None,
        stage: Optional[str] = None,
        outcome: Optional[str] = None,
        release_version: Optional[str] = None,
        release_sha: Optional[str] = None,
        since_hours: Optional[int] = 24,
        skip: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        query: dict[str, Any] = {}
        if tenant_id:
            query["tenant_id"] = tenant_id
        if alert_id:
            query["alert_id"] = alert_id
        if stage:
            query["stage"] = stage
        if outcome:
            query["outcome"] = outcome
        if release_version:
            query["release_version"] = release_version
        if release_sha:
            query["release_sha"] = release_sha
        if since_hours:
            query["started_at"] = {
                "$gte": datetime.now(timezone.utc) - timedelta(hours=since_hours)
            }

        collection = cls._collection()
        matched_ids = collection.distinct("alert_id", query)
        grouped: dict[str, list[dict[str, Any]]] = {}
        cursor = collection.find({"alert_id": {"$in": matched_ids}}).limit(5000)
        for span in cursor:
            grouped.setdefault(span["alert_id"], []).append(span)

        summaries = [cls._summary(spans) for spans in grouped.values()]
        summaries.sort(key=lambda item: str(item.get("last_seen_at", "")), reverse=True)
        return {
            "items": summaries[skip : skip + limit],
            "total": len(summaries),
            "skip": skip,
            "limit": limit,
        }

    @classmethod
    def get_trace(cls, alert_id: str) -> dict[str, Any]:
        spans = list(
            cls._collection()
            .find({"alert_id": alert_id})
            .sort([("sequence", ASCENDING), ("started_at", ASCENDING)])
        )
        if not spans:
            raise ResourceNotFoundError(
                "Trace unavailable: this alert may predate trace instrumentation."
            )
        serialized = [_serialize_span(span) for span in spans]
        return {
            "summary": cls._summary(spans),
            "spans": serialized,
            "pipeline_boundary": (
                "Automated response and action execution are not implemented."
                if LLM_ANALYSIS_ENABLED
                else (
                    "No downstream LLM analysis worker is currently implemented."
                    if CORRELATION_ENABLED
                    else "No downstream correlation or LLM analysis worker is currently implemented."
                )
            ),
        }
