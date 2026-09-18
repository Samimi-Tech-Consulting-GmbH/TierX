from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt as pyjwt

from app.core.security import decode_access_token
from app.schemas.user import AuthenticatedUser, UserRole

bearer_scheme = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> AuthenticatedUser:
    token = credentials.credentials
    try:
        payload = decode_access_token(token)
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
        )
    except pyjwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )

    return AuthenticatedUser(
        user_id=payload["sub"],
        email=payload["email"],
        role=payload["role"],
        tenant_id=payload.get("tenant_id"),
    )


def require_platform_admin(
    user: AuthenticatedUser = Depends(get_current_user),
) -> AuthenticatedUser:
    if user.role != UserRole.PLATFORM_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Operation requires PLATFORM_ADMIN role.",
        )
    return user


def require_tenant_admin(
    user: AuthenticatedUser = Depends(get_current_user),
) -> AuthenticatedUser:
    if user.role not in (UserRole.PLATFORM_ADMIN, UserRole.TENANT_ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Operation requires TENANT_ADMIN or PLATFORM_ADMIN role.",
        )
    return user


def require_tenant_admin_only(
    user: AuthenticatedUser = Depends(get_current_user),
) -> AuthenticatedUser:
    """Tenant self-service settings/onboarding for TENANT_ADMIN only (not PLATFORM_ADMIN)."""
    if user.role != UserRole.TENANT_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Operation requires TENANT_ADMIN role.",
        )
    return user


def verify_tenant_access(
    tenant_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
) -> str:
    """Ensure the authenticated user is allowed to access this tenant's resources.

    PLATFORM_ADMIN can access any tenant.  All other roles must match
    the tenant_id embedded in their JWT claim against the URL path parameter.
    """
    if user.role == UserRole.PLATFORM_ADMIN:
        return tenant_id
    if user.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: tenant context mismatch.",
        )
    return tenant_id
