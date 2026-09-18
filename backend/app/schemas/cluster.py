from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


ClusterStatus = Literal[
    "OPEN", "UNDER_INVESTIGATION", "ESCALATED", "CLOSED", "FALSE_POSITIVE"
]
Verdict = Literal["TRUE_POSITIVE", "FALSE_POSITIVE", "BENIGN"]


class ClusterDocument(BaseModel):
    cluster_id: str
    tenant_id: str
    lead_alert_id: str
    alert_ids: list[str]
    alert_count: int
    affected_host_count: Optional[int] = None
    is_open_for_grouping: bool
    debounce_expires_at: datetime
    grouping_window_expires_at: datetime
    correlation_basis: dict[str, Any] = Field(default_factory=dict)
    first_seen: datetime
    last_seen: datetime
    window_seconds: Optional[int] = None
    severity: dict[str, Any] = Field(default_factory=dict)
    debounce_outcome: Optional[str] = None
    clustering_status: Optional[str] = None
    analysis_type: str
    analyzed_version: int = 0
    analyzed_alert_count: int = 0
    last_analysis_requested_at: Optional[datetime] = None
    requested_analysis_version: int = 0
    last_analyzed_at: Optional[datetime] = None
    summary: Optional[dict[str, Any]] = None
    analysis_status: Optional[str] = None
    analysis_error: Optional[dict[str, Any]] = None
    status: ClusterStatus = "OPEN"
    assigned_to: Optional[str] = None
    escalated_to: Optional[str] = None
    verdict: Optional[Verdict] = None
    analyst_notes: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    closed_at: Optional[datetime] = None


class ClusterListItem(BaseModel):
    cluster_id: str
    tenant_id: str
    status: ClusterStatus
    clustering_status: Optional[str] = None
    alert_count: int
    severity: dict[str, Any] = Field(default_factory=dict)
    first_seen: datetime
    last_seen: datetime
    assigned_to: Optional[str] = None
    is_open_for_grouping: bool
    summary: Optional[dict[str, Any]] = None
    analysis_status: Optional[str] = None
    analysis_error: Optional[dict[str, Any]] = None
    analyzed_version: int = 0
    requested_analysis_version: int = 0
    last_analyzed_at: Optional[datetime] = None
    correlation_basis: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class ClusterPage(BaseModel):
    items: list[ClusterListItem]
    total: int


class ClusterStatusUpdate(BaseModel):
    status: ClusterStatus


class ClusterAssignUpdate(BaseModel):
    assigned_to: Optional[str]


class ClusterVerdictUpdate(BaseModel):
    verdict: Verdict


class ClusterNoteCreate(BaseModel):
    note: str = Field(min_length=1, max_length=10_000)


class ClusterAlertPage(BaseModel):
    items: list[dict[str, Any]]
    total: int


class ClusterSummaryHistory(BaseModel):
    items: list[dict[str, Any]]
