from fastapi import APIRouter, Depends, Query, status
from typing import List, Optional, Any

from app.schemas.user import UserCreate, UserDocument, UserRole, AuthenticatedUser
from app.api.dependencies.auth import require_platform_admin
from app.services.user_service import UserService

router = APIRouter(prefix="/users", tags=["Admin Users"])


@router.post("", status_code=status.HTTP_201_CREATED, response_model=UserDocument)
def create_user(
    user_in: UserCreate,
    admin: AuthenticatedUser = Depends(require_platform_admin),
) -> Any:
    return UserService.create_user(user_in, created_by=admin.email)


@router.get("", response_model=List[UserDocument])
def list_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    tenant_id: Optional[str] = None,
    role: Optional[UserRole] = None,
    admin: AuthenticatedUser = Depends(require_platform_admin),
) -> Any:
    return UserService.get_users(
        skip=skip, limit=limit, tenant_id=tenant_id, role=role
    )


@router.get("/{user_id}", response_model=UserDocument)
def get_user(
    user_id: str,
    admin: AuthenticatedUser = Depends(require_platform_admin),
) -> Any:
    return UserService.get_user_by_id(user_id)
