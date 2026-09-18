from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from typing import List, Optional, Any

from app.schemas.playbook import (
    PlaybookDocument,
    PlaybookListItem,
    PlaybookReplace,
    PlaybookVersionSummary,
    PlaybookStats,
)
from app.schemas.user import AuthenticatedUser
from app.api.dependencies.auth import get_current_user, require_tenant_admin, verify_tenant_access
from app.services.playbook_service import PlaybookService, PlaybookValidationError

router = APIRouter(
    prefix="/tenants/{tenant_id}/playbooks",
    tags=["Playbooks"],
)


@router.get("", response_model=List[PlaybookListItem])
def list_playbooks(
    tenant_id: str = Depends(verify_tenant_access),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    is_active: Optional[bool] = Query(None),
    alert_type: Optional[str] = Query(
        None,
        description="Playbooks that include this string in alert_types",
    ),
    user: AuthenticatedUser = Depends(get_current_user),
) -> Any:
    return PlaybookService.list_playbooks(
        tenant_id,
        skip=skip,
        limit=limit,
        is_active=is_active,
        alert_type=alert_type,
    )


@router.get("/stats", response_model=PlaybookStats)
def get_playbook_stats(
    tenant_id: str = Depends(verify_tenant_access),
    user: AuthenticatedUser = Depends(get_current_user),
) -> Any:
    return PlaybookService.stats(tenant_id)


@router.get(
    "/{playbook_id}/versions",
    response_model=List[PlaybookVersionSummary],
)
def list_playbook_versions(
    playbook_id: str,
    tenant_id: str = Depends(verify_tenant_access),
    user: AuthenticatedUser = Depends(get_current_user),
) -> Any:
    return PlaybookService.list_playbook_versions(tenant_id, playbook_id)


@router.put("/{playbook_id}/yaml", response_model=PlaybookDocument)
async def put_playbook_yaml(
    playbook_id: str,
    tenant_id: str = Depends(verify_tenant_access),
    name: str = Form(..., min_length=1, max_length=512),
    file: UploadFile = File(...),
    user: AuthenticatedUser = Depends(require_tenant_admin),
) -> Any:
    filename = (file.filename or "").lower()
    if not filename.endswith((".yml", ".yaml")):
        raise PlaybookValidationError(
            [
                {
                    "loc": ["file"],
                    "msg": "File must use .yml or .yaml extension",
                    "type": "value_error",
                }
            ]
        )
    yaml_text = await _read_yaml_upload(file)
    return PlaybookService.append_revision_from_yaml(
        tenant_id,
        playbook_id,
        name,
        yaml_text,
        created_by=user.email,
    )


@router.get("/{playbook_id}", response_model=PlaybookDocument)
def get_playbook(
    playbook_id: str,
    tenant_id: str = Depends(verify_tenant_access),
    user: AuthenticatedUser = Depends(get_current_user),
) -> Any:
    return PlaybookService.get_playbook(tenant_id, playbook_id)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=PlaybookDocument)
async def create_playbook_multipart(
    tenant_id: str = Depends(verify_tenant_access),
    name: str = Form(..., min_length=1, max_length=512),
    file: UploadFile = File(...),
    user: AuthenticatedUser = Depends(require_tenant_admin),
) -> Any:
    filename = (file.filename or "").lower()
    if not filename.endswith((".yml", ".yaml")):
        raise PlaybookValidationError(
            [
                {
                    "loc": ["file"],
                    "msg": "File must use .yml or .yaml extension",
                    "type": "value_error",
                }
            ]
        )

    yaml_text = await _read_yaml_upload(file)

    return PlaybookService.create_from_yaml(
        tenant_id,
        name,
        yaml_text,
        created_by=user.email,
    )


@router.put("/{playbook_id}", response_model=PlaybookDocument)
def put_playbook(
    playbook_id: str,
    body: PlaybookReplace,
    tenant_id: str = Depends(verify_tenant_access),
    user: AuthenticatedUser = Depends(require_tenant_admin),
) -> Any:
    return PlaybookService.replace_playbook(
        tenant_id, playbook_id, body, created_by=user.email
    )


@router.delete("/{playbook_id}", response_model=PlaybookDocument)
def delete_playbook(
    playbook_id: str,
    tenant_id: str = Depends(verify_tenant_access),
    user: AuthenticatedUser = Depends(require_tenant_admin),
) -> Any:
    return PlaybookService.soft_delete(tenant_id, playbook_id)


async def _read_yaml_upload(file: UploadFile) -> str:
    raw_bytes = await file.read()
    try:
        return raw_bytes.decode("utf-8")
    except UnicodeDecodeError as e:
        raise PlaybookValidationError(
            [
                {
                    "loc": ["file"],
                    "msg": f"File must be UTF-8 encoded: {e}",
                    "type": "value_error",
                }
            ]
        ) from e
