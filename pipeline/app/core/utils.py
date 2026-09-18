from __future__ import annotations

from typing import Any


def resolve_path(payload: dict[str, Any], dotted_path: str) -> Any:
    """Walk a dotted key path (e.g. ``result.host``) into a nested dict."""
    current: Any = payload
    for part in dotted_path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current
