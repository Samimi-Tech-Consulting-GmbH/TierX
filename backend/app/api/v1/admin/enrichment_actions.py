from fastapi import APIRouter, Depends, Query, status

from app.api.dependencies.auth import require_platform_admin
from app.schemas.enrichment_action import (
    EnrichmentActionCreated,
    EnrichmentActionDocument,
    EnrichmentActionPage,
    EnrichmentActionUpdate,
    EnrichmentActionWrite,
)
from app.schemas.user import AuthenticatedUser
from app.services.enrichment_action_service import EnrichmentActionService

router = APIRouter(prefix="/enrichment-actions", tags=["Admin Enrichment Actions"])


@router.get("", response_model=EnrichmentActionPage)
def list_actions(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    include_deleted: bool = False,
    _: AuthenticatedUser = Depends(require_platform_admin),
):
    return EnrichmentActionService.list(skip=skip, limit=limit, include_deleted=include_deleted)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=EnrichmentActionCreated)
def create_action(
    body: EnrichmentActionWrite,
    admin: AuthenticatedUser = Depends(require_platform_admin),
):
    return EnrichmentActionService.create(body, admin.email)


@router.get("/{action_code}", response_model=EnrichmentActionDocument)
def get_action(action_code: str, _: AuthenticatedUser = Depends(require_platform_admin)):
    return EnrichmentActionService.get(action_code)


@router.put("/{action_code}", response_model=EnrichmentActionDocument)
def update_action(
    action_code: str,
    body: EnrichmentActionUpdate,
    admin: AuthenticatedUser = Depends(require_platform_admin),
):
    return EnrichmentActionService.update(action_code, body, admin.email)


@router.post("/{action_code}/rotate", response_model=EnrichmentActionCreated)
def rotate_action(
    action_code: str,
    admin: AuthenticatedUser = Depends(require_platform_admin),
):
    return EnrichmentActionService.rotate(action_code, admin.email)


@router.delete("/{action_code}", response_model=EnrichmentActionDocument)
def delete_action(
    action_code: str,
    admin: AuthenticatedUser = Depends(require_platform_admin),
):
    return EnrichmentActionService.soft_delete(action_code, admin.email)
