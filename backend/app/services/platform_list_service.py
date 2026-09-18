from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Callable

from fastapi import HTTPException, status
from pymongo import ASCENDING, DESCENDING

from app.db.mongodb import DatabaseManager
from app.models.tenant import Tenant
from app.services.alert_type_schema_service import AlertTypeSchemaService
from app.services.playbook_service import PlaybookService
from app.core.alert_metrics import (
    aggregate_alert_stats,
    build_alert_query,
    severity_from_alert,
)
from app.schemas.tenant import AlertStats
from app.schemas.playbook import PlaybookStats


logger = logging.getLogger(__name__)


class PlatformListService:
    """Globally page records from active, physically separated tenant DBs."""

    MAX_WORKERS = 8

    @staticmethod
    def _active_tenants() -> list[Tenant]:
        return list(
            Tenant.objects(status="ACTIVE")
            .only("tenant_id", "display_name", "db_name")
            .order_by("tenant_id")
        )

    @staticmethod
    def _database(tenant: Tenant):
        return DatabaseManager.get_tenant_database(str(tenant.db_name))

    @staticmethod
    def _search(value: str | None) -> str:
        return (value or "").strip()[:512]

    @staticmethod
    def _pattern(value: str):
        return re.compile(re.escape(value), re.IGNORECASE)

    @staticmethod
    def _timestamp(value: Any) -> float:
        if not isinstance(value, datetime):
            return float("-inf")
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.timestamp()

    @classmethod
    def _sort_key(
        cls,
        row: dict[str, Any],
        *,
        q: str,
        id_field: str,
        timestamp_field: str,
    ) -> tuple[Any, ...]:
        return (
            0 if q and row.get(id_field) == q else 1,
            -cls._timestamp(row.get(timestamp_field)),
            str(row.get("tenant_id") or ""),
            str(row.get(id_field) or ""),
        )

    @classmethod
    def _merge(
        cls,
        *,
        tenants: list[Tenant],
        worker: Callable[[Tenant], tuple[int, list[dict[str, Any]]]],
        skip: int,
        limit: int,
        q: str,
        id_field: str,
        timestamp_field: str,
    ) -> tuple[list[dict[str, Any]], int]:
        if not tenants:
            return [], 0

        total = 0
        rows: list[dict[str, Any]] = []
        failures: list[str] = []
        with ThreadPoolExecutor(
            max_workers=min(cls.MAX_WORKERS, len(tenants))
        ) as executor:
            future_tenants = {
                executor.submit(worker, tenant): tenant for tenant in tenants
            }
            for future in as_completed(future_tenants):
                tenant = future_tenants[future]
                try:
                    tenant_total, tenant_rows = future.result()
                except Exception:
                    safe_id = str(tenant.tenant_id)
                    failures.append(safe_id)
                    logger.error(
                        "Platform list tenant query failed tenant_id=%s", safe_id
                    )
                    continue
                total += tenant_total
                rows.extend(tenant_rows)

        if failures:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="One or more active tenant databases could not be queried",
            )

        rows.sort(
            key=lambda row: cls._sort_key(
                row,
                q=q,
                id_field=id_field,
                timestamp_field=timestamp_field,
            )
        )
        return rows[skip : skip + limit], total

    @staticmethod
    def _pipeline(
        query: dict[str, Any],
        *,
        q: str,
        id_field: str,
        timestamp_field: str,
        top: int,
    ) -> list[dict[str, Any]]:
        pipeline: list[dict[str, Any]] = [{"$match": query}]
        if q:
            pipeline.append(
                {
                    "$addFields": {
                        "_exact_rank": {
                            "$cond": [{"$eq": [f"${id_field}", q]}, 0, 1]
                        }
                    }
                }
            )
        else:
            pipeline.append({"$addFields": {"_exact_rank": 1}})
        pipeline.extend(
            [
                {
                    "$sort": {
                        "_exact_rank": ASCENDING,
                        timestamp_field: DESCENDING,
                        id_field: ASCENDING,
                    }
                },
                {"$limit": top},
                {"$project": {"_exact_rank": 0}},
            ]
        )
        return pipeline

    @staticmethod
    def _decorate(rows: list[dict[str, Any]], tenant: Tenant) -> list[dict[str, Any]]:
        decorated = []
        for source in rows:
            row = dict(source)
            if "_id" in row:
                row["_id"] = str(row["_id"])
                row["id"] = row["_id"]
            row["tenant_id"] = str(tenant.tenant_id)
            row["tenant_name"] = str(tenant.display_name)
            if row.get("alert_id") is not None:
                row["severity"] = severity_from_alert(row)
            decorated.append(row)
        return decorated

    @classmethod
    def list_alerts(
        cls,
        *,
        q: str | None,
        skip: int,
        limit: int,
        since_hours: int | None,
    ) -> tuple[list[dict[str, Any]], int]:
        search = cls._search(q)
        top = skip + limit
        base_query, _ = build_alert_query(q=search, since_hours=since_hours)

        def query_tenant(tenant: Tenant):
            query = dict(base_query)
            collection = cls._database(tenant)["alerts"]
            total = collection.count_documents(query)
            rows = list(
                collection.aggregate(
                    cls._pipeline(
                        query,
                        q=search,
                        id_field="alert_id",
                        timestamp_field="created_at",
                        top=top,
                    )
                )
            )
            return total, cls._decorate(rows, tenant)

        return cls._merge(
            tenants=cls._active_tenants(),
            worker=query_tenant,
            skip=skip,
            limit=limit,
            q=search,
            id_field="alert_id",
            timestamp_field="created_at",
        )

    @classmethod
    def _collect_tenant_values(
        cls, worker: Callable[[Tenant], dict[str, Any]], *, label: str
    ) -> list[dict[str, Any]]:
        tenants = cls._active_tenants()
        if not tenants:
            return []
        values: list[dict[str, Any]] = []
        failed = False
        with ThreadPoolExecutor(
            max_workers=min(cls.MAX_WORKERS, len(tenants))
        ) as executor:
            futures = {executor.submit(worker, tenant): tenant for tenant in tenants}
            for future in as_completed(futures):
                tenant = futures[future]
                try:
                    values.append(future.result())
                except Exception:
                    failed = True
                    logger.exception(
                        "Platform %s tenant query failed tenant_id=%s",
                        label,
                        tenant.tenant_id,
                    )
        if failed:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    f"Platform {label} are unavailable because a tenant "
                    "database could not be queried"
                ),
            )
        return values

    @classmethod
    def alert_stats(
        cls, *, q: str | None, since_hours: int | None
    ) -> AlertStats:
        query, _ = build_alert_query(q=q, since_hours=since_hours)
        values = cls._collect_tenant_values(
            lambda tenant: aggregate_alert_stats(
                cls._database(tenant)["alerts"], query
            ),
            label="alert statistics",
        )
        counts = {
            name: sum(int(value["severity"].get(name, 0)) for value in values)
            for name in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN")
        }
        return AlertStats(
            filtered_total=sum(int(value["filtered_total"]) for value in values),
            severity=counts,
        )

    @classmethod
    def playbook_stats(cls) -> PlaybookStats:
        values = cls._collect_tenant_values(
            lambda tenant: PlaybookService.stats_values(str(tenant.tenant_id)),
            label="playbook statistics",
        )
        covered = (
            set().union(*(value["alert_types"] for value in values))
            if values
            else set()
        )
        return PlaybookStats(
            total_playbooks=sum(int(value["total_playbooks"]) for value in values),
            active_playbooks=sum(int(value["active_playbooks"]) for value in values),
            system_playbooks=sum(int(value["system_playbooks"]) for value in values),
            covered_alert_types=len(covered),
        )

    @classmethod
    def list_clusters(
        cls,
        *,
        q: str | None,
        skip: int,
        limit: int,
        cluster_status: str | None,
    ) -> tuple[list[dict[str, Any]], int]:
        search = cls._search(q)
        top = skip + limit

        def query_tenant(tenant: Tenant):
            query: dict[str, Any] = {}
            if cluster_status and not search:
                query["status"] = cluster_status
            if search:
                pattern = cls._pattern(search)
                query["$or"] = [
                    {"cluster_id": pattern},
                    {"summary.headline": pattern},
                    {"summary.narrative": pattern},
                    {"correlation_basis.mitre_techniques": pattern},
                ]
            collection = cls._database(tenant)["clusters"]
            total = collection.count_documents(query)
            rows = list(
                collection.aggregate(
                    cls._pipeline(
                        query,
                        q=search,
                        id_field="cluster_id",
                        timestamp_field="created_at",
                        top=top,
                    )
                    + [{"$project": {"_id": 0}}]
                )
            )
            return total, cls._decorate(rows, tenant)

        return cls._merge(
            tenants=cls._active_tenants(),
            worker=query_tenant,
            skip=skip,
            limit=limit,
            q=search,
            id_field="cluster_id",
            timestamp_field="created_at",
        )

    @classmethod
    def list_schemas(
        cls,
        *,
        q: str | None,
        skip: int,
        limit: int,
        is_active: bool | None,
    ) -> tuple[list[dict[str, Any]], int]:
        search = cls._search(q)
        top = skip + limit

        def query_tenant(tenant: Tenant):
            query: dict[str, Any] = {}
            if is_active is not None and not search:
                query["is_active"] = is_active
            if search:
                pattern = cls._pattern(search)
                query["$or"] = [
                    {"alert_type": pattern},
                    {"schema_id": pattern},
                ]
            collection = cls._database(tenant)[AlertTypeSchemaService.COLLECTION]
            total = collection.count_documents(query)
            rows = list(
                collection.aggregate(
                    cls._pipeline(
                        query,
                        q=search,
                        id_field="schema_id",
                        timestamp_field="updated_at",
                        top=top,
                    )
                )
            )
            return total, cls._decorate(rows, tenant)

        return cls._merge(
            tenants=cls._active_tenants(),
            worker=query_tenant,
            skip=skip,
            limit=limit,
            q=search,
            id_field="schema_id",
            timestamp_field="updated_at",
        )

    @classmethod
    def list_playbooks(
        cls,
        *,
        q: str | None,
        skip: int,
        limit: int,
        is_active: bool | None,
    ) -> tuple[list[dict[str, Any]], int]:
        search = cls._search(q)
        top = skip + limit

        def query_tenant(tenant: Tenant):
            query: dict[str, Any] = {}
            if is_active is not None and not search:
                query["is_active"] = is_active
            if search:
                pattern = cls._pattern(search)
                query["$or"] = [
                    {"playbook_name": pattern},
                    {"alert_types": pattern},
                    {"playbook_id": pattern},
                ]
            collection = cls._database(tenant)[PlaybookService.COLLECTION]
            latest_pipeline = [
                {"$addFields": {"version": {"$ifNull": ["$version", 1]}}},
                {"$sort": {"version": DESCENDING}},
                {
                    "$group": {
                        "_id": "$playbook_id",
                        "document": {"$first": "$$ROOT"},
                    }
                },
                {"$replaceRoot": {"newRoot": "$document"}},
                {"$match": query},
            ]
            count_rows = list(
                collection.aggregate(latest_pipeline + [{"$count": "total"}])
            )
            rows = list(
                collection.aggregate(
                    latest_pipeline
                    + cls._pipeline(
                        {},
                        q=search,
                        id_field="playbook_id",
                        timestamp_field="updated_at",
                        top=top,
                    )[1:]
                )
            )
            total = int(count_rows[0]["total"]) if count_rows else 0
            return total, cls._decorate(rows, tenant)

        return cls._merge(
            tenants=cls._active_tenants(),
            worker=query_tenant,
            skip=skip,
            limit=limit,
            q=search,
            id_field="playbook_id",
            timestamp_field="updated_at",
        )

    @classmethod
    def ensure_indexes(cls) -> None:
        for tenant in cls._active_tenants():
            try:
                db = cls._database(tenant)
                cls._ensure_index(db["alerts"], [("alert_id", ASCENDING)])
                db["alerts"].create_index(
                    [("created_at", DESCENDING), ("alert_id", ASCENDING)],
                    name="created_at_-1_alert_id_1",
                )
                db["alerts"].create_index(
                    [("status", ASCENDING), ("created_at", DESCENDING)],
                    name="status_1_created_at_-1",
                )
                db["alerts"].create_index(
                    [("severity", ASCENDING), ("created_at", DESCENDING)],
                    name="severity_1_created_at_-1",
                )
                cls._ensure_index(db["clusters"], [("cluster_id", ASCENDING)])
                db["clusters"].create_index(
                    [("created_at", DESCENDING), ("cluster_id", ASCENDING)],
                    name="created_at_-1_cluster_id_1",
                )
                db["clusters"].create_index(
                    [("status", ASCENDING), ("created_at", DESCENDING)],
                    name="status_1_created_at_-1",
                )
                AlertTypeSchemaService._reconcile_collection_indexes(
                    db[AlertTypeSchemaService.COLLECTION]
                )
                PlaybookService._reconcile_collection_indexes(
                    db[PlaybookService.COLLECTION], str(tenant.tenant_id)
                )
            except Exception:
                logger.error(
                    "Could not ensure platform-list indexes tenant_id=%s",
                    str(tenant.tenant_id),
                )

    @staticmethod
    def _ensure_index(collection, keys: list[tuple[str, int]]) -> None:
        """Create an index only when no equivalent key pattern already exists."""
        wanted = list(keys)
        for current in collection.list_indexes():
            if list(current.get("key", {}).items()) == wanted:
                return
        collection.create_index(keys)
