from typing import Any

from fastapi import APIRouter, Depends, status

from app.api.dependencies.auth import require_tenant_admin, verify_tenant_access
from app.schemas.user import AuthenticatedUser
from app.schemas.webhook_signing import WebhookSecretCreated, WebhookSecretMetadata
from app.services.webhook_signing_service import WebhookSigningService

router = APIRouter(prefix="/tenants/{tenant_id}", tags=["Webhook signing credentials"])


def _admin_tenant(
    tenant_id: str = Depends(verify_tenant_access),
    user: AuthenticatedUser = Depends(require_tenant_admin),
) -> tuple[str, AuthenticatedUser]:
    return tenant_id, user


@router.get("/webhook-signing-secret", response_model=WebhookSecretMetadata)
def get_tenant_secret(context: tuple[str, AuthenticatedUser] = Depends(_admin_tenant)) -> Any:
    tenant_id, _ = context
    return WebhookSigningService.get_metadata(tenant_id, "TENANT")


@router.post(
    "/webhook-signing-secret",
    response_model=WebhookSecretCreated,
    status_code=status.HTTP_201_CREATED,
)
def rotate_tenant_secret(context: tuple[str, AuthenticatedUser] = Depends(_admin_tenant)) -> Any:
    tenant_id, user = context
    return WebhookSigningService.rotate(tenant_id, "TENANT", user.email)


@router.delete("/webhook-signing-secret", response_model=WebhookSecretMetadata)
def delete_tenant_secret(context: tuple[str, AuthenticatedUser] = Depends(_admin_tenant)) -> Any:
    tenant_id, _ = context
    return WebhookSigningService.delete(tenant_id, "TENANT")


@router.get(
    "/playbooks/{playbook_id}/webhook-signing-secret",
    response_model=WebhookSecretMetadata,
)
def get_playbook_secret(
    playbook_id: str, context: tuple[str, AuthenticatedUser] = Depends(_admin_tenant)
) -> Any:
    tenant_id, _ = context
    return WebhookSigningService.get_metadata(tenant_id, "PLAYBOOK", playbook_id)


@router.post(
    "/playbooks/{playbook_id}/webhook-signing-secret",
    response_model=WebhookSecretCreated,
    status_code=status.HTTP_201_CREATED,
)
def rotate_playbook_secret(
    playbook_id: str, context: tuple[str, AuthenticatedUser] = Depends(_admin_tenant)
) -> Any:
    tenant_id, user = context
    return WebhookSigningService.rotate(tenant_id, "PLAYBOOK", user.email, playbook_id)


@router.delete(
    "/playbooks/{playbook_id}/webhook-signing-secret",
    response_model=WebhookSecretMetadata,
)
def delete_playbook_secret(
    playbook_id: str, context: tuple[str, AuthenticatedUser] = Depends(_admin_tenant)
) -> Any:
    tenant_id, _ = context
    return WebhookSigningService.delete(tenant_id, "PLAYBOOK", playbook_id)
