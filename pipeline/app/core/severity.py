from __future__ import annotations

from typing import Any


def canonical_severity(value: Any) -> str:
    if isinstance(value, bool) or value is None:
        return "UNKNOWN"
    normalized = str(value).strip().lower()
    if normalized in {"5", "critical", "kritisch"}:
        return "CRITICAL"
    if normalized in {"4", "high", "hoch"}:
        return "HIGH"
    if normalized in {"3", "medium", "mittel"}:
        return "MEDIUM"
    if normalized in {"1", "2", "low", "niedrig"}:
        return "LOW"
    return "UNKNOWN"
