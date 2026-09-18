from typing import Any, Optional

from fastapi import APIRouter, Depends, Query

from app.api.dependencies.auth import require_platform_admin
from app.schemas.cluster import ClusterStatus
from app.schemas.platform_list import (
    PlatformAlertPage,
    PlatformAlertTypeSchemaPage,
    PlatformClusterPage,
    PlatformPlaybookPage,
)
from app.schemas.user import AuthenticatedUser
from app.schemas.tenant import AlertStats
from app.schemas.playbook import PlaybookStats
from app.services.platform_list_service import PlatformListService


router = APIRouter(tags=["Admin Platform Lists"])


@router.get("/alerts/stats", response_model=AlertStats)
def get_alert_stats(
    q: Optional[str] = Query(None, max_length=512),
    since_hours: Optional[int] = Query(None, ge=1),
    _: AuthenticatedUser = Depends(require_platform_admin),
) -> Any:
    return PlatformListService.alert_stats(q=q, since_hours=since_hours)


@router.get("/playbooks/stats", response_model=PlaybookStats)
def get_playbook_stats(
    _: AuthenticatedUser = Depends(require_platform_admin),
) -> Any:
    return PlatformListService.playbook_stats()


@router.get("/alerts", response_model=PlatformAlertPage)
def list_alerts(
    q: Optional[str] = Query(None, max_length=512),
    skip: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=200),
    since_hours: Optional[int] = Query(None, ge=1),
    _: AuthenticatedUser = Depends(require_platform_admin),
) -> Any:
    items, total = PlatformListService.list_alerts(
        q=q, skip=skip, limit=limit, since_hours=since_hours
    )
    return {"items": items, "total": total, "skip": skip, "limit": limit}


@router.get("/clusters", response_model=PlatformClusterPage)
def list_clusters(
    q: Optional[str] = Query(None, max_length=512),
    skip: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=200),
    status: Optional[ClusterStatus] = None,
    _: AuthenticatedUser = Depends(require_platform_admin),
) -> Any:
    items, total = PlatformListService.list_clusters(
        q=q, skip=skip, limit=limit, cluster_status=status
    )
    return {"items": items, "total": total, "skip": skip, "limit": limit}


@router.get("/alert-type-schemas", response_model=PlatformAlertTypeSchemaPage)
def list_alert_type_schemas(
    q: Optional[str] = Query(None, max_length=512),
    skip: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=200),
    is_active: Optional[bool] = None,
    _: AuthenticatedUser = Depends(require_platform_admin),
) -> Any:
    items, total = PlatformListService.list_schemas(
        q=q, skip=skip, limit=limit, is_active=is_active
    )
    return {"items": items, "total": total, "skip": skip, "limit": limit}


@router.get("/playbooks", response_model=PlatformPlaybookPage)
def list_playbooks(
    q: Optional[str] = Query(None, max_length=512),
    skip: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=200),
    is_active: Optional[bool] = None,
    _: AuthenticatedUser = Depends(require_platform_admin),
) -> Any:
    items, total = PlatformListService.list_playbooks(
        q=q, skip=skip, limit=limit, is_active=is_active
    )
    return {"items": items, "total": total, "skip": skip, "limit": limit}
