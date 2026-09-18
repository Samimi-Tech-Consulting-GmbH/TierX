"""Permanent TierX compatibility adapters for legacy clients."""

from __future__ import annotations

import os

from fastapi import HTTPException, Request, status


def env_value(name: str, default: str | None = None) -> str | None:
    """Resolve canonical, unprefixed, then legacy environment variables."""
    for key in (f"TIERX_{name}", name, f"SOC_MIND_{name}"):
        value = os.getenv(key)
        if value is not None:
            return value
    return default


def compatible_header(request: Request, suffix: str, *, required: bool = False) -> str | None:
    """Read TierX/legacy headers and reject ambiguous requests."""
    canonical = request.headers.get(f"x-tierx-{suffix}")
    legacy = request.headers.get(f"x-soc-mind-{suffix}")
    canonical = canonical.strip() if canonical else None
    legacy = legacy.strip() if legacy else None
    if canonical and legacy and canonical != legacy:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Conflicting TierX and legacy {suffix} headers.",
        )
    value = canonical or legacy
    if required and not value:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Missing X-TierX-{suffix} header.",
        )
    return value


def dual_headers(**values: str) -> dict[str, str]:
    """Emit canonical and legacy names with byte-identical values."""
    headers: dict[str, str] = {}
    for suffix, value in values.items():
        display = "-".join(
            "ID" if part == "id" else "SHA" if part == "sha" else part.capitalize()
            for part in suffix.split("_")
        )
        headers[f"X-TierX-{display}"] = value
        headers[f"X-SOC-Mind-{display}"] = value
    return headers
