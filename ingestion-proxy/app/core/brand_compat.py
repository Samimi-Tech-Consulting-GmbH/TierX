"""TierX HTTP-header compatibility for existing integrations."""

from fastapi import HTTPException, Request, status


def compatible_header(request: Request, suffix: str) -> str | None:
    canonical = request.headers.get(f"x-tierx-{suffix}")
    legacy = request.headers.get(f"x-soc-mind-{suffix}")
    canonical = canonical.strip() if canonical else None
    legacy = legacy.strip() if legacy else None
    if canonical and legacy and canonical != legacy:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Conflicting TierX and legacy {suffix} headers.",
        )
    return canonical or legacy
