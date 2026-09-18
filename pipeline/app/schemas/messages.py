"""
Pydantic models for the Kafka messages that flow through the pipeline.
Each model corresponds to a topic's message envelope.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ReceivedAlertMessage(BaseModel):
    """Message consumed from the ``received`` topic (produced by ingestion-proxy)."""

    alert_id: str
    tenant_id: str
    alert_type: str
    source_system: str
    raw_payload: dict[str, Any]
    source_reference: dict[str, Any] | None = None
    kafka_state: Literal["RECEIVED"] = "RECEIVED"
    status: Literal["RECEIVED"] = "RECEIVED"


class ValidatedAlertMessage(BaseModel):
    """Message produced to the ``validated`` topic after successful validation."""

    alert_id: str
    tenant_id: str
    alert_type: str
    source_system: str
    raw_payload: dict[str, Any]
    source_reference: dict[str, Any] | None = None
    kafka_state: Literal["VALIDATED"] = "VALIDATED"
    status: Literal["ANALYZING"] = "ANALYZING"
    validated: Literal[True] = True


class NormalizedAlertMessage(BaseModel):
    """Message produced to the ``normalized`` topic after ECS normalization."""

    alert_id: str
    tenant_id: str
    alert_type: str
    source_system: str
    normalized_payload: dict[str, Any]
    raw_payload: dict[str, Any]
    source_reference: dict[str, Any] | None = None
    kafka_state: Literal["NORMALIZED"] = "NORMALIZED"
    status: Literal["ANALYZING"] = "ANALYZING"
    validated: Literal[True] = True
    normalized: Literal[True] = True


class DistinctAlertMessage(BaseModel):
    """Message produced to the ``distinct`` topic after deduplication passes."""

    alert_id: str
    tenant_id: str
    alert_type: str
    source_system: str
    normalized_payload: dict[str, Any]
    raw_payload: dict[str, Any]
    source_reference: dict[str, Any] | None = None
    fingerprint: str
    kafka_state: Literal["DISTINCT"] = "DISTINCT"
    status: Literal["ANALYZING"] = "ANALYZING"
    validated: Literal[True] = True
    normalized: Literal[True] = True


class EnrichedAlertMessage(BaseModel):
    """Message produced to the ``enriched`` topic after playbook prompt attachment."""

    alert_id: str
    tenant_id: str
    alert_type: str
    source_system: str
    normalized_payload: dict[str, Any]
    raw_payload: dict[str, Any]
    source_reference: dict[str, Any] | None = None
    fingerprint: str
    prompt: str | None = None
    kafka_state: Literal["ENRICHED"] = "ENRICHED"
    status: Literal["ANALYZING"] = "ANALYZING"
    validated: Literal[True] = True
    normalized: Literal[True] = True
    enriched: Literal[True] = True


class ClusteredAlertMessage(BaseModel):
    """Versioned request emitted when a cluster is ready for downstream analysis."""

    alert_id: str
    tenant_id: str
    cluster_id: str
    analysis_type: Literal["SINGLE_ALERT_ANALYSIS", "CLUSTER_ANALYSIS"]
    debounce_outcome: Literal[
        "IMMEDIATE",
        "EXPIRED_WITH_CLUSTER",
        "EXPIRED_SOLO_CLUSTER",
        "PROMOTED",
    ]
    requested_analysis_version: int = Field(ge=1)
    trigger_reason: Literal[
        "DEBOUNCE_EXPIRED",
        "PROMOTED",
        "MEMBERSHIP_CHANGED",
        "WINDOW_CAP",
    ]
    is_final: bool
    kafka_state: Literal["CLUSTERED"] = "CLUSTERED"
    status: Literal["ANALYZING"] = "ANALYZING"
