from fastapi import APIRouter, Depends

from app.api.dependencies.auth import get_current_user, verify_tenant_access
from app.schemas.enrichment_action import EnrichmentActionDocument
from app.schemas.user import AuthenticatedUser
from app.services.enrichment_action_service import EnrichmentActionService

router = APIRouter(prefix="/tenants/{tenant_id}/enrichment-actions", tags=["Enrichment Actions"])


@router.get("", response_model=list[EnrichmentActionDocument])
def list_authorized_actions(
    tenant_id: str = Depends(verify_tenant_access),
    _: AuthenticatedUser = Depends(get_current_user),
):
    return EnrichmentActionService.authorized_for_tenant(tenant_id)
