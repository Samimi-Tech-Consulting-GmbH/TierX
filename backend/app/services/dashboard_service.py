from __future__ import annotations

import threading
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Any

import mongoengine as me
from pymongo import ASCENDING, DESCENDING

from app.db.mongodb import DatabaseManager
from app.core.alert_metrics import severity_expression
from app.core.errors import ResourceNotFoundError
from app.models.tenant import Tenant
from app.schemas.dashboard import (
    DashboardActivity,
    DashboardActivityBucket,
    DashboardCoverage,
    DashboardKpis,
    DashboardRecentActivity,
    PlatformDashboardSummary,
    TenantDashboardSummary,
)


ACTIVITY_WINDOWS = {
    "daily": (8, timedelta(hours=3)),
    "weekly": (7, timedelta(hours=24)),
    "monthly": (10, timedelta(hours=72)),
}
RESOLVED_CLUSTER_STATUSES = ["CLOSED", "FALSE_POSITIVE"]
ACTIVE_CLUSTER_STATUSES = ["OPEN", "UNDER_INVESTIGATION", "ESCALATED"]
logger = logging.getLogger(__name__)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class PlatformDashboardService:
    CACHE_TTL_SECONDS = 30
    MAX_WORKERS = 8

    _condition = threading.Condition()
    _cache: PlatformDashboardSummary | None = None
    _cache_deadline = 0.0
    _refreshing = False

    @classmethod
    def reset_cache(cls) -> None:
        with cls._condition:
            cls._cache = None
            cls._cache_deadline = 0.0
            cls._refreshing = False
            cls._condition.notify_all()

    @classmethod
    def ensure_indexes(cls) -> None:
        tenants = Tenant.objects(status__ne="DELETED").only("db_name")
        for tenant in tenants:
            try:
                db = DatabaseManager.get_tenant_database(str(tenant.db_name))
                db["alerts"].create_index(
                    [("status", ASCENDING), ("created_at", DESCENDING)]
                )
                db["alerts"].create_index(
                    [("severity", ASCENDING), ("created_at", DESCENDING)]
                )
                db["clusters"].create_index(
                    [("status", ASCENDING), ("created_at", DESCENDING)]
                )
                db["dead_letters"].create_index(
                    [("received_at", DESCENDING)]
                )
            except Exception:
                # A temporarily unavailable tenant must not prevent the API from
                # starting. The summary response will report it as partial.
                continue

        me.connection.get_db("default")["dead_letters"].create_index(
            [("received_at", DESCENDING)]
        )

    @classmethod
    def get_summary(cls) -> PlatformDashboardSummary:
        now_mono = time.monotonic()
        with cls._condition:
            if cls._cache is not None and now_mono < cls._cache_deadline:
                return cls._cache
            while cls._refreshing:
                cls._condition.wait()
                now_mono = time.monotonic()
                if cls._cache is not None and now_mono < cls._cache_deadline:
                    return cls._cache
            cls._refreshing = True

        try:
            summary = cls._build_summary(datetime.now(timezone.utc))
        except Exception:
            with cls._condition:
                cls._refreshing = False
                cls._condition.notify_all()
            raise

        with cls._condition:
            cls._cache = summary
            cls._cache_deadline = (
                time.monotonic() + cls.CACHE_TTL_SECONDS
            )
            cls._refreshing = False
            cls._condition.notify_all()
            return summary

    @classmethod
    def _windows(
        cls, generated_at: datetime
    ) -> dict[str, list[tuple[datetime, datetime]]]:
        return {
            name: [
                (
                    generated_at - step * (count - index),
                    generated_at - step * (count - index - 1),
                )
                for index in range(count)
            ]
            for name, (count, step) in ACTIVITY_WINDOWS.items()
        }

    @staticmethod
    def _bucket_pipeline(
        field: str, windows: list[tuple[datetime, datetime]]
    ) -> list[dict[str, Any]]:
        boundaries = [windows[0][0], *[end for _, end in windows]]
        return [
            {"$match": {field: {"$gte": boundaries[0], "$lt": boundaries[-1]}}},
            {
                "$bucket": {
                    "groupBy": f"${field}",
                    "boundaries": boundaries,
                    "default": "outside",
                    "output": {"count": {"$sum": 1}},
                }
            },
        ]

    @classmethod
    def _activity_facets(
        cls, field: str, windows: dict[str, list[tuple[datetime, datetime]]]
    ) -> dict[str, list[dict[str, Any]]]:
        return {
            name: cls._bucket_pipeline(field, value)
            for name, value in windows.items()
        }

    @classmethod
    def _aggregate_tenant(
        cls,
        tenant: Tenant,
        windows: dict[str, list[tuple[datetime, datetime]]],
    ) -> dict[str, Any]:
        db = DatabaseManager.get_tenant_database(str(tenant.db_name))

        alert_facets: dict[str, list[dict[str, Any]]] = {
            "totals": [
                {
                    "$group": {
                        "_id": None,
                        "total_alerts": {"$sum": 1},
                        "critical_alerts": {
                            "$sum": {
                                "$cond": [
                                    {"$eq": [severity_expression(), "CRITICAL"]},
                                    1,
                                    0,
                                ]
                            }
                        },
                        "escalated_alerts": {
                            "$sum": {
                                "$cond": [
                                    {
                                        "$eq": [
                                            {
                                                "$toUpper": {
                                                    "$convert": {
                                                        "input": "$status",
                                                        "to": "string",
                                                        "onError": "",
                                                        "onNull": "",
                                                    }
                                                }
                                            },
                                            "ESCALATED",
                                        ]
                                    },
                                    1,
                                    0,
                                ]
                            }
                        },
                    }
                }
            ],
            "recent_critical": [
                {
                    "$match": {
                        "created_at": {"$ne": None},
                        "$expr": {
                            "$in": [
                                severity_expression(),
                                ["CRITICAL"],
                            ]
                        },
                    }
                },
                {"$sort": {"created_at": -1, "_id": -1}},
                {"$limit": 1},
                {"$project": {"_id": 0, "alert_id": 1, "created_at": 1}},
            ],
            **cls._activity_facets("created_at", windows),
        }
        alert_result = next(
            iter(db["alerts"].aggregate([{"$facet": alert_facets}])), {}
        )

        cluster_result = next(
            iter(
                db["clusters"].aggregate(
                    [
                        {
                            "$facet": {
                                "totals": [
                                    {
                                        "$group": {
                                            "_id": None,
                                            "active_clusters": {
                                                "$sum": {
                                                    "$cond": [
                                                        {
                                                            "$in": [
                                                                "$status",
                                                                ACTIVE_CLUSTER_STATUSES,
                                                            ]
                                                        },
                                                        1,
                                                        0,
                                                    ]
                                                }
                                            },
                                            "resolved_clusters": {
                                                "$sum": {
                                                    "$cond": [
                                                        {
                                                            "$in": [
                                                                "$status",
                                                                RESOLVED_CLUSTER_STATUSES,
                                                            ]
                                                        },
                                                        1,
                                                        0,
                                                    ]
                                                }
                                            },
                                            "open_alerts": {
                                                "$sum": {
                                                    "$cond": [
                                                        {
                                                            "$in": [
                                                                "$status",
                                                                ACTIVE_CLUSTER_STATUSES,
                                                            ]
                                                        },
                                                        {"$ifNull": ["$alert_count", 0]},
                                                        0,
                                                    ]
                                                }
                                            },
                                        }
                                    }
                                ],
                                "recent": [
                                    {"$match": {"created_at": {"$ne": None}}},
                                    {"$sort": {"created_at": -1, "_id": -1}},
                                    {"$limit": 1},
                                    {
                                        "$project": {
                                            "_id": 0,
                                            "cluster_id": 1,
                                            "created_at": 1,
                                        }
                                    },
                                ],
                            }
                        }
                    ]
                )
            ),
            {},
        )

        dead_letter_result = next(
            iter(
                db["dead_letters"].aggregate(
                    [{"$facet": cls._activity_facets("received_at", windows)}]
                )
            ),
            {},
        )

        totals = (alert_result.get("totals") or [{}])[0]
        cluster_totals = (cluster_result.get("totals") or [{}])[0]
        return {
            "tenant_id": tenant.tenant_id,
            "total_alerts": int(totals.get("total_alerts", 0)),
            "critical_alerts": int(totals.get("critical_alerts", 0)),
            "escalated_alerts": int(totals.get("escalated_alerts", 0)),
            "open_alerts": int(cluster_totals.get("open_alerts", 0)),
            "active_clusters": int(cluster_totals.get("active_clusters", 0)),
            "resolved_clusters": int(cluster_totals.get("resolved_clusters", 0)),
            "alert_activity": alert_result,
            "dead_letter_activity": dead_letter_result,
            "recent_critical": (alert_result.get("recent_critical") or [None])[0],
            "recent_cluster": (cluster_result.get("recent") or [None])[0],
        }

    @classmethod
    def get_tenant_summary(cls, tenant_id: str) -> TenantDashboardSummary:
        tenant = Tenant.objects(
            tenant_id=tenant_id, status__ne="DELETED"
        ).only("tenant_id", "db_name", "status").first()
        if tenant is None:
            raise ResourceNotFoundError(f"Tenant with ID {tenant_id} not found")

        generated_at = datetime.now(timezone.utc)
        windows = cls._windows(generated_at)
        result = cls._aggregate_tenant(tenant, windows)
        activity = DashboardActivity(
            **{
                name: [
                    DashboardActivityBucket(
                        start_at=start,
                        end_at=end,
                        alerts=cls._counts_for(
                            result["alert_activity"].get(name) or [], ranges
                        )[index],
                        dead_letters=cls._counts_for(
                            result["dead_letter_activity"].get(name) or [], ranges
                        )[index],
                    )
                    for index, (start, end) in enumerate(ranges)
                ]
                for name, ranges in windows.items()
            }
        )
        recent: list[DashboardRecentActivity] = []
        if result.get("recent_critical"):
            item = result["recent_critical"]
            if isinstance(item.get("created_at"), datetime):
                recent.append(
                    DashboardRecentActivity(
                        kind="CRITICAL_ALERT",
                        tenant_id=tenant_id,
                        alert_id=item.get("alert_id"),
                        occurred_at=_as_utc(item["created_at"]),
                    )
                )
        if result.get("recent_cluster"):
            item = result["recent_cluster"]
            if isinstance(item.get("created_at"), datetime):
                recent.append(
                    DashboardRecentActivity(
                        kind="CLUSTER",
                        tenant_id=tenant_id,
                        cluster_id=item.get("cluster_id"),
                        occurred_at=_as_utc(item["created_at"]),
                    )
                )
        recent.sort(key=lambda item: item.occurred_at, reverse=True)
        return TenantDashboardSummary(
            generated_at=generated_at,
            cache_expires_at=generated_at
            + timedelta(seconds=cls.CACHE_TTL_SECONDS),
            kpis=DashboardKpis(
                critical_alerts=result["critical_alerts"],
                open_alerts=result["open_alerts"],
                active_clusters=result["active_clusters"],
                resolved_incidents=result["resolved_clusters"],
                total_alerts=result["total_alerts"],
                escalated_alerts=result["escalated_alerts"],
                resolved_clusters=result["resolved_clusters"],
            ),
            activity=activity,
            recent_activity=recent,
        )

    @classmethod
    def _aggregate_platform_dead_letters(
        cls, windows: dict[str, list[tuple[datetime, datetime]]]
    ) -> dict[str, Any]:
        db = me.connection.get_db("default")
        return next(
            iter(
                db["dead_letters"].aggregate(
                    [{"$facet": cls._activity_facets("received_at", windows)}]
                )
            ),
            {},
        )

    @staticmethod
    def _counts_for(
        rows: list[dict[str, Any]],
        windows: list[tuple[datetime, datetime]],
    ) -> list[int]:
        by_start = {
            _as_utc(row["_id"]): int(row.get("count", 0))
            for row in rows
            if isinstance(row.get("_id"), datetime)
        }
        return [by_start.get(_as_utc(start), 0) for start, _ in windows]

    @classmethod
    def _build_summary(cls, generated_at: datetime) -> PlatformDashboardSummary:
        generated_at = _as_utc(generated_at)
        windows = cls._windows(generated_at)
        tenants = list(
            Tenant.objects(status__ne="DELETED").only(
                "tenant_id", "db_name", "status"
            )
        )
        results: list[dict[str, Any]] = []
        failed_sources: list[str] = []
        failure_details: list[dict[str, str]] = []

        worker_count = min(cls.MAX_WORKERS, max(len(tenants), 1))
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(cls._aggregate_tenant, tenant, windows): tenant
                for tenant in tenants
            }
            for future in as_completed(futures):
                tenant = futures[future]
                try:
                    results.append(future.result())
                except Exception as exc:
                    source = f"tenant:{tenant.tenant_id}"
                    failed_sources.append(source)
                    failure_details.append(
                        {"source": source, "error_type": type(exc).__name__}
                    )
                    logger.exception(
                        "Dashboard tenant aggregation failed tenant_id=%s",
                        tenant.tenant_id,
                    )

        try:
            platform_dead_letters = cls._aggregate_platform_dead_letters(windows)
        except Exception as exc:
            platform_dead_letters = {}
            failed_sources.append("platform:dead_letters")
            failure_details.append(
                {
                    "source": "platform:dead_letters",
                    "error_type": type(exc).__name__,
                }
            )
            logger.exception("Dashboard platform dead-letter aggregation failed")

        activity_totals: dict[str, dict[str, list[int]]] = {}
        for name, value in windows.items():
            alerts = [0] * len(value)
            dead_letters = cls._counts_for(
                platform_dead_letters.get(name) or [], value
            )
            for result in results:
                tenant_alerts = cls._counts_for(
                    result["alert_activity"].get(name) or [], value
                )
                tenant_dead_letters = cls._counts_for(
                    result["dead_letter_activity"].get(name) or [], value
                )
                alerts = [a + b for a, b in zip(alerts, tenant_alerts)]
                dead_letters = [
                    a + b for a, b in zip(dead_letters, tenant_dead_letters)
                ]
            activity_totals[name] = {
                "alerts": alerts,
                "dead_letters": dead_letters,
            }

        activity = DashboardActivity(
            **{
                name: [
                    DashboardActivityBucket(
                        start_at=start,
                        end_at=end,
                        alerts=activity_totals[name]["alerts"][index],
                        dead_letters=activity_totals[name]["dead_letters"][index],
                    )
                    for index, (start, end) in enumerate(value)
                ]
                for name, value in windows.items()
            }
        )

        recent: list[DashboardRecentActivity] = []
        critical = [
            (result["tenant_id"], result["recent_critical"])
            for result in results
            if result.get("recent_critical")
            and isinstance(result["recent_critical"].get("created_at"), datetime)
        ]
        if critical:
            tenant_id, item = max(
                critical, key=lambda value: _as_utc(value[1]["created_at"])
            )
            recent.append(
                DashboardRecentActivity(
                    kind="CRITICAL_ALERT",
                    tenant_id=tenant_id,
                    alert_id=item.get("alert_id"),
                    occurred_at=_as_utc(item["created_at"]),
                )
            )

        clusters = [
            (result["tenant_id"], result["recent_cluster"])
            for result in results
            if result.get("recent_cluster")
            and isinstance(result["recent_cluster"].get("created_at"), datetime)
        ]
        if clusters:
            tenant_id, item = max(
                clusters, key=lambda value: _as_utc(value[1]["created_at"])
            )
            recent.append(
                DashboardRecentActivity(
                    kind="CLUSTER",
                    tenant_id=tenant_id,
                    cluster_id=item.get("cluster_id"),
                    occurred_at=_as_utc(item["created_at"]),
                )
            )
        recent.sort(key=lambda item: item.occurred_at, reverse=True)

        return PlatformDashboardSummary(
            generated_at=generated_at,
            cache_expires_at=generated_at
            + timedelta(seconds=cls.CACHE_TTL_SECONDS),
            coverage=DashboardCoverage(
                eligible_tenants=len(tenants),
                successful_tenants=len(results),
                failed_tenants=len(tenants) - len(results),
                partial=bool(failed_sources),
                failed_sources=sorted(failed_sources),
                failure_details=sorted(
                    failure_details, key=lambda item: item["source"]
                ),
            ),
            kpis=DashboardKpis(
                critical_alerts=sum(
                    int(item.get("critical_alerts", 0)) for item in results
                ),
                open_alerts=sum(int(item.get("open_alerts", 0)) for item in results),
                resolved_incidents=sum(
                    item["resolved_clusters"] for item in results
                ),
                total_alerts=sum(item["total_alerts"] for item in results),
                escalated_alerts=sum(
                    item["escalated_alerts"] for item in results
                ),
                active_clusters=sum(item["active_clusters"] for item in results),
                resolved_clusters=sum(
                    item["resolved_clusters"] for item in results
                ),
            ),
            activity=activity,
            recent_activity=recent,
        )
