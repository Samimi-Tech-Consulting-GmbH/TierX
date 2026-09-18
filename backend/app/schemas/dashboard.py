from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class DashboardCoverage(BaseModel):
    eligible_tenants: int
    successful_tenants: int
    failed_tenants: int
    partial: bool
    failed_sources: list[str] = Field(default_factory=list)
    failure_details: list[dict[str, str]] = Field(default_factory=list)


class DashboardKpis(BaseModel):
    critical_alerts: int = 0
    open_alerts: int = 0
    resolved_incidents: int = 0
    total_alerts: int = 0
    escalated_alerts: int = 0
    active_clusters: int = 0
    resolved_clusters: int = 0


class DashboardActivityBucket(BaseModel):
    start_at: datetime
    end_at: datetime
    alerts: int = 0
    dead_letters: int = 0


class DashboardActivity(BaseModel):
    daily: list[DashboardActivityBucket]
    weekly: list[DashboardActivityBucket]
    monthly: list[DashboardActivityBucket]


class DashboardRecentActivity(BaseModel):
    kind: Literal["CRITICAL_ALERT", "CLUSTER"]
    tenant_id: str
    occurred_at: datetime
    alert_id: Optional[str] = None
    cluster_id: Optional[str] = None


class PlatformDashboardSummary(BaseModel):
    generated_at: datetime
    cache_expires_at: datetime
    coverage: DashboardCoverage
    kpis: DashboardKpis
    activity: DashboardActivity
    recent_activity: list[DashboardRecentActivity] = Field(default_factory=list)


class TenantDashboardSummary(BaseModel):
    generated_at: datetime
    cache_expires_at: datetime
    kpis: DashboardKpis
    activity: DashboardActivity
    recent_activity: list[DashboardRecentActivity] = Field(default_factory=list)
