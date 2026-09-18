"""Idempotently repair an explicitly selected historical correlation failure."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from aiokafka import AIOKafkaProducer

from app.core.config import settings
from app.db.mongodb import close_client, get_client, get_database
from app.schemas.messages import ClusteredAlertMessage
from app.workers.correlation_worker import (
    ALERTS_COLLECTION,
    CLUSTERS_COLLECTION,
    as_utc,
    display_pair,
    extract_correlation_values,
    match_entities,
    parse_severity,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Repair exactly two historical alerts that should have correlated."
    )
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--alert-id", action="append", required=True)
    parser.add_argument("--operator", required=True)
    parser.add_argument("--dry-run", action="store_true")
    return parser


async def _publish(message: dict[str, Any]) -> None:
    producer = AIOKafkaProducer(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        value_serializer=lambda value: json.dumps(value).encode("utf-8"),
        key_serializer=lambda value: value.encode("utf-8"),
    )
    await producer.start()
    try:
        await producer.send_and_wait(
            settings.kafka_clustered_topic,
            message,
            key=str(message["tenant_id"]),
        )
    finally:
        await producer.stop()


async def repair(args: argparse.Namespace) -> dict[str, Any]:
    alert_ids = sorted(set(args.alert_id))
    if len(alert_ids) != 2:
        raise ValueError("Exactly two distinct --alert-id values are required")

    tenant = await get_database()["tenants"].find_one(
        {"tenant_id": args.tenant_id, "status": "ACTIVE"},
        {"_id": 0, "db_name": 1},
    )
    if not tenant:
        raise ValueError("Active tenant not found")
    db = get_client()[tenant["db_name"]]
    alerts = await db[ALERTS_COLLECTION].find(
        {"tenant_id": args.tenant_id, "alert_id": {"$in": alert_ids}},
        {"_id": 0, "raw_payload": 0},
    ).to_list(length=None)
    if sorted(str(alert["alert_id"]) for alert in alerts) != alert_ids:
        raise ValueError("Both alerts must exist in the selected tenant")

    cluster_ids = {str(alert["cluster_id"]) for alert in alerts if alert.get("cluster_id")}
    cluster_id = str(
        uuid5(
            NAMESPACE_URL,
            f"soc-mind-correlation-repair:{args.tenant_id}:{':'.join(alert_ids)}",
        )
    )
    if cluster_ids:
        if cluster_ids != {cluster_id}:
            raise ValueError("At least one alert already belongs to another cluster")
        existing = await db[CLUSTERS_COLLECTION].find_one(
            {"cluster_id": cluster_id}, {"_id": 0}
        )
        if not existing:
            raise ValueError("Alert membership references a missing repair cluster")
        pending = existing.get("pending_analysis_request")
        if pending and not args.dry_run:
            await _publish(pending)
            now = datetime.now(timezone.utc)
            await db[CLUSTERS_COLLECTION].update_one(
                {"cluster_id": cluster_id},
                {
                    "$max": {
                        "published_analysis_version": pending[
                            "requested_analysis_version"
                        ]
                    },
                    "$unset": {"pending_analysis_request": ""},
                    "$set": {"analysis_status": "PENDING", "updated_at": now},
                },
            )
        return {
            "status": "ALREADY_REPAIRED",
            "cluster_id": cluster_id,
            "alert_ids": alert_ids,
            "pending_request_republished": bool(pending and not args.dry_run),
        }

    ordered = sorted(
        alerts,
        key=lambda alert: (
            as_utc(alert.get("created_at")),
            str(alert["alert_id"]),
        ),
    )
    first_seen = as_utc(ordered[0].get("created_at"))
    last_seen = as_utc(ordered[-1].get("created_at"))
    if last_seen - first_seen > timedelta(hours=settings.correlation_lookback_hours):
        raise ValueError("The alerts were not originally within the correlation window")

    first_entities, first_techniques = extract_correlation_values(
        ordered[0].get("normalized_payload") or {}
    )
    shared_entities, shared_techniques = match_entities(
        first_entities,
        first_techniques,
        ordered[1].get("normalized_payload") or {},
    )
    if not shared_entities and not shared_techniques:
        raise ValueError("The selected alerts have no deterministic correlation overlap")

    severity_values = [
        parse_severity(
            (alert.get("normalized_payload") or {}).get("event.severity")
        )
        for alert in ordered
    ]
    severity_distribution = Counter(map(str, severity_values))
    now = datetime.now(timezone.utc)
    request = ClusteredAlertMessage(
        alert_id=str(ordered[0]["alert_id"]),
        tenant_id=args.tenant_id,
        cluster_id=cluster_id,
        analysis_type="CLUSTER_ANALYSIS",
        debounce_outcome="EXPIRED_WITH_CLUSTER",
        requested_analysis_version=1,
        trigger_reason="WINDOW_CAP",
        is_final=True,
    ).model_dump()
    preview = {
        "status": "DRY_RUN" if args.dry_run else "REPAIRED",
        "cluster_id": cluster_id,
        "alert_ids": alert_ids,
        "shared_entities": sorted(map(display_pair, shared_entities)),
        "mitre_techniques": sorted(shared_techniques),
        "first_seen": first_seen.isoformat(),
        "last_seen": last_seen.isoformat(),
        "request": request,
    }
    if args.dry_run:
        return preview

    cluster = {
        "cluster_id": cluster_id,
        "tenant_id": args.tenant_id,
        "lead_alert_id": str(ordered[0]["alert_id"]),
        "alert_ids": alert_ids,
        "alert_count": 2,
        "is_open_for_grouping": False,
        "debounce_expires_at": first_seen,
        "grouping_window_expires_at": first_seen
        + timedelta(hours=settings.correlation_lookback_hours),
        "correlation_basis": {
            "method": "ENTITY_OVERLAP",
            "shared_entities": preview["shared_entities"],
            "mitre_techniques": preview["mitre_techniques"],
        },
        "first_seen": first_seen,
        "last_seen": last_seen,
        "window_seconds": int((last_seen - first_seen).total_seconds()),
        "severity": {
            "max": max(severity_values),
            "avg": sum(severity_values) / len(severity_values),
            "distribution": dict(severity_distribution),
        },
        "debounce_outcome": "EXPIRED_WITH_CLUSTER",
        "analysis_type": "CLUSTER_ANALYSIS",
        "clustering_status": "CORRELATED",
        "analyzed_version": 0,
        "analyzed_alert_count": 0,
        "requested_analysis_version": 1,
        "published_analysis_version": 0,
        "pending_analysis_request": request,
        "analysis_status": "PENDING",
        "status": "OPEN",
        "assigned_to": None,
        "escalated_to": None,
        "verdict": None,
        "analyst_notes": [],
        "created_at": first_seen,
        "updated_at": now,
        "closed_at": now,
        "correlation_repair": {
            "operator": args.operator,
            "repaired_at": now,
            "release_sha": settings.app_release_sha,
            "release_version": settings.app_release_version,
            "reason": "Historical timezone-comparison failure",
        },
    }
    await db[CLUSTERS_COLLECTION].create_index("cluster_id", unique=True)
    await db[CLUSTERS_COLLECTION].create_index("alert_ids", unique=True, sparse=True)
    await db[CLUSTERS_COLLECTION].insert_one(cluster)
    update = await db[ALERTS_COLLECTION].update_many(
        {"tenant_id": args.tenant_id, "alert_id": {"$in": alert_ids}, "cluster_id": None},
        {
            "$set": {
                "cluster_id": cluster_id,
                "clustering_status": "CORRELATED",
                "analysis_type": "CLUSTER_ANALYSIS",
                "debounce_outcome": "EXPIRED_WITH_CLUSTER",
                "requested_analysis_version": 1,
                "analysis_status": "PENDING",
                "status": "ANALYZING",
                "kafka_state": "CLUSTERED",
                "updated_at": now,
            }
        },
    )
    if update.modified_count != 2:
        await db[CLUSTERS_COLLECTION].delete_one({"cluster_id": cluster_id})
        raise RuntimeError("Alert membership changed during repair; no repair was applied")

    await _publish(request)
    await db[CLUSTERS_COLLECTION].update_one(
        {"cluster_id": cluster_id},
        {
            "$max": {"published_analysis_version": 1},
            "$unset": {"pending_analysis_request": ""},
            "$set": {"updated_at": datetime.now(timezone.utc)},
        },
    )
    return preview


async def _main() -> int:
    args = _parser().parse_args()
    try:
        print(json.dumps(await repair(args), indent=2, default=str))
        return 0
    finally:
        await close_client()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
