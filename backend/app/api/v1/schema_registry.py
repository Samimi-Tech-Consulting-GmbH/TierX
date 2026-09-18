from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status

from app.schemas.alert_type_schema import (
    AlertTypeSchemaDocument,
    AlertTypeSchemaListResponse,
)
from app.schemas.user import AuthenticatedUser
from app.api.dependencies.auth import (
    get_current_user,
    require_tenant_admin,
    verify_tenant_access,
)
from app.services.alert_type_schema_service import (
    AlertTypeSchemaService,
    AlertTypeSchemaValidationError,
)

router = APIRouter(
    prefix="/tenants/{tenant_id}/schema-registry",
    tags=["Alert-Type Schema Registry"],
)


@router.get("", response_model=AlertTypeSchemaListResponse)
def list_alert_type_schemas(
    tenant_id: str = Depends(verify_tenant_access),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    is_active: Optional[bool] = Query(None),
    alert_type: Optional[str] = Query(
        None,
        description="Exact alert_type key to filter",
    ),
    q: Optional[str] = Query(
        None,
        max_length=512,
        description="Case-insensitive substring match on alert_type (free-text search)",
    ),
    user: AuthenticatedUser = Depends(get_current_user),
) -> Any:
    return AlertTypeSchemaService.list_schemas(
        tenant_id,
        skip=skip,
        limit=limit,
        is_active=is_active,
        alert_type=alert_type,
        alert_type_search=q,
    )


@router.get("/by-id/{schema_id}", response_model=AlertTypeSchemaDocument)
def get_alert_type_schema_by_id(
    schema_id: str,
    tenant_id: str = Depends(verify_tenant_access),
    user: AuthenticatedUser = Depends(get_current_user),
) -> Any:
    return AlertTypeSchemaService.get_schema_by_id(tenant_id, schema_id)


@router.get("/{alert_type}/history", response_model=list[AlertTypeSchemaDocument])
def get_alert_type_schema_history(
    alert_type: str,
    tenant_id: str = Depends(verify_tenant_access),
    user: AuthenticatedUser = Depends(get_current_user),
) -> Any:
    return AlertTypeSchemaService.list_history(tenant_id, alert_type)


@router.get("/{alert_type}", response_model=AlertTypeSchemaDocument)
def get_active_alert_type_schema(
    alert_type: str,
    tenant_id: str = Depends(verify_tenant_access),
    user: AuthenticatedUser = Depends(get_current_user),
) -> Any:
    return AlertTypeSchemaService.get_active_for_alert_type(tenant_id, alert_type)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=AlertTypeSchemaDocument)
async def create_alert_type_schema_draft(
    tenant_id: str = Depends(verify_tenant_access),
    file: UploadFile = File(...),
    playbook_id: Optional[str] = Form(None),
    user: AuthenticatedUser = Depends(require_tenant_admin),
) -> Any:
    filename = (file.filename or "").lower()
    if not filename.endswith((".yml", ".yaml")):
        raise AlertTypeSchemaValidationError(
            [
                {
                    "loc": ["file"],
                    "msg": "File must use .yml or .yaml extension",
                    "type": "value_error",
                }
            ]
        )
    yaml_text = await _read_yaml_upload(file)
    return AlertTypeSchemaService.create_from_yaml(
        tenant_id,
        yaml_text,
        created_by=user.email,
        playbook_id=playbook_id,
    )


@router.post(
    "/{alert_type}/{schema_id}/activate",
    response_model=AlertTypeSchemaDocument,
)
def activate_alert_type_schema(
    alert_type: str,
    schema_id: str,
    tenant_id: str = Depends(verify_tenant_access),
    user: AuthenticatedUser = Depends(require_tenant_admin),
) -> Any:
    return AlertTypeSchemaService.activate(
        tenant_id, alert_type, schema_id, updated_by=user.email
    )


@router.put("/{alert_type}/{schema_id}")
def put_alert_type_schema_forbidden(
    alert_type: str,
    schema_id: str,
    tenant_id: str = Depends(verify_tenant_access),
    user: AuthenticatedUser = Depends(get_current_user),
) -> Any:
    raise HTTPException(
        status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
        detail="Updating an existing alert-type schema version is not supported.",
    )


async def _read_yaml_upload(file: UploadFile) -> str:
    raw_bytes = await file.read()
    try:
        return raw_bytes.decode("utf-8")
    except UnicodeDecodeError as e:
        raise AlertTypeSchemaValidationError(
            [
                {
                    "loc": ["file"],
                    "msg": f"File must be UTF-8 encoded: {e}",
                    "type": "value_error",
                }
            ]
        ) from e
