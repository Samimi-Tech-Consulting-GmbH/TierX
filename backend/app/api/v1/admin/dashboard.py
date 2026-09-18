from fastapi import APIRouter, Depends

from app.api.dependencies.auth import require_platform_admin
from app.schemas.dashboard import PlatformDashboardSummary
from app.schemas.user import AuthenticatedUser
from app.services.dashboard_service import PlatformDashboardService


router = APIRouter(prefix="/dashboard", tags=["Admin Dashboard"])


@router.get("/summary", response_model=PlatformDashboardSummary)
def get_dashboard_summary(
    _: AuthenticatedUser = Depends(require_platform_admin),
) -> PlatformDashboardSummary:
    return PlatformDashboardService.get_summary()
