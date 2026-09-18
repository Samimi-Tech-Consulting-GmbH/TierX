from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, EmailStr, ConfigDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PLATFORM_ADMIN"
    TENANT_ADMIN = "TENANT_ADMIN"
    TENANT_OPERATOR = "TENANT_OPERATOR"


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    role: UserRole
    tenant_id: Optional[str] = Field(
        None, description="Required for TENANT_ADMIN and TENANT_OPERATOR roles"
    )


class TenantUserCreate(BaseModel):
    """Schema for tenant-scoped user creation (tenant_id comes from the URL)."""
    email: EmailStr
    password: str = Field(..., min_length=8)
    role: UserRole = Field(
        UserRole.TENANT_OPERATOR,
        description="Role to assign; TENANT_ADMIN callers can only create TENANT_OPERATOR",
    )


class UserOut(BaseModel):
    user_id: str
    email: EmailStr
    role: UserRole
    tenant_id: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str] = None


class UserDocument(UserOut):
    id: Optional[str] = Field(None, alias="_id")

    model_config = ConfigDict(populate_by_name=True)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class AuthenticatedUser(BaseModel):
    user_id: str
    email: str
    role: UserRole
    tenant_id: Optional[str] = None
