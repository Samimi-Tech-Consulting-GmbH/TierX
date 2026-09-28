"""Deterministic entity-overlap correlation and cluster lifecycle worker."""

from __future__ import annotations

import asyncio
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable
from uuid import uuid4

from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.errors import PyMongoError

from app.core.config import settings
from app.db.mongodb import get_client, get_database
from app.schemas.messages import ClusteredAlertMessage, EnrichedAlertMessage
from app.services.schema_registry import get_tenant_db_name
from app.workers.base import BaseWorker

ALERTS_COLLECTION = "alerts"
CLUSTERS_COLLECTION = "clusters"
ANALYSIS_RUNS_COLLECTION = "analysis_runs"

ENTITY_FIELDS = (
    "host.id",
    "host.name",
    "host.hostname",
    "host.ip",
    "host.mac",
    "user.id",
    "user.name",
    "user.email",
    "user.domain",
    "source.ip",
    "destination.ip",
    "client.ip",
    "server.ip",
    "network.community_id",
    "file.hash.sha256",
    "file.hash.md5",
    "file.hash.sha1",
    "file.path",
    "file.name",
    "process.entity_id",
    "process.hash.sha256",
    "process.command_line",
    "process.parent.entity_id",
    "dns.question.name",
    "url.domain",
    "url.full",
    "user_agent.original",
    "email.message_id",
    "email.from.address",
    "email.to.address",
    "email.subject",
    "cloud.instance.id",
    "cloud.account.id",
    "container.id",
    "orchestrator.namespace",
    "threat.indicator.ip",
    "threat.indicator.domain",
    "threat.indicator.url.full",
    "threat.indicator.file.hash.sha256",
    "threat.indicator.file.hash.md5",
    "threat.indicator.file.hash.sha1",
)
DYNAMIC_PREFIXES = ("user.target",)
MITRE_FIELDS = ("threat.technique.id",)
DEFAULT_DEBOUNCE_MS = {
    5: settings.correlation_debounce_critical_ms,
    4: settings.correlation_debounce_high_ms,
    3: settings.correlation_debounce_medium_ms,
    2: settings.correlation_debounce_low_ms,
    1: settings.correlation_debounce_low_ms,
}
SEVERITY_NAMES = {"critical": 5, "high": 4, "medium": 3, "low": 1}


def _resolve(document: dict[str, Any], path: str) -> Any:
    if path in document:
        return document[path]
    current: Any = document
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _scalars(value: Any) -> Iterable[Any]:
    if value is None:
        return
    if isinstance(value, list):
        for item in value:
            yield from _scalars(item)
        return
    if isinstance(value, dict):
        for key in sorted(value):
            yield from _scalars(value[key])
        return
    if isinstance(value, str) and not value.strip():
        return
    yield value


