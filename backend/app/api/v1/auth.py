from fastapi import APIRouter, HTTPException, status, Depends

from app.schemas.user import LoginRequest, TokenResponse, AuthenticatedUser, UserOut
from app.services.user_service import UserService
from app.core.security import create_access_token
from app.api.dependencies.auth import get_current_user

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/login", response_model=TokenResponse)
def login(credentials: LoginRequest):
    user = UserService.authenticate(credentials.email, credentials.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    token = create_access_token(
        user_id=user.user_id,
        email=user.email,
        role=user.role,
        tenant_id=user.tenant_id,
    )
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserOut)
def get_me(current_user: AuthenticatedUser = Depends(get_current_user)):
    return UserService.get_user_by_id(current_user.user_id)
