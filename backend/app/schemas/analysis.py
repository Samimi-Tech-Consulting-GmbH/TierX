from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


AnalysisScopeType = Literal["ALERT", "CLUSTER"]
AnalysisRunState = Literal[
    "PENDING", "RUNNING", "SUCCEEDED", "FAILED", "SUPERSEDED"
]


class AnalysisRun(BaseModel):
    analysis_run_id: str
    tenant_id: str
    analysis_scope_type: AnalysisScopeType
    analysis_scope_id: str
    requested_analysis_version: int
    state: AnalysisRunState
    configuration_revision: Optional[int] = None
    retry_cycle: int = 0
    attempts_total: int = 0
    attempts_in_cycle: int = 0
    model: Optional[str] = None
    model_digest: Optional[str] = None
    prompt_source: Optional[str] = None
    prompt_sources: list[dict[str, Any]] = Field(default_factory=list)
    last_error: Optional[dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class AnalysisRunPage(BaseModel):
    items: list[AnalysisRun]
    total: int


class AnalysisRetryResponse(BaseModel):
    analysis_run_id: str
    analysis_scope_type: AnalysisScopeType
    analysis_scope_id: str
    requested_analysis_version: int
    retry_cycle: int
    state: Literal["PENDING"] = "PENDING"


class SystemPromptDocument(BaseModel):
    template_id: str
    version: int
    prompt: str
    is_active: bool
    created_by: str
    created_at: datetime
    updated_at: datetime


class SystemPromptUpdate(BaseModel):
    prompt: str = Field(min_length=1, max_length=50_000)
    expected_version: Optional[int] = Field(default=None, ge=1)