def _scalar_key(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _dynamic_leaves(value: Any, prefix: str) -> Iterable[tuple[str, Any]]:
    if isinstance(value, dict):
        for key in sorted(value):
            yield from _dynamic_leaves(value[key], f"{prefix}.{key}")
    elif isinstance(value, list):
        for item in value:
            yield from _dynamic_leaves(item, prefix)
    elif value is not None and not (isinstance(value, str) and not value.strip()):
        yield prefix, value


def extract_correlation_values(
    normalized: dict[str, Any],
) -> tuple[set[tuple[str, str]], set[str]]:
    """Return typed exact-match entity pairs and MITRE technique values."""
    entities: set[tuple[str, str]] = set()
    for field in ENTITY_FIELDS:
        for value in _scalars(_resolve(normalized, field)):
            entities.add((field, _scalar_key(value)))
    for prefix in DYNAMIC_PREFIXES:
        value = _resolve(normalized, prefix)
        for field, scalar in _dynamic_leaves(value, prefix):
            entities.add((field, _scalar_key(scalar)))

    techniques: set[str] = set()
    for field in MITRE_FIELDS:
        for value in _scalars(_resolve(normalized, field)):
            techniques.add(str(value))
    return entities, techniques


def display_pair(pair: tuple[str, str]) -> str:
    field, encoded = pair
    try:
        value = json.loads(encoded)
    except json.JSONDecodeError:
        value = encoded
    return f"{field}:{value}"


def as_utc(value: datetime | None, *, fallback: datetime | None = None) -> datetime:
    """Return an aware UTC datetime, including for legacy naive Mongo values."""
    candidate = value or fallback
    if candidate is None:
        raise ValueError("A timestamp is required")
    if candidate.tzinfo is None:
        return candidate.replace(tzinfo=timezone.utc)
    return candidate.astimezone(timezone.utc)


def parse_severity(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("Boolean severity is not supported")
    if isinstance(value, (int, float)) and int(value) == value:
        number = int(value)
    elif isinstance(value, str):
        stripped = value.strip().lower()
        if stripped in SEVERITY_NAMES:
            number = SEVERITY_NAMES[stripped]
        elif stripped.isdigit():
            number = int(stripped)
        else:
            raise ValueError(f"Unsupported severity value: {value!r}")
    else:
        raise ValueError(f"Unsupported severity value: {value!r}")
    if number not in {1, 2, 3, 4, 5}:
        raise ValueError(f"Severity must be between 1 and 5, got {number}")
    return number


def debounce_ms(severity: int, tenant_settings: dict[str, Any]) -> int:
    names = {
        5: "correlation_debounce_critical_ms",
        4: "correlation_debounce_high_ms",
        3: "correlation_debounce_medium_ms",
        2: "correlation_debounce_low_ms",
        1: "correlation_debounce_low_ms",
    }
    raw = tenant_settings.get(names[severity], DEFAULT_DEBOUNCE_MS[severity])
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        raise ValueError(f"{names[severity]} must be a non-negative integer")
    return raw


def match_entities(
    incoming_entities: set[tuple[str, str]],
    incoming_techniques: set[str],
    candidate_payload: dict[str, Any],
) -> tuple[set[tuple[str, str]], set[str]]:
    candidate_entities, candidate_techniques = extract_correlation_values(
        candidate_payload
    )
    return (
        incoming_entities & candidate_entities,
        incoming_techniques & candidate_techniques,
    )


class CorrelationClusteringWorker(BaseWorker):
    def __init__(self):
        super().__init__(
            name="correlation",
            input_topic=settings.kafka_enriched_topic,
            output_topic=settings.kafka_clustered_topic,
        )
        self._scheduler_task: asyncio.Task | None = None
        self._indexed_databases: set[str] = set()

    async def start(self):
        await super().start()
        self._scheduler_task = asyncio.create_task(
            self._scheduler_loop(), name="correlation-scheduler"
        )

    async def stop(self):
        if self._scheduler_task and not self._scheduler_task.done():
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass
        await super().stop()

    async def _tenant(self, tenant_id: str) -> dict[str, Any]:
        tenant = await get_database()["tenants"].find_one(
            {"tenant_id": tenant_id, "status": "ACTIVE"},
            {"db_name": 1, "settings": 1, "_id": 0},
        )
        if not tenant:
            raise ValueError(f"Active tenant not found: {tenant_id}")
        return tenant

    async def _ensure_indexes(self, db_name: str):
        if db_name in self._indexed_databases:
            return
        db = get_client()[db_name]
        await db[ALERTS_COLLECTION].create_index(
            [("tenant_id", ASCENDING), ("created_at", DESCENDING)]
        )
        await db[ALERTS_COLLECTION].create_index("alert_id", unique=True)
        await db[CLUSTERS_COLLECTION].create_index("cluster_id", unique=True)
        await db[CLUSTERS_COLLECTION].create_index(
            "alert_ids", unique=True, sparse=True
        )
        await db[CLUSTERS_COLLECTION].create_index(
            [
                ("tenant_id", ASCENDING),
                ("is_open_for_grouping", ASCENDING),
                ("grouping_window_expires_at", ASCENDING),
            ]
        )
        await db[CLUSTERS_COLLECTION].create_index(
            [("tenant_id", ASCENDING), ("status", ASCENDING)]
        )
        await db[ANALYSIS_RUNS_COLLECTION].create_index(
            [
                ("analysis_scope_type", ASCENDING),
                ("analysis_scope_id", ASCENDING),
                ("requested_analysis_version", ASCENDING),
            ],
            unique=True,
        )
        self._indexed_databases.add(db_name)

    async def _candidates(
        self, alerts: Any, tenant_id: str, alert_id: str, now: datetime
    ) -> list[dict[str, Any]]:
        cursor = alerts.find(
            {
                "tenant_id": tenant_id,
                "created_at": {
                    "$gte": now
                    - timedelta(hours=settings.correlation_lookback_hours)
                },
                "alert_id": {"$ne": alert_id},
            },
            {
                "_id": 0,
                "alert_id": 1,
                "cluster_id": 1,
                "created_at": 1,
                "alert_type": 1,
                "source_system": 1,
                "alert_analysis": 1,
                "normalized_payload": 1,
            },
        )
        return await cursor.to_list(length=None)

    @staticmethod
    def _select_cluster(clusters: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not clusters:
            return None
        return sorted(
            clusters,
            key=lambda item: (
                -int(item.get("alert_count", 0)),
                as_utc(
                    item.get("created_at"),
                    fallback=datetime.max.replace(tzinfo=timezone.utc),
                ),
                str(item.get("cluster_id", "")),
            ),
        )[0]

    async def _resolve_cluster(
        self, clusters: Any, tenant_id: str, cluster_ids: set[str], now: datetime
    ) -> dict[str, Any] | None:
        if not cluster_ids:
            return None
        matches = await clusters.find(
            {
                "tenant_id": tenant_id,
                "cluster_id": {"$in": sorted(cluster_ids)},
                "is_open_for_grouping": True,
                "grouping_window_expires_at": {"$gt": now},
            }
        ).to_list(length=None)
        return self._select_cluster(matches)

    async def _request_analysis(
        self,
        db: Any,
        cluster: dict[str, Any],
        *,
        outcome: str,
        trigger_reason: str,
        is_final: bool,
    ) -> dict[str, Any] | None:
        expected = int(cluster.get("requested_analysis_version", 0))
        requested_version = expected + 1
        now = datetime.now(timezone.utc)
        message = ClusteredAlertMessage(
            alert_id=cluster["lead_alert_id"],
            tenant_id=cluster["tenant_id"],
            cluster_id=cluster["cluster_id"],
            analysis_type=cluster["analysis_type"],
            debounce_outcome=outcome,
            requested_analysis_version=requested_version,
            trigger_reason=trigger_reason,
            is_final=is_final,
        ).model_dump()
        updated = await db[CLUSTERS_COLLECTION].find_one_and_update(
            {
                "cluster_id": cluster["cluster_id"],
                "requested_analysis_version": expected,
            },
            {
                "$inc": {"requested_analysis_version": 1},
                "$set": {
                    "debounce_outcome": outcome,
                    "last_analysis_requested_at": now,
                    "pending_analysis_request": message,
                    "updated_at": now,
                },
            },
            return_document=ReturnDocument.AFTER,
        )
        if not updated:
            return None
        return message

    async def _publish_request(self, db: Any, message: dict[str, Any]) -> bool:
        try:
            await self.produce(settings.kafka_clustered_topic, message)
        except Exception as exc:
            await self.produce_dead_letter(
                alert_id=message["alert_id"],
                tenant_id=message["tenant_id"],
                alert_type=None,
                source_system=None,
                raw_payload=None,
                error_type="CORRELATION_PRODUCE_FAILURE",
                error_detail=str(exc),
                failed_stage="CORRELATION",
            )
            self.logger.exception(
                "Cluster request publication failed; request version remains pending"
            )
            return False
        try:
            now = datetime.now(timezone.utc)
            clustering_status = (
                "SOLO_CLUSTER"
                if message["analysis_type"] == "SINGLE_ALERT_ANALYSIS"
                else "CORRELATED"
            )
            await db[ALERTS_COLLECTION].update_many(
                {"cluster_id": message["cluster_id"]},
                {
                    "$set": {
                        "kafka_state": "CLUSTERED",
                        "clustering_status": clustering_status,
                        "analysis_type": message["analysis_type"],
                        "debounce_outcome": message["debounce_outcome"],
                        "analysis_status": (
                            "PENDING"
                            if settings.llm_analysis_enabled
                            else "DISABLED"
                        ),
                        "updated_at": now,
                    }
                },
            )
            await db[CLUSTERS_COLLECTION].update_one(
                {
                    "cluster_id": message["cluster_id"],
                    "requested_analysis_version": message[
                        "requested_analysis_version"
                    ],
                },
                {
                    "$max": {
                        "published_analysis_version": message[
                            "requested_analysis_version"
                        ]
                    },
                    "$unset": {"pending_analysis_request": ""},
                    "$set": {
                        "analysis_status": (
                            "PENDING"
                            if settings.llm_analysis_enabled
                            else "DISABLED"
                        ),
                        "updated_at": now,
                    },
                },
            )
        except PyMongoError as exc:
            await self.produce_dead_letter(
                alert_id=message["alert_id"],
                tenant_id=message["tenant_id"],
                alert_type=None,
                source_system=None,
                raw_payload=None,
                error_type="CLUSTER_WRITE_FAILURE",
                error_detail=str(exc),
                failed_stage="CORRELATION",
            )
            self.logger.exception(
                "Published cluster request but failed to persist publication state; "
                "request version remains pending"
            )
            return False
        return True

    async def process(self, data: dict[str, Any]) -> dict[str, Any] | None:
        async with self.trace_span("CORRELATION", data) as trace:
            msg = EnrichedAlertMessage.model_validate(data)
            tenant = await self._tenant(msg.tenant_id)
            db_name = tenant["db_name"]
            await self._ensure_indexes(db_name)
            db = get_client()[db_name]
            alerts = db[ALERTS_COLLECTION]
            clusters = db[CLUSTERS_COLLECTION]
            now = datetime.now(timezone.utc)

            existing_alert = await alerts.find_one(
                {"alert_id": msg.alert_id},
                {
                    "cluster_id": 1,
                    "requested_analysis_version": 1,
                    "pending_analysis_request": 1,
                    "_id": 0,
                },
            )
            if existing_alert and (
                existing_alert.get("cluster_id")
                or int(existing_alert.get("requested_analysis_version") or 0) > 0
            ):
                pending_request = existing_alert.get("pending_analysis_request")
                if existing_alert.get("cluster_id"):
                    existing_cluster = await clusters.find_one(
                        {"cluster_id": existing_alert["cluster_id"]}
                    )
                    pending_request = (
                        existing_cluster.get("pending_analysis_request")
                        if existing_cluster
                        else None
                    )
                await trace.finish(
                    "SUCCEEDED",
                    checks=[{"name": "idempotent_replay", "outcome": "SUCCEEDED"}],
                    decisions={
                        "cluster_id": existing_alert.get("cluster_id"),
                        "replayed": True,
                        "pending_request_version": (
                            pending_request.get("requested_analysis_version")
                            if pending_request
                            else None
                        ),
                    },
                )
                return pending_request

            try:
                severity = parse_severity(_resolve(msg.normalized_payload, "event.severity"))
            except ValueError as exc:
                await trace.finish(
                    "FAILED",
                    error={
                        "type": "CORRELATION_EXCEPTION",
                        "detail": str(exc),
                        "failed_fields": ["event.severity"],
                    },
                    checks=[{"name": "event.severity", "outcome": "FAILED"}],
                )
                raise
            delay_ms = debounce_ms(severity, tenant.get("settings") or {})
            incoming_entities, incoming_techniques = extract_correlation_values(
                msg.normalized_payload
            )
            candidates = await self._candidates(alerts, msg.tenant_id, msg.alert_id, now)
            correlated: list[dict[str, Any]] = []
            shared_entities: set[tuple[str, str]] = set()
            shared_techniques: set[str] = set()
            for candidate in candidates:
                entity_matches, technique_matches = match_entities(
                    incoming_entities,
                    incoming_techniques,
                    candidate.get("normalized_payload") or {},
                )
                if entity_matches or technique_matches:
                    correlated.append(candidate)
                    shared_entities.update(entity_matches)
                    shared_techniques.update(technique_matches)

            candidate_cluster_ids = {
                str(item["cluster_id"])
                for item in correlated
                if item.get("cluster_id")
            }
            cluster = await self._resolve_cluster(
                clusters, msg.tenant_id, candidate_cluster_ids, now
            )
            standalone_matches = [
                candidate for candidate in correlated if not candidate.get("cluster_id")
            ]
            result = {
                "method": "ENTITY_OVERLAP",
                "lookback_hours": settings.correlation_lookback_hours,
                "correlated_alert_ids": sorted(
                    str(item["alert_id"]) for item in correlated
                ),
                "shared_entities": sorted(map(display_pair, shared_entities)),
                "mitre_techniques": sorted(shared_techniques),
            }

            created = cluster is None
            if created:
                cluster_id = str(uuid4())
                debounce_expires_at = now + timedelta(milliseconds=delay_ms)
                member_candidates = [*standalone_matches]
                member_ids = sorted(
                    {msg.alert_id, *(str(item["alert_id"]) for item in member_candidates)}
                )
                ordered_leads = sorted(
                    [
                        {
                            "alert_id": msg.alert_id,
                            "created_at": now,
                        },
                        *member_candidates,
                    ],
                    key=lambda item: (
                        as_utc(item.get("created_at"), fallback=now),
                        str(item["alert_id"]),
                    ),
                )
                severity_values = [severity]
                for candidate in member_candidates:
                    severity_values.append(
                        parse_severity(
                            _resolve(
                                candidate.get("normalized_payload") or {},
                                "event.severity",
                            )
                        )
                    )
                severity_distribution = Counter(map(str, severity_values))
                member_count = len(member_ids)
                analysis_type = (
                    "SINGLE_ALERT_ANALYSIS"
                    if member_count == 1
                    else "CLUSTER_ANALYSIS"
                )
                clustering_status = (
                    "CORRELATED"
                    if member_count > 1
                    else ("SOLO_CLUSTER" if severity == 5 else "DEBOUNCING")
                )
                cluster = {
                    "cluster_id": cluster_id,
                    "tenant_id": msg.tenant_id,
                    "lead_alert_id": str(ordered_leads[0]["alert_id"]),
                    "alert_ids": member_ids,
                    "alert_count": member_count,
                    "is_open_for_grouping": True,
                    "debounce_expires_at": debounce_expires_at,
                    "grouping_window_expires_at": now
                    + timedelta(hours=settings.correlation_lookback_hours),
                    "correlation_basis": {
                        "method": "ENTITY_OVERLAP",
                        "shared_entities": sorted(map(display_pair, shared_entities)),
                        "mitre_techniques": sorted(shared_techniques),
                    },
                    "first_seen": as_utc(
                        ordered_leads[0].get("created_at"), fallback=now
                    ),
                    "last_seen": now,
                    "window_seconds": None,
                    "severity": {
                        "max": max(severity_values),
                        "avg": sum(severity_values) / len(severity_values),
                        "distribution": dict(severity_distribution),
                    },
                    "debounce_outcome": None,
                    "analysis_type": analysis_type,
                    "clustering_status": clustering_status,
                    "analyzed_version": 0,
                    "analyzed_alert_count": 0,
                    "last_analysis_requested_at": None,
                    "requested_analysis_version": 0,
                    "published_analysis_version": 0,
                    "pending_analysis_request": None,
                    "last_analyzed_at": None,
                    "analysis_status": None,
                    "status": "OPEN",
                    "assigned_to": None,
                    "escalated_to": None,
                    "verdict": None,
                    "analyst_notes": [],
                    "created_at": now,
                    "updated_at": now,
                    "closed_at": None,
                }
                try:
                    await clusters.insert_one(cluster)
                except Exception as exc:
                    await trace.finish(
                        "FAILED",
                        error={"type": "CLUSTER_WRITE_FAILURE", "detail": str(exc)},
                    )
                    await self.produce_dead_letter(
                        alert_id=msg.alert_id,
                        tenant_id=msg.tenant_id,
                        alert_type=msg.alert_type,
                        source_system=msg.source_system,
                        raw_payload=msg.raw_payload,
                        error_type="CLUSTER_WRITE_FAILURE",
                        error_detail=str(exc),
                        failed_stage="CORRELATION",
                    )
                    return None
            else:
                member_ids = list(cluster.get("alert_ids") or [])
                add_candidates = [
                    {
                        "alert_id": msg.alert_id,
                        "normalized_payload": msg.normalized_payload,
                        "created_at": now,
                    },
                    *standalone_matches,
                ]
                add_candidates = [
                    item
                    for item in add_candidates
                    if str(item["alert_id"]) not in member_ids
                ]
                add_ids = sorted({str(item["alert_id"]) for item in add_candidates})
                member_ids = sorted({*member_ids, *add_ids})
                severities = Counter(
                    {str(key): int(value) for key, value in
                     (cluster.get("severity", {}).get("distribution") or {}).items()}
                )
                for candidate in add_candidates:
                    candidate_severity = parse_severity(
                        _resolve(
                            candidate.get("normalized_payload") or {},
                            "event.severity",
                        )
                    )
                    severities[str(candidate_severity)] += 1
                count = len(member_ids)
                total = sum(int(key) * value for key, value in severities.items())
                merged_entities = set(
                    cluster.get("correlation_basis", {}).get("shared_entities") or []
                )
                merged_entities.update(map(display_pair, shared_entities))
                merged_techniques = set(
                    cluster.get("correlation_basis", {}).get("mitre_techniques") or []
                )
                merged_techniques.update(shared_techniques)
                cluster = await clusters.find_one_and_update(
                    {
                        "cluster_id": cluster["cluster_id"],
                        "is_open_for_grouping": True,
                        "grouping_window_expires_at": {"$gt": now},
                    },
                    {
                        "$addToSet": {"alert_ids": {"$each": add_ids}},
                        "$set": {
                            "alert_count": count,
                            "last_seen": now,
                            "updated_at": now,
                            "analysis_type": "CLUSTER_ANALYSIS",
                            "clustering_status": "CORRELATED",
                            "severity": {
                                "max": max(map(int, severities)),
                                "avg": total / count,
                                "distribution": dict(severities),
                            },
                            "correlation_basis.shared_entities": sorted(merged_entities),
                            "correlation_basis.mitre_techniques": sorted(
                                merged_techniques
                            ),
                        },
                    },
                    return_document=ReturnDocument.AFTER,
                )
                if not cluster:
                    raise RuntimeError("Selected cluster closed before membership update")

            promoted_ids = list(cluster.get("alert_ids") or [])
            await alerts.update_many(
                {
                    "alert_id": {"$in": promoted_ids},
                    "alert_analysis": {"$exists": True, "$ne": None},
                },
                {
                    "$set": {
                        "alert_analysis.superseded_by_cluster_id": cluster["cluster_id"],
                        "alert_analysis.superseded_at": now,
                    }
                },
            )
            member_count = int(cluster.get("alert_count") or len(promoted_ids))
            analysis_type = (
                "SINGLE_ALERT_ANALYSIS"
                if member_count == 1
                else "CLUSTER_ANALYSIS"
            )
            clustering_status = (
                "CORRELATED"
                if member_count > 1
                else ("SOLO_CLUSTER" if severity == 5 else "DEBOUNCING")
            )
            await alerts.update_many(
                {"alert_id": {"$in": promoted_ids}},
                {
                    "$set": {
                        "cluster_id": cluster["cluster_id"],
                        "clustering_status": clustering_status,
                        "analysis_type": analysis_type,
                        "status": "ANALYZING",
                        "analysis_error": None,
                        "updated_at": now,
                    },
                    "$unset": {"pending_analysis_request": ""},
                },
            )
            await db[ANALYSIS_RUNS_COLLECTION].update_many(
                {
                    "analysis_scope_type": "ALERT",
                    "analysis_scope_id": {"$in": promoted_ids},
                    "state": {"$in": ["PENDING", "RUNNING"]},
                },
                {
                    "$set": {
                        "state": "SUPERSEDED",
                        "superseded_by_cluster_id": cluster["cluster_id"],
                        "completed_at": now,
                        "updated_at": now,
                    },
                    "$unset": {"lease_expires_at": ""},
                },
            )
            await alerts.update_one(
                {"alert_id": msg.alert_id},
                {
                    "$set": {
                        "cluster_id": cluster["cluster_id"],
                        "clustering_status": clustering_status,
                        "debounce_outcome": cluster.get("debounce_outcome"),
                        "analysis_type": analysis_type,
                        "correlation_result": result,
                        "updated_at": now,
                    }
                },
            )

            output = None
            if (
                int(cluster.get("severity", {}).get("max", severity)) == 5
                and cluster["requested_analysis_version"] == 0
            ):
                output = await self._request_analysis(
                    db,
                    cluster,
                    outcome="PROMOTED",
                    trigger_reason="PROMOTED",
                    is_final=False,
                )
            elif not created and cluster["requested_analysis_version"] > 0:
                output = await self._request_analysis(
                    db,
                    cluster,
                    outcome="IMMEDIATE",
                    trigger_reason="MEMBERSHIP_CHANGED",
                    is_final=False,
                )

            decisions = {
                "extracted_entities": sorted(map(display_pair, incoming_entities)),
                "extracted_mitre_techniques": sorted(incoming_techniques),
                "candidate_count": len(candidates),
                "matching_alert_ids": result["correlated_alert_ids"],
                "shared_entities": result["shared_entities"],
                "shared_mitre_techniques": result["mitre_techniques"],
                "selected_cluster_id": cluster["cluster_id"],
                "cluster_created": created,
                "promoted_standalone_alert_ids": sorted(
                    str(item["alert_id"]) for item in standalone_matches
                ),
                "analysis_type": analysis_type,
                "clustering_status": clustering_status,
                "severity": severity,
                "debounce_ms": delay_ms,
                "debounce_expires_at": cluster["debounce_expires_at"].isoformat(),
                "grouping_window_expires_at": cluster[
                    "grouping_window_expires_at"
                ].isoformat(),
            }
            await trace.finish(
                "SUCCEEDED",
                output_value=output,
                checks=[
                    {"name": "tenant_database", "outcome": "SUCCEEDED"},
                    {"name": "candidate_lookup", "outcome": "SUCCEEDED"},
                    {"name": "cluster_assignment", "outcome": "SUCCEEDED"},
                ],
                decisions=decisions,
            )
            return output

    async def _handle(self, msg: Any):
        try:
            output = await self.process(msg.value)
            if output:
                tenant = await self._tenant(output["tenant_id"])
                await self._publish_request(get_client()[tenant["db_name"]], output)
        except Exception as exc:
            self.logger.exception("Correlation failed")
            await self.produce_dead_letter(
                alert_id=msg.value.get("alert_id", "unknown"),
                tenant_id=msg.value.get("tenant_id"),
                alert_type=msg.value.get("alert_type"),
                source_system=msg.value.get("source_system"),
                raw_payload=msg.value.get("raw_payload"),
                error_type=(
                    "CLUSTER_WRITE_FAILURE"
                    if isinstance(exc, PyMongoError)
                    else "CORRELATION_EXCEPTION"
                ),
                error_detail=str(exc),
                failed_stage="CORRELATION",
            )

    async def _scheduler_loop(self):
        while True:
            try:
                await self._scheduler_tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger.exception("Correlation scheduler tick failed")
            await asyncio.sleep(settings.correlation_scheduler_interval_seconds)

    async def _scheduler_tick(self):
        tenants = await get_database()["tenants"].find(
            {"status": "ACTIVE"}, {"db_name": 1, "_id": 0}
        ).to_list(length=None)
        now = datetime.now(timezone.utc)
        for tenant in tenants:
            db = get_client()[tenant["db_name"]]
            await self._ensure_indexes(tenant["db_name"])
            clusters = db[CLUSTERS_COLLECTION]
            alerts = db[ALERTS_COLLECTION]
            pending = await clusters.find(
                {"pending_analysis_request": {"$exists": True, "$ne": None}}
            ).to_list(length=None)
            for cluster in pending:
                await self._publish_request(
                    db, cluster["pending_analysis_request"]
                )

            due = await clusters.find(
                {
                    "is_open_for_grouping": True,
                    "requested_analysis_version": 0,
                    "debounce_expires_at": {"$lte": now},
                }
            ).to_list(length=None)
            for cluster in due:
                is_solo = int(cluster.get("alert_count", 0)) == 1
                analysis_type = (
                    "SINGLE_ALERT_ANALYSIS" if is_solo else "CLUSTER_ANALYSIS"
                )
                clustering_status = "SOLO_CLUSTER" if is_solo else "CORRELATED"
                await clusters.update_one(
                    {
                        "cluster_id": cluster["cluster_id"],
                        "requested_analysis_version": 0,
                    },
                    {
                        "$set": {
                            "analysis_type": analysis_type,
                            "clustering_status": clustering_status,
                            "updated_at": now,
                        }
                    },
                )
                await alerts.update_many(
                    {"cluster_id": cluster["cluster_id"]},
                    {
                        "$set": {
                            "analysis_type": analysis_type,
                            "clustering_status": clustering_status,
                            "updated_at": now,
                        }
                    },
                )
                cluster["analysis_type"] = analysis_type
                cluster["clustering_status"] = clustering_status
                outcome = (
                    "EXPIRED_SOLO_CLUSTER"
                    if is_solo
                    else "EXPIRED_WITH_CLUSTER"
                )
                message = await self._request_analysis(
                    db,
                    cluster,
                    outcome=outcome,
                    trigger_reason="DEBOUNCE_EXPIRED",
                    is_final=False,
                )
                if message:
                    await self._publish_request(db, message)

            expired = await clusters.find(
                {
                    "is_open_for_grouping": True,
                    "grouping_window_expires_at": {"$lte": now},
                }
            ).to_list(length=None)
            for cluster in expired:
                closed = await clusters.find_one_and_update(
                    {
                        "cluster_id": cluster["cluster_id"],
                        "is_open_for_grouping": True,
                    },
                    {
                        "$set": {
                            "is_open_for_grouping": False,
                            "closed_at": now,
                            "updated_at": now,
                            "window_seconds": max(
                                0,
                                int(
                                    (
                                        as_utc(
                                            cluster.get("last_seen"), fallback=now
                                        )
                                        - as_utc(
                                            cluster.get("first_seen"), fallback=now
                                        )
                                    ).total_seconds()
                                ),
                            ),
                        }
                    },
                    return_document=ReturnDocument.AFTER,
                )
                if not closed:
                    continue
                message = await self._request_analysis(
                    db,
                    closed,
                    outcome=closed.get("debounce_outcome")
                    or (
                        "EXPIRED_SOLO_CLUSTER"
                        if closed["alert_count"] == 1
                        else "EXPIRED_WITH_CLUSTER"
                    ),
                    trigger_reason="WINDOW_CAP",
                    is_final=True,
                )
                if message:
                    await self._publish_request(db, message)
