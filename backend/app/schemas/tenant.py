from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any, Union, Literal
from uuid import UUID, uuid4
from pydantic import BaseModel, Field, EmailStr, ConfigDict, field_validator

CORRELATION_SETTING_DEFAULTS = {
    "correlation_debounce_critical_ms": 0,
    "correlation_debounce_high_ms": 120_000,
    "correlation_debounce_medium_ms": 300_000,
    "correlation_debounce_low_ms": 600_000,
}


def validate_tenant_settings(
    value: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if value is None:
        return value
    for name in CORRELATION_SETTING_DEFAULTS:
        if name not in value:
            continue
        setting = value[name]
        if isinstance(setting, bool) or not isinstance(setting, int) or setting < 0:
            raise ValueError(f"{name} must be a non-negative integer")
    return value


class TenantStatus(str, Enum):
    ONBOARDING = "ONBOARDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DELETED = "DELETED"


class TenantBase(BaseModel):
    display_name: str = Field(..., description="Human-readable name")
    contact_email: Optional[EmailStr] = Field(None, description="Primary contact email")
    allowed_source_systems: List[str] = Field(
        default_factory=list, description="Allowed data sources"
    )
    settings: Dict[str, Any] = Field(
        default_factory=dict, description="Tenant configuration overrides"
    )

    _validate_settings = field_validator("settings")(validate_tenant_settings)


class TenantCreate(TenantBase):
    name: str = Field(..., description="Unique URL-friendly slug")


class TenantUpdate(TenantBase):
    display_name: Optional[str] = Field(None, description="Human-readable name")
    contact_email: Optional[EmailStr] = Field(None, description="Primary contact email")
    allowed_source_systems: Optional[List[str]] = Field(
        None, description="Allowed data sources"
    )
    settings: Optional[Dict[str, Any]] = Field(
        None, description="Tenant configuration overrides"
    )


class TenantStatusUpdate(BaseModel):
    status: TenantStatus = Field(..., description="New lifecycle state")


class TenantOut(TenantBase):
    tenant_id: UUID
    name: str
    db_name: str
    status: TenantStatus
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str] = None


class TenantDocument(TenantOut):
    id: Optional[str] = Field(None, alias="_id")

    model_config = ConfigDict(populate_by_name=True)


class TenantPage(BaseModel):
    items: List[TenantDocument]
    total: int
    skip: int
    limit: int


class PipelineHealthSummary(BaseModel):
    """Alert counts for tenant pipeline overview (SM-239 compatible shape)."""

    total_alerts: int = 0
    alerts_last_24h: int = 0
    escalated_count: int = 0
    error_count: int = 0
    dead_letter_count: int = 0
    dead_letters_last_24h: int = 0


class DeadLetterRecord(BaseModel):
    """Document stored in the tenant DB ``dead_letters`` collection."""

    id: str
    alert_id: Optional[str] = None
    tenant_id: Optional[str] = None
    source_system: Optional[str] = None
    alert_type: Optional[str] = None
    status: Optional[str] = None
    kafka_state: Optional[str] = None
    error_type: Optional[str] = None
    error_detail: Optional[str] = None
    failed_stage: Optional[str] = None
    failed_fields: List[Any] = Field(default_factory=list)
    raw_payload: Optional[Any] = None
    received_at: Optional[datetime] = None
    dead_lettered_at: Optional[Union[str, datetime]] = None
    analysis_run_id: Optional[str] = None
    analysis_scope_type: Optional[str] = None
    analysis_scope_id: Optional[str] = None
    requested_analysis_version: Optional[int] = None
    retry_cycle: Optional[int] = None
    source_alert: Optional[str] = None
    fingerprint: Optional[str] = None


class DeadLetterPage(BaseModel):
    items: List[DeadLetterRecord]
    total: int


class AlertDocument(BaseModel):
    """Document stored in the tenant DB ``alerts`` collection."""

    id: str
    alert_id: str
    tenant_id: str
    alert_type: str
    source_system: str
    raw_payload: Optional[Any] = None
    source_reference: Optional[Dict[str, Any]] = None
    normalized_payload: Optional[Dict[str, Any]] = None
    severity: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"] = "UNKNOWN"
    status: Optional[str] = None
    kafka_state: Optional[str] = None
    fingerprint: Optional[str] = None
    validated: Optional[bool] = None
    normalized: Optional[bool] = None
    enriched: Optional[bool] = None
    playbook_id: Optional[str] = None
    playbook_version: Optional[int] = None
    playbook_resolution: Optional[str] = None
    prompt_webhook_context: Optional[Dict[str, Any]] = None
    prompt_webhook_contexts: Optional[List[Dict[str, Any]]] = None
    enrichment_action_batch_id: Optional[str] = None
    enrichment_action_status: Optional[str] = None
    enrichment_action_results: Optional[List[Dict[str, Any]]] = None
    enrichment: Optional[Dict[str, Any]] = None
    cluster_id: Optional[str] = None
    clustering_status: Optional[str] = None
    debounce_outcome: Optional[str] = None
    analysis_type: Optional[str] = None
    correlation_result: Optional[Dict[str, Any]] = None
    analysis_status: Optional[str] = None
    analysis_error: Optional[Dict[str, Any]] = None
    requested_analysis_version: Optional[int] = None
    analyzed_version: Optional[int] = None
    last_analysis_requested_at: Optional[datetime] = None
    last_analyzed_at: Optional[datetime] = None
    alert_analysis: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class AlertPage(BaseModel):
    items: List[AlertDocument]
    total: int


class AlertSeverityCounts(BaseModel):
    CRITICAL: int = 0
    HIGH: int = 0
    MEDIUM: int = 0
    LOW: int = 0
    UNKNOWN: int = 0


class AlertStats(BaseModel):
    filtered_total: int = 0
    severity: AlertSeverityCounts = Field(default_factory=AlertSeverityCounts)


class TenantSelfServiceSettingsUpdate(BaseModel):
    """Tenant-admin editable subset of settings (labeled fields in dashboard)."""

    similarity_threshold: Optional[float] = Field(None, ge=0.0, le=1.0)
    worker_concurrency: Optional[int] = Field(None, ge=1)
    default_model: Optional[str] = Field(None, max_length=128)
    contact_email: Optional[EmailStr] = Field(None, description="Primary contact email")
    correlation_debounce_critical_ms: Optional[int] = Field(None, ge=0)
    correlation_debounce_high_ms: Optional[int] = Field(None, ge=0)
    correlation_debounce_medium_ms: Optional[int] = Field(None, ge=0)
    correlation_debounce_low_ms: Optional[int] = Field(None, ge=0)
