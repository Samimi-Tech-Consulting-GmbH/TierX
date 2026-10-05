from fastapi import APIRouter, Depends
from app.api.dependencies.auth import get_current_user
from app.schemas.user import AuthenticatedUser
from app.services.release_service import LatestRelease, release_service

router = APIRouter(prefix="/releases", tags=["Releases"])


@router.get("/latest", response_model=LatestRelease)
async def latest_release(_: AuthenticatedUser = Depends(get_current_user)):
    return await release_service.latest()
