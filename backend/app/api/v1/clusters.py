from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query

from app.api.dependencies.auth import (
    get_current_user,
    require_tenant_admin,
    verify_tenant_access,
)
from app.schemas.cluster import (
    ClusterAlertPage,
    ClusterAssignUpdate,
    ClusterDocument,
    ClusterNoteCreate,
    ClusterPage,
    ClusterStatusUpdate,
    ClusterSummaryHistory,
    ClusterVerdictUpdate,
)
from app.schemas.user import AuthenticatedUser
from app.services.cluster_service import ClusterService

router = APIRouter(prefix="/tenants/{tenant_id}/clusters", tags=["Clusters"])


@router.get("", response_model=ClusterPage)
def list_clusters(
    tenant_id: str = Depends(verify_tenant_access),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    status: Optional[str] = None,
    assigned_to: Optional[str] = None,
    is_open_for_grouping: Optional[bool] = None,
    created_after: Optional[datetime] = None,
    created_before: Optional[datetime] = None,
    q: Optional[str] = Query(None, max_length=512),
    _: AuthenticatedUser = Depends(get_current_user),
) -> Any:
    return ClusterService.list_clusters(
        tenant_id,
        skip=skip,
        limit=limit,
        cluster_status=status,
        assigned_to=assigned_to,
        is_open_for_grouping=is_open_for_grouping,
        created_after=created_after,
        created_before=created_before,
        q=q,
    )


@router.get("/{cluster_id}", response_model=ClusterDocument)
def get_cluster(
    cluster_id: str,
    tenant_id: str = Depends(verify_tenant_access),
    _: AuthenticatedUser = Depends(get_current_user),
) -> Any:
    return ClusterService.get_cluster(tenant_id, cluster_id)


@router.get(
    "/{cluster_id}/summary/history", response_model=ClusterSummaryHistory
)
def get_summary_history(
    cluster_id: str,
    tenant_id: str = Depends(verify_tenant_access),
    _: AuthenticatedUser = Depends(get_current_user),
) -> Any:
    return ClusterService.summary_history(tenant_id, cluster_id)


@router.patch("/{cluster_id}/status", response_model=ClusterDocument)
def update_status(
    cluster_id: str,
    body: ClusterStatusUpdate,
    tenant_id: str = Depends(verify_tenant_access),
    _: AuthenticatedUser = Depends(require_tenant_admin),
) -> Any:
    return ClusterService.update_status(tenant_id, cluster_id, body.status)


@router.patch("/{cluster_id}/assign", response_model=ClusterDocument)
def assign_cluster(
    cluster_id: str,
    body: ClusterAssignUpdate,
    tenant_id: str = Depends(verify_tenant_access),
    _: AuthenticatedUser = Depends(require_tenant_admin),
) -> Any:
    return ClusterService.assign(tenant_id, cluster_id, body.assigned_to)


@router.patch("/{cluster_id}/verdict", response_model=ClusterDocument)
def set_verdict(
    cluster_id: str,
    body: ClusterVerdictUpdate,
    tenant_id: str = Depends(verify_tenant_access),
    _: AuthenticatedUser = Depends(require_tenant_admin),
) -> Any:
    return ClusterService.set_verdict(tenant_id, cluster_id, body.verdict)


@router.post("/{cluster_id}/notes", response_model=ClusterDocument)
def add_note(
    cluster_id: str,
    body: ClusterNoteCreate,
    tenant_id: str = Depends(verify_tenant_access),
    user: AuthenticatedUser = Depends(require_tenant_admin),
) -> Any:
    return ClusterService.add_note(tenant_id, cluster_id, user.email, body.note)


@router.get("/{cluster_id}/alerts", response_model=ClusterAlertPage)
def get_cluster_alerts(
    cluster_id: str,
    tenant_id: str = Depends(verify_tenant_access),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    _: AuthenticatedUser = Depends(get_current_user),
) -> Any:
    return ClusterService.alerts(tenant_id, cluster_id, skip, limit)
