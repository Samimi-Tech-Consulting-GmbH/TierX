"""TierX HTTP-header access."""

from fastapi import Request


def tierx_header(request: Request, suffix: str) -> str | None:
    canonical = request.headers.get(f"x-tierx-{suffix}")
    canonical = canonical.strip() if canonical else None
    return canonical
