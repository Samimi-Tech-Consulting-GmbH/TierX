from fastapi import APIRouter, Depends, Query, HTTPException, status
from typing import List, Any

from app.schemas.user import (
    TenantUserCreate,
    UserCreate,
    UserDocument,
    UserRole,
    AuthenticatedUser,
)
from app.api.dependencies.auth import require_tenant_admin, verify_tenant_access
from app.services.user_service import UserService

router = APIRouter(
    prefix="/tenants/{tenant_id}/users",
    tags=["Tenant Users"],
)

ROLES_TENANT_ADMIN_CAN_CREATE = {UserRole.TENANT_OPERATOR}


@router.get("", response_model=List[UserDocument])
def list_tenant_users(
    tenant_id: str = Depends(verify_tenant_access),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    user: AuthenticatedUser = Depends(require_tenant_admin),
) -> Any:
    return UserService.get_users(skip=skip, limit=limit, tenant_id=tenant_id)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=UserDocument)
def create_tenant_user(
    body: TenantUserCreate,
    tenant_id: str = Depends(verify_tenant_access),
    user: AuthenticatedUser = Depends(require_tenant_admin),
) -> Any:
    if (
        user.role == UserRole.TENANT_ADMIN
        and body.role not in ROLES_TENANT_ADMIN_CAN_CREATE
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="TENANT_ADMIN can only create users with TENANT_OPERATOR role.",
        )

    if body.role == UserRole.PLATFORM_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot create PLATFORM_ADMIN through tenant-scoped endpoint.",
        )

    full_create = UserCreate(
        email=body.email,
        password=body.password,
        role=body.role,
        tenant_id=tenant_id,
    )
    return UserService.create_user(full_create, created_by=user.email)
