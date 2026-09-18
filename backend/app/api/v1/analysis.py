from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.dependencies.auth import (
    get_current_user,
    require_platform_admin,
    require_tenant_admin,
    verify_tenant_access,
)
from app.schemas.analysis import (
    AnalysisRetryResponse,
    AnalysisRunPage,
    SystemPromptDocument,
    SystemPromptUpdate,
)
from app.schemas.user import AuthenticatedUser
from app.services.analysis_service import AnalysisService

router = APIRouter(tags=["Analysis"])


@router.get(
    "/tenants/{tenant_id}/alerts/{alert_id}/analysis/runs",
    response_model=AnalysisRunPage,
)
def alert_runs(
    alert_id: str,
    tenant_id: str = Depends(verify_tenant_access),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    _: AuthenticatedUser = Depends(get_current_user),
):
    return AnalysisService.list_runs(
        tenant_id, "ALERT", alert_id, skip=skip, limit=limit
    )


@router.get(
    "/tenants/{tenant_id}/clusters/{cluster_id}/analysis/runs",
    response_model=AnalysisRunPage,
)
def cluster_runs(
    cluster_id: str,
    tenant_id: str = Depends(verify_tenant_access),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    _: AuthenticatedUser = Depends(get_current_user),
):
    return AnalysisService.list_runs(
        tenant_id, "CLUSTER", cluster_id, skip=skip, limit=limit
    )


@router.post(
    "/tenants/{tenant_id}/clusters/{cluster_id}/analysis/retry",
    response_model=AnalysisRetryResponse,
)
def retry_cluster(
    cluster_id: str,
    tenant_id: str = Depends(verify_tenant_access),
    _: AuthenticatedUser = Depends(require_tenant_admin),
):
    return AnalysisService.retry(tenant_id, "CLUSTER", cluster_id)


@router.get(
    "/admin/analysis/system-prompt",
    response_model=SystemPromptDocument,
)
def get_system_prompt(
    _: AuthenticatedUser = Depends(require_platform_admin),
):
    return AnalysisService.get_system_prompt()


@router.put(
    "/admin/analysis/system-prompt",
    response_model=SystemPromptDocument,
)
def put_system_prompt(
    body: SystemPromptUpdate,
    admin: AuthenticatedUser = Depends(require_platform_admin),
):
    return AnalysisService.update_system_prompt(
        body.prompt, admin.email, body.expected_version
    )
