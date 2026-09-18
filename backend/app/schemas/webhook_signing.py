from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel


class WebhookSecretMetadata(BaseModel):
    configured: bool
    scope: Literal["TENANT", "PLAYBOOK", "NONE"]
    key_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    tenant_fallback_configured: bool = False
    effective_scope: Literal["TENANT", "PLAYBOOK", "NONE"] = "NONE"


class WebhookSecretCreated(WebhookSecretMetadata):
    secret: str
