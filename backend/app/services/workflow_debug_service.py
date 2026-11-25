"""Read-only, payload-free index of root workflow executions."""

from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import HTTPException

from app.models.tenant import Tenant
from app.services.platform_list_service import PlatformListService

ExecutionState = Literal[
    "PENDING", "RUNNING", "SUCCEEDED", "SUCCEEDED_WITH_WARNINGS", "FAILED", "CANCELLED"
]


class WorkflowDebugService(PlatformListService):
    FIELDS = {name: 1 for name in (
        "run_id", "alert_id", "definition_ref", "definition_code", "revision",
        "state", "created_at", "started_at", "completed_at", "release_version", "release_sha",
    )}

    @classmethod
    def list_executions(
        cls, *, tenant_id=None, q=None, state=None, since_hours=None,
        release_version=None, skip=0, limit=25,
    ):
        tenants = (
            list(Tenant.objects(tenant_id=tenant_id, status="ACTIVE"))
            if tenant_id else cls._active_tenants()
        )
        if tenant_id and not tenants:
            raise HTTPException(404, "Active tenant required")
        query = {"parent_run_id": {"$in": [None, ""]}}
        search = cls._search(q)
        if search:
            query["$or"] = [
                {field: cls._pattern(search)}
                for field in ("alert_id", "run_id", "definition_ref", "definition_code")
            ]
        if state:
            query["state"] = state
        if release_version:
            query["release_version"] = release_version
        if since_hours:
            query["created_at"] = {"$gte": datetime.now(timezone.utc) - timedelta(hours=since_hours)}

        def query_tenant(tenant):
            db = cls._database(tenant)
            rows = list(db.v2_runs.find(query, {**cls.FIELDS, "_id": 0})
                        .sort([("created_at", -1), ("run_id", 1)]).limit(skip + limit))
            alerts = {row["alert_id"]: row for row in db.alerts.find(
                {"alert_id": {"$in": [row.get("alert_id") for row in rows]}},
                {"_id": 0, "alert_id": 1, "alert_type": 1, "source_system": 1},
            )}
            for row in rows:
                alert = alerts.get(row.get("alert_id"), {})
                row.update(tenant_id=str(tenant.tenant_id), tenant_name=str(tenant.display_name),
                           alert_type=alert.get("alert_type"), source_system=alert.get("source_system"))
            return db.v2_runs.count_documents(query), rows

        rows, total = cls._merge(
            tenants=tenants, worker=query_tenant, skip=skip, limit=limit, q="",
            id_field="run_id", timestamp_field="created_at",
        )
        return {"items": rows, "total": total, "skip": skip, "limit": limit}
