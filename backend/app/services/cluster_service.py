from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Optional

import mongoengine as me
from fastapi import HTTPException, status

from app.core.errors import ResourceNotFoundError
from app.db.mongodb import DatabaseManager
from app.core.alert_metrics import host_from_alert, severity_from_alert
from app.models.tenant import Tenant
from app.schemas.cluster import (
    ClusterAlertPage,
    ClusterDocument,
    ClusterListItem,
    ClusterPage,
    ClusterSummaryHistory,
)


TRANSITIONS = {
    "OPEN": {"UNDER_INVESTIGATION"},
    "UNDER_INVESTIGATION": {"ESCALATED", "CLOSED", "FALSE_POSITIVE"},
    "ESCALATED": {"CLOSED", "FALSE_POSITIVE"},
    "CLOSED": {"OPEN"},
    "FALSE_POSITIVE": set(),
}


class ClusterService:
    @staticmethod
    def _db(tenant_id: str):
        tenant = Tenant.objects(tenant_id=tenant_id).first()
        if not tenant:
            raise ResourceNotFoundError(f"Tenant with ID {tenant_id} not found")
        alias = DatabaseManager.get_tenant_db_alias(tenant.db_name)
        return me.connection.get_db(alias)

    @classmethod
    def _cluster(cls, tenant_id: str, cluster_id: str) -> dict[str, Any]:
        doc = cls._db(tenant_id)["clusters"].find_one(
            {"tenant_id": tenant_id, "cluster_id": cluster_id},
            {"_id": 0},
        )
        if not doc:
            raise ResourceNotFoundError("Cluster not found")
        return doc

    @classmethod
    def list_clusters(
        cls,
        tenant_id: str,
        *,
        skip: int,
        limit: int,
        cluster_status: Optional[str],
        assigned_to: Optional[str],
        is_open_for_grouping: Optional[bool],
        created_after: Optional[datetime],
        created_before: Optional[datetime],
        q: Optional[str] = None,
    ) -> ClusterPage:
        query: dict[str, Any] = {"tenant_id": tenant_id}
        search = (q or "").strip()[:512]
        if cluster_status and not search:
            query["status"] = cluster_status
        if assigned_to:
            query["assigned_to"] = assigned_to
        if is_open_for_grouping is not None:
            query["is_open_for_grouping"] = is_open_for_grouping
        if created_after or created_before:
            query["created_at"] = {}
            if created_after:
                query["created_at"]["$gte"] = created_after
            if created_before:
                query["created_at"]["$lte"] = created_before
        if search:
            pattern = re.compile(re.escape(search), re.IGNORECASE)
            query["$or"] = [
                {"cluster_id": pattern},
                {"summary.headline": pattern},
                {"summary.narrative": pattern},
                {"correlation_basis.mitre_techniques": pattern},
            ]

        collection = cls._db(tenant_id)["clusters"]
        total = collection.count_documents(query)
        if search:
            cursor = collection.aggregate(
                [
                    {"$match": query},
                    {
                        "$addFields": {
                            "_exact_rank": {
                                "$cond": [{"$eq": ["$cluster_id", search]}, 0, 1]
                            }
                        }
                    },
                    {"$sort": {"_exact_rank": 1, "created_at": -1, "cluster_id": 1}},
                    {"$skip": skip},
                    {"$limit": limit},
                    {"$project": {"_id": 0, "_exact_rank": 0}},
                ]
            )
        else:
            cursor = (
                collection.find(query, {"_id": 0})
                .sort([("created_at", -1), ("cluster_id", 1)])
                .skip(skip)
                .limit(limit)
            )
        return ClusterPage(
            items=[ClusterListItem(**doc) for doc in cursor],
            total=total,
        )

    @classmethod
    def get_cluster(cls, tenant_id: str, cluster_id: str) -> ClusterDocument:
        cluster = cls._cluster(tenant_id, cluster_id)
        alerts = cls._db(tenant_id)["alerts"].find(
            {"alert_id": {"$in": cluster.get("alert_ids") or []}},
            {"_id": 0, "normalized_payload": 1},
        )
        cluster["affected_host_count"] = len(
            {host for alert in alerts if (host := host_from_alert(alert))}
        )
        return ClusterDocument(**cluster)

    @classmethod
    def summary_history(
        cls, tenant_id: str, cluster_id: str
    ) -> ClusterSummaryHistory:
        cluster = cls._cluster(tenant_id, cluster_id)
        summary = cluster.get("summary") or {}
        items = list(summary.get("history") or [])
        current = {
            key: value for key, value in summary.items() if key != "history"
        }
        if current.get("version") is not None:
            items.append(current)
        items.sort(key=lambda value: int(value.get("version", 0)))
        return ClusterSummaryHistory(items=items)

    @classmethod
    def update_status(
        cls, tenant_id: str, cluster_id: str, new_status: str
    ) -> ClusterDocument:
        current = cls._cluster(tenant_id, cluster_id)
        old_status = current.get("status", "OPEN")
        if new_status not in TRANSITIONS.get(old_status, set()):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid cluster status transition: {old_status} -> {new_status}",
            )
        now = datetime.now(timezone.utc)
        values: dict[str, Any] = {"status": new_status, "updated_at": now}
        if new_status in {"CLOSED", "FALSE_POSITIVE"}:
            values["closed_at"] = now
        elif old_status == "CLOSED" and new_status == "OPEN":
            values["closed_at"] = None
        doc = cls._db(tenant_id)["clusters"].find_one_and_update(
            {"tenant_id": tenant_id, "cluster_id": cluster_id},
            {"$set": values},
            return_document=True,
            projection={"_id": 0},
        )
        return ClusterDocument(**doc)

    @classmethod
    def assign(
        cls, tenant_id: str, cluster_id: str, assigned_to: Optional[str]
    ) -> ClusterDocument:
        cls._cluster(tenant_id, cluster_id)
        doc = cls._db(tenant_id)["clusters"].find_one_and_update(
            {"tenant_id": tenant_id, "cluster_id": cluster_id},
            {
                "$set": {
                    "assigned_to": assigned_to,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
            return_document=True,
            projection={"_id": 0},
        )
        return ClusterDocument(**doc)

    @classmethod
    def set_verdict(
        cls, tenant_id: str, cluster_id: str, verdict: str
    ) -> ClusterDocument:
        current = cls._cluster(tenant_id, cluster_id)
        if current.get("status") not in {"CLOSED", "FALSE_POSITIVE"}:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Verdict can only be set on CLOSED or FALSE_POSITIVE clusters",
            )
        doc = cls._db(tenant_id)["clusters"].find_one_and_update(
            {"tenant_id": tenant_id, "cluster_id": cluster_id},
            {
                "$set": {
                    "verdict": verdict,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
            return_document=True,
            projection={"_id": 0},
        )
        return ClusterDocument(**doc)

    @classmethod
    def add_note(
        cls, tenant_id: str, cluster_id: str, author: str, note: str
    ) -> ClusterDocument:
        cls._cluster(tenant_id, cluster_id)
        now = datetime.now(timezone.utc)
        doc = cls._db(tenant_id)["clusters"].find_one_and_update(
            {"tenant_id": tenant_id, "cluster_id": cluster_id},
            {
                "$push": {
                    "analyst_notes": {
                        "author": author,
                        "note": note,
                        "created_at": now,
                    }
                },
                "$set": {"updated_at": now},
            },
            return_document=True,
            projection={"_id": 0},
        )
        return ClusterDocument(**doc)

    @classmethod
    def alerts(
        cls, tenant_id: str, cluster_id: str, skip: int, limit: int
    ) -> ClusterAlertPage:
        cluster = cls._cluster(tenant_id, cluster_id)
        query = {"alert_id": {"$in": cluster.get("alert_ids") or []}}
        collection = cls._db(tenant_id)["alerts"]
        total = collection.count_documents(query)
        docs = list(
            collection.find(query, {"_id": 0})
            .sort([("created_at", 1), ("alert_id", 1)])
            .skip(skip)
            .limit(limit)
        )
        for doc in docs:
            doc["severity"] = severity_from_alert(doc)
        return ClusterAlertPage(items=docs, total=total)
