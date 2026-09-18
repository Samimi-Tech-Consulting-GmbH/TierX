from __future__ import annotations

import os
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import JSONResponse

from app.api.dependencies.auth import require_platform_admin
from app.core.brand_compat import dual_headers
from app.schemas.user import AuthenticatedUser
from app.services.debug_trace_service import DebugTraceService

router = APIRouter(prefix="/debug", tags=["Admin Debug"])

DEBUG_TRACE_ENABLED = os.getenv("DEBUG_TRACE_ENABLED", "false").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
INGESTION_PROXY_URL = os.getenv(
    "INGESTION_PROXY_URL", "http://ingestion-proxy:8000"
).rstrip("/")


def _disabled() -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": "Debug tracing is disabled for this environment."},
    )


@router.post("/ingest")
async def debug_ingest(
    request: Request,
    admin: AuthenticatedUser = Depends(require_platform_admin),
):
    if not DEBUG_TRACE_ENABLED:
        return _disabled()

    try:
        body: Any = await request.json()
    except Exception:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": "Request body must be valid JSON."},
        )

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{INGESTION_PROXY_URL}/api/v1/alerts/ingest",
                json=body,
                headers=dual_headers(debug_actor=admin.email),
            )
    except httpx.HTTPError:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "The private ingestion service is unavailable."},
        )

    try:
        payload = response.json()
    except ValueError:
        payload = {
            "detail": "The private ingestion service returned an invalid response."
        }
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=payload,
        )
    alert_id = payload.get("alert_id")
    if alert_id:
        payload["trace_path"] = f"/api/v1/admin/debug/traces/{alert_id}"
        payload["trace_ui_path"] = f"/dashboard/admin/debug/alerts/{alert_id}"
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED if response.is_success else response.status_code,
        content=payload,
    )


@router.get("/traces")
def list_debug_traces(
    tenant_id: Optional[str] = None,
    alert_id: Optional[str] = None,
    stage: Optional[str] = None,
    outcome: Optional[str] = None,
    release_version: Optional[str] = None,
    release_sha: Optional[str] = None,
    since_hours: Optional[int] = Query(24, ge=1, le=24 * 30),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    _: AuthenticatedUser = Depends(require_platform_admin),
):
    if not DEBUG_TRACE_ENABLED:
        return _disabled()
    return DebugTraceService.list_traces(
        tenant_id=tenant_id,
        alert_id=alert_id,
        stage=stage,
        outcome=outcome,
        release_version=release_version,
        release_sha=release_sha,
        since_hours=since_hours,
        skip=skip,
        limit=limit,
    )


@router.get("/traces/{alert_id}")
def get_debug_trace(
    alert_id: str,
    _: AuthenticatedUser = Depends(require_platform_admin),
):
    if not DEBUG_TRACE_ENABLED:
        return _disabled()
    return DebugTraceService.get_trace(alert_id)
