from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class AnalysisModelOutput(BaseModel):
    """Strict evidence-based result returned by the local model."""

    headline: str = Field(min_length=1, max_length=500)
    narrative: str = Field(min_length=1, max_length=10_000)
    kill_chain: list[str] = Field(max_length=32)
    confidence: Literal["HIGH", "MEDIUM", "LOW"]
    recommended_actions: list[str] = Field(max_length=64)
