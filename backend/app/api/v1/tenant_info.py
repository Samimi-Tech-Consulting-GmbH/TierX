from fastapi import APIRouter, Depends, Query
from typing import Any, Optional

from app.schemas.tenant import (
    TenantDocument,
    TenantSelfServiceSettingsUpdate,
    PipelineHealthSummary,
    AlertDocument,
    AlertPage,
    AlertStats,
    DeadLetterPage,
    DeadLetterRecord,
)
from app.schemas.user import AuthenticatedUser
from app.api.dependencies.auth import (
    get_current_user,
    verify_tenant_access,
    require_tenant_admin_only,
)
from app.services.tenant_service import TenantService
from app.schemas.dashboard import TenantDashboardSummary
from app.services.dashboard_service import PlatformDashboardService

router = APIRouter(
    prefix="/tenants/{tenant_id}",
    tags=["Tenant Info"],
)


@router.get("", response_model=TenantDocument)
def get_my_tenant(
    tenant_id: str = Depends(verify_tenant_access),
    user: AuthenticatedUser = Depends(get_current_user),
) -> Any:
    return TenantService.get_tenant_by_id(tenant_id)


@router.get("/onboarding-status", response_model=dict)
def get_my_tenant_onboarding_status(
    tenant_id: str = Depends(verify_tenant_access),
    _: AuthenticatedUser = Depends(require_tenant_admin_only),
) -> Any:
    return TenantService.get_onboarding_status(tenant_id)


@router.put("/settings", response_model=TenantDocument)
def update_my_tenant_settings(
    body: TenantSelfServiceSettingsUpdate,
    tenant_id: str = Depends(verify_tenant_access),
    _: AuthenticatedUser = Depends(require_tenant_admin_only),
) -> Any:
    return TenantService.merge_self_service_settings(tenant_id, body)


@router.get("/pipeline-health-summary", response_model=PipelineHealthSummary)
def get_my_pipeline_health_summary(
    tenant_id: str = Depends(verify_tenant_access),
    _: AuthenticatedUser = Depends(get_current_user),
) -> Any:
    return TenantService.get_pipeline_health_summary(tenant_id)


@router.get("/dashboard/summary", response_model=TenantDashboardSummary)
def get_tenant_dashboard_summary(
    tenant_id: str = Depends(verify_tenant_access),
    _: AuthenticatedUser = Depends(get_current_user),
) -> Any:
    return PlatformDashboardService.get_tenant_summary(tenant_id)


@router.get("/alerts", response_model=AlertPage)
def list_my_alerts(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    since_hours: Optional[int] = Query(None, ge=1),
    q: Optional[str] = Query(None, max_length=512),
    tenant_id: str = Depends(verify_tenant_access),
    _: AuthenticatedUser = Depends(get_current_user),
) -> Any:
    return TenantService.list_alerts(
        tenant_id, skip=skip, limit=limit, since_hours=since_hours, q=q
    )


@router.get("/alerts/stats", response_model=AlertStats)
def get_my_alert_stats(
    since_hours: Optional[int] = Query(None, ge=1),
    q: Optional[str] = Query(None, max_length=512),
    tenant_id: str = Depends(verify_tenant_access),
    _: AuthenticatedUser = Depends(get_current_user),
) -> Any:
    return TenantService.get_alert_stats(
        tenant_id, since_hours=since_hours, q=q
    )


@router.get("/alerts/{alert_id}", response_model=AlertDocument)
def get_my_alert(
    alert_id: str,
    tenant_id: str = Depends(verify_tenant_access),
    _: AuthenticatedUser = Depends(get_current_user),
) -> Any:
    return TenantService.get_alert(tenant_id, alert_id)


@router.get("/dead-letters", response_model=DeadLetterPage)
def list_my_dead_letters(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    since_hours: Optional[int] = Query(None, ge=1),
    tenant_id: str = Depends(verify_tenant_access),
    _: AuthenticatedUser = Depends(get_current_user),
) -> Any:
    return TenantService.list_dead_letters(tenant_id, skip=skip, limit=limit, since_hours=since_hours)


@router.get("/dead-letters/{dead_letter_id}", response_model=DeadLetterRecord)
def get_my_dead_letter(
    dead_letter_id: str,
    tenant_id: str = Depends(verify_tenant_access),
    _: AuthenticatedUser = Depends(get_current_user),
) -> Any:
    return TenantService.get_dead_letter(tenant_id, dead_letter_id)
