from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any


SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN")


def canonical_severity(value: Any) -> str:
    """Return the API severity enum without changing pipeline outcomes."""

    if isinstance(value, bool) or value is None:
        return "UNKNOWN"
    normalized = str(value).strip().lower()
    if normalized in {"5", "critical", "kritisch"}:
        return "CRITICAL"
    if normalized in {"4", "high", "hoch"}:
        return "HIGH"
    if normalized in {"3", "medium", "mittel"}:
        return "MEDIUM"
    if normalized in {"1", "2", "low", "niedrig"}:
        return "LOW"
    return "UNKNOWN"


def severity_from_alert(document: dict[str, Any]) -> str:
    explicit = document.get("severity")
    if explicit is not None:
        return canonical_severity(explicit)
    payload = document.get("normalized_payload") or {}
    if not isinstance(payload, dict):
        return "UNKNOWN"
    value = payload.get("event.severity")
    nested = payload.get("event")
    if value is None and isinstance(nested, dict):
        value = nested.get("severity")
    return canonical_severity(value)


def literal_object_field_expression(
    field_name: str, *, input_expression: Any
) -> dict[str, Any]:
    """Read a literal dotted key using operators available in MongoDB 4.4."""

    return {
        "$let": {
            "vars": {
                "matches": {
                    "$filter": {
                        "input": {
                            "$objectToArray": {
                                "$ifNull": [input_expression, {}]
                            }
                        },
                        "as": "field",
                        "cond": {"$eq": ["$$field.k", field_name]},
                    }
                }
            },
            "in": {
                "$let": {
                    "vars": {"first": {"$arrayElemAt": ["$$matches", 0]}},
                    "in": "$$first.v",
                }
            },
        }
    }


def severity_expression() -> dict[str, Any]:
    flat = literal_object_field_expression(
        "event.severity", input_expression="$normalized_payload"
    )
    source = {
        "$ifNull": [
            "$severity",
            {"$ifNull": [flat, "$normalized_payload.event.severity"]},
        ]
    }
    normalized = {
        "$toLower": {
            "$trim": {
                "input": {
                    "$convert": {
                        "input": source,
                        "to": "string",
                        "onError": "",
                        "onNull": "",
                    }
                }
            }
        }
    }
    return {
        "$switch": {
            "branches": [
                {
                    "case": {"$in": [normalized, ["5", "critical", "kritisch"]]},
                    "then": "CRITICAL",
                },
                {
                    "case": {"$in": [normalized, ["4", "high", "hoch"]]},
                    "then": "HIGH",
                },
                {
                    "case": {"$in": [normalized, ["3", "medium", "mittel"]]},
                    "then": "MEDIUM",
                },
                {
                    "case": {
                        "$in": [normalized, ["1", "2", "low", "niedrig"]]
                    },
                    "then": "LOW",
                },
            ],
            "default": "UNKNOWN",
        }
    }


def host_from_alert(document: dict[str, Any]) -> str | None:
    payload = document.get("normalized_payload") or {}
    if not isinstance(payload, dict):
        return None
    value = payload.get("host.hostname")
    nested = payload.get("host")
    if value is None and isinstance(nested, dict):
        value = nested.get("hostname")
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def build_alert_query(
    *,
    q: str | None = None,
    since_hours: int | None = None,
    now: datetime | None = None,
) -> tuple[dict[str, Any], str]:
    query: dict[str, Any] = {}
    if since_hours is not None:
        current = now or datetime.now(timezone.utc)
        query["created_at"] = {"$gte": current - timedelta(hours=since_hours)}
    search = (q or "").strip()[:512]
    if search:
        pattern = re.compile(re.escape(search), re.IGNORECASE)
        query["$or"] = [
            {"alert_id": pattern},
            {"alert_type": pattern},
            {"source_system": pattern},
            {"fingerprint": pattern},
        ]
    return query, search


def aggregate_alert_stats(collection: Any, query: dict[str, Any]) -> dict[str, Any]:
    rows = list(
        collection.aggregate(
            [
                {"$match": query},
                {"$group": {"_id": severity_expression(), "count": {"$sum": 1}}},
            ]
        )
    )
    counts = {name: 0 for name in SEVERITIES}
    for row in rows:
        name = str(row.get("_id") or "UNKNOWN").upper()
        counts[name if name in counts else "UNKNOWN"] += int(row.get("count", 0))
    return {"filtered_total": sum(counts.values()), "severity": counts}
