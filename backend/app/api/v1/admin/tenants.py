from fastapi import APIRouter, Depends, Query, status
from typing import List, Optional, Any

from app.schemas.tenant import (
    TenantCreate,
    TenantUpdate,
    TenantDocument,
    TenantPage,
    TenantStatus,
    TenantStatusUpdate,
    PipelineHealthSummary,
    DeadLetterRecord,
    DeadLetterPage,
    AlertDocument,
    AlertPage,
)
from app.schemas.user import AuthenticatedUser
from app.api.dependencies.auth import require_platform_admin
from app.services.tenant_service import TenantService

router = APIRouter(prefix="/tenants", tags=["Admin Tenants"])


@router.post("", status_code=status.HTTP_201_CREATED, response_model=TenantDocument)
def create_tenant(
    tenant_in: TenantCreate,
    admin: AuthenticatedUser = Depends(require_platform_admin),
) -> Any:
    return TenantService.create_tenant(tenant_in, created_by=admin.email)


@router.get("", response_model=List[TenantDocument])
def list_tenants(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    status: Optional[TenantStatus] = None,
    search: Optional[str] = None,
    admin: AuthenticatedUser = Depends(require_platform_admin),
) -> Any:
    return TenantService.get_tenants(
        skip=skip, limit=limit, status=status, search=search
    )


@router.get("/page", response_model=TenantPage)
def list_tenant_page(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=200),
    status: Optional[TenantStatus] = None,
    search: Optional[str] = None,
    admin: AuthenticatedUser = Depends(require_platform_admin),
) -> Any:
    return TenantService.get_tenant_page(
        skip=skip, limit=limit, status=status, search=search
    )


@router.get(
    "/{tenant_id}/pipeline-health-summary",
    response_model=PipelineHealthSummary,
)
def get_tenant_pipeline_health_summary(
    tenant_id: str,
    admin: AuthenticatedUser = Depends(require_platform_admin),
) -> Any:
    return TenantService.get_pipeline_health_summary(tenant_id)


@router.get(
    "/{tenant_id}/dead-letters",
    response_model=DeadLetterPage,
)
def list_tenant_dead_letters(
    tenant_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    since_hours: Optional[int] = Query(None, ge=1),
    admin: AuthenticatedUser = Depends(require_platform_admin),
) -> Any:
    return TenantService.list_dead_letters(tenant_id, skip=skip, limit=limit, since_hours=since_hours)


@router.get(
    "/{tenant_id}/dead-letters/{dead_letter_id}",
    response_model=DeadLetterRecord,
)
def get_tenant_dead_letter(
    tenant_id: str,
    dead_letter_id: str,
    admin: AuthenticatedUser = Depends(require_platform_admin),
) -> Any:
    return TenantService.get_dead_letter(tenant_id, dead_letter_id)


@router.get(
    "/{tenant_id}/alerts",
    response_model=AlertPage,
)
def list_tenant_alerts(
    tenant_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    since_hours: Optional[int] = Query(None, ge=1),
    q: Optional[str] = Query(None, max_length=512),
    admin: AuthenticatedUser = Depends(require_platform_admin),
) -> Any:
    return TenantService.list_alerts(
        tenant_id, skip=skip, limit=limit, since_hours=since_hours, q=q
    )


@router.get(
    "/{tenant_id}/alerts/{alert_id}",
    response_model=AlertDocument,
)
def get_tenant_alert(
    tenant_id: str,
    alert_id: str,
    admin: AuthenticatedUser = Depends(require_platform_admin),
) -> Any:
    return TenantService.get_alert(tenant_id, alert_id)


@router.get("/{tenant_id}", response_model=TenantDocument)
def get_tenant(
    tenant_id: str,
    admin: AuthenticatedUser = Depends(require_platform_admin),
) -> Any:
    return TenantService.get_tenant_by_id(tenant_id)


@router.put("/{tenant_id}", response_model=TenantDocument)
def update_tenant(
    tenant_id: str,
    tenant_in: TenantUpdate,
    admin: AuthenticatedUser = Depends(require_platform_admin),
) -> Any:
    return TenantService.update_tenant(tenant_id, tenant_in)


@router.patch("/{tenant_id}/status", response_model=TenantDocument)
def patch_tenant_status(
    tenant_id: str,
    status_in: TenantStatusUpdate,
    admin: AuthenticatedUser = Depends(require_platform_admin),
) -> Any:
    return TenantService.update_tenant_status(tenant_id, status_in)


@router.get("/{tenant_id}/onboarding-status", response_model=dict)
def get_tenant_onboarding_status(
    tenant_id: str,
    admin: AuthenticatedUser = Depends(require_platform_admin),
) -> Any:
    return TenantService.get_onboarding_status(tenant_id)
