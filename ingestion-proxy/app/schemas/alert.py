from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class ErrorType(str, Enum):
    ALERT_SCHEMA_MISSING = "ALERT_SCHEMA_MISSING"
    UNKNOWN_SOURCE = "UNKNOWN_SOURCE"
    UNKNOWN_TENANT = "UNKNOWN_TENANT"


class IngestAlertRequest(BaseModel):
    tenant_id: str = Field(..., description="Tenant identifier")
    source_system: str = Field(..., description="Origin system (e.g. splunk, sentinel)")
    raw_payload: dict[str, Any] = Field(..., description="Raw alert payload from the source")
    alert_type: str = Field(..., description="Logical alert type / classification from source")
    timestamp: str = Field(
        ...,
        description="Event or submission time from the client (ISO-8601 recommended)",
    )
    source_reference: dict[str, Any] | None = Field(
        default=None,
        description="Sanitized transport provenance supplied by a trusted internal adapter",
    )


class ReceivedAlertMessage(BaseModel):
    alert_id: str = Field(description="Server-assigned unique id for this alert")
    tenant_id: str
    alert_type: str
    source_system: str
    raw_payload: dict[str, Any]
    source_reference: dict[str, Any] | None = None
    kafka_state: Literal["RECEIVED"] = "RECEIVED"
    status: Literal["RECEIVED"] = "RECEIVED"


class DeadLetterMessage(BaseModel):
    alert_id: str = Field(description="Server-assigned unique id for this alert")
    tenant_id: str | None = None
    alert_type: str | None = None
    source_system: str | None = None
    raw_payload: dict[str, Any] | None = None
    status: Literal["FAILED"] = "FAILED"
    kafka_state: Literal["DLQ"] = "DLQ"
    dead_lettered_at: str = Field(description="ISO-8601 timestamp when the message was dead-lettered")
    error_type: ErrorType
    error_detail: str | None = Field(None, description="Human-readable explanation of the failure")


class IngestAlertResponse(BaseModel):
    alert_id: str = Field(description="Server-assigned unique id for this alert")
    tenant_id: str
    source_system: str
    alert_type: str
    raw_payload: dict[str, Any]
    timestamp: str
    source_reference: dict[str, Any] | None = None
    kafka_state: Literal["RECEIVED"] = "RECEIVED"
    status: Literal["RECEIVED"] = "RECEIVED"
