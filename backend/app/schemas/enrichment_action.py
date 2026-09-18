from __future__ import annotations

from datetime import datetime
from enum import Enum
import ipaddress

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator


class EnrichmentActionTenantScope(str, Enum):
    ALL_TENANTS = "ALL_TENANTS"
    SELECTED_TENANTS = "SELECTED_TENANTS"


class EnrichmentActionWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_code: str = Field(
        ..., min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$"
    )
    name: str = Field(..., min_length=1, max_length=128)
    description: str = Field(..., min_length=1, max_length=2048)
    url: HttpUrl
    timeout_seconds: int = Field(300, ge=1, le=1800)
    enabled: bool = True
    tenant_scope: EnrichmentActionTenantScope = EnrichmentActionTenantScope.ALL_TENANTS
    tenant_ids: list[str] = Field(default_factory=list, max_length=1000)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: HttpUrl) -> HttpUrl:
        if value.scheme != "https":
            raise ValueError("url must use HTTPS")
        if value.username or value.password:
            raise ValueError("url must not contain credentials")
        if value.query:
            raise ValueError("url must not contain a query string")
        if value.fragment:
            raise ValueError("url must not contain a fragment")
        hostname = str(value.host or "").lower().rstrip(".")
        if hostname == "localhost" or hostname.endswith((".localhost", ".local")):
            raise ValueError("url must use a public host")
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            raise ValueError("url must use a public IP address")
        return value

    @model_validator(mode="after")
    def validate_tenant_scope(self):
        self.tenant_ids = sorted(set(self.tenant_ids))
        if self.tenant_scope == EnrichmentActionTenantScope.ALL_TENANTS:
            if self.tenant_ids:
                raise ValueError("tenant_ids must be empty for ALL_TENANTS")
        elif not self.tenant_ids:
            raise ValueError("tenant_ids is required for SELECTED_TENANTS")
        return self


class EnrichmentActionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=128)
    description: str = Field(..., min_length=1, max_length=2048)
    url: HttpUrl
    timeout_seconds: int = Field(300, ge=1, le=1800)
    enabled: bool = True
    tenant_scope: EnrichmentActionTenantScope = EnrichmentActionTenantScope.ALL_TENANTS
    tenant_ids: list[str] = Field(default_factory=list, max_length=1000)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: HttpUrl) -> HttpUrl:
        return EnrichmentActionWrite.validate_url(value)

    @model_validator(mode="after")
    def validate_tenant_scope(self):
        self.tenant_ids = sorted(set(self.tenant_ids))
        if self.tenant_scope == EnrichmentActionTenantScope.ALL_TENANTS:
            if self.tenant_ids:
                raise ValueError("tenant_ids must be empty for ALL_TENANTS")
        elif not self.tenant_ids:
            raise ValueError("tenant_ids is required for SELECTED_TENANTS")
        return self


class EnrichmentActionDocument(BaseModel):
    action_code: str
    name: str
    description: str
    url: str
    timeout_seconds: int
    enabled: bool
    tenant_scope: EnrichmentActionTenantScope
    tenant_ids: list[str]
    key_id: str
    configuration_checksum: str
    created_at: datetime
    updated_at: datetime
    created_by: str
    updated_by: str
    deleted_at: datetime | None = None
    last_used_at: datetime | None = None
    last_status: str | None = None
    last_duration_ms: float | None = None
    last_error_type: str | None = None


class EnrichmentActionCreated(EnrichmentActionDocument):
    secret: str


class EnrichmentActionPage(BaseModel):
    items: list[EnrichmentActionDocument]
    total: int
    skip: int
    limit: int
