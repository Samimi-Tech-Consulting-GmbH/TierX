"""TierX environment and HTTP header helpers."""

from __future__ import annotations

import os

from fastapi import HTTPException, Request, status


def env_value(name: str, default: str | None = None) -> str | None:
    """Resolve TierX-prefixed then unprefixed environment variables."""
    for key in (f"TIERX_{name}", name):
        value = os.getenv(key)
        if value is not None:
            return value
    return default


def tierx_header(request: Request, suffix: str, *, required: bool = False) -> str | None:
    """Read a TierX header."""
    canonical = request.headers.get(f"x-tierx-{suffix}")
    canonical = canonical.strip() if canonical else None
    value = canonical
    if required and not value:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Missing X-TierX-{suffix} header.",
        )
    return value


def tierx_headers(**values: str) -> dict[str, str]:
    """Emit TierX headers."""
    headers: dict[str, str] = {}
    for suffix, value in values.items():
        display = "-".join(
            "ID" if part == "id" else "SHA" if part == "sha" else part.capitalize()
            for part in suffix.split("_")
        )
        headers[f"X-TierX-{display}"] = value
    return headers
