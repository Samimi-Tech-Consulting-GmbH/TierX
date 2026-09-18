from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from app.schemas.jira_integration import (
    MAX_JIRA_ATTACHMENT_BYTES,
    JiraAttachmentUploadResponse,
    JiraCommentReceipt,
    JiraConnectionInfo,
    JiraSubmissionCreate,
    JiraSubmissionResponse,
    JiraSubmissionFailure,
)
from app.services.jira_integration_service import JiraIntegrationService
from app.core.brand_compat import compatible_header

router = APIRouter(prefix="/integrations/jira", tags=["Jira Integration"])


def require_jira_integration(request: Request) -> dict[str, Any]:
    integration_id = compatible_header(request, "integration-id") or ""
    authorization = request.headers.get("authorization", "")
    scheme, _, secret = authorization.partition(" ")
    if not integration_id or scheme.lower() != "bearer" or not secret.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A Jira integration ID and Bearer credential are required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return JiraIntegrationService.authenticate(integration_id, secret.strip())


@router.get("/connection", response_model=JiraConnectionInfo)
def test_jira_connection(
    integration: dict[str, Any] = Depends(require_jira_integration),
):
    return JiraIntegrationService.connection_info(integration)


@router.post(
    "/submissions",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JiraSubmissionResponse,
)
def create_jira_submission(
    body: JiraSubmissionCreate,
    integration: dict[str, Any] = Depends(require_jira_integration),
):
    return JiraIntegrationService.create_submission(integration, body)


@router.put(
    "/submissions/{submission_id}/attachments/{attachment_id}",
    response_model=JiraAttachmentUploadResponse,
)
async def upload_jira_attachment(
    submission_id: str,
    attachment_id: str,
    request: Request,
    x_content_sha256: str = Header(..., min_length=64, max_length=64),
    integration: dict[str, Any] = Depends(require_jira_integration),
):
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > MAX_JIRA_ATTACHMENT_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Jira attachment exceeds the 5 MiB limit.",
            )
        content.extend(chunk)
    return JiraIntegrationService.upload_attachment(
        integration,
        submission_id,
        attachment_id,
        bytes(content),
        x_content_sha256,
        request.headers.get("content-type"),
    )


@router.post(
    "/submissions/{submission_id}/finalize",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JiraSubmissionResponse,
)
async def finalize_jira_submission(
    submission_id: str,
    integration: dict[str, Any] = Depends(require_jira_integration),
):
    return await JiraIntegrationService.finalize_submission(integration, submission_id)


@router.get(
    "/submissions/{submission_id}", response_model=JiraSubmissionResponse
)
def get_jira_submission(
    submission_id: str,
    integration: dict[str, Any] = Depends(require_jira_integration),
):
    return JiraIntegrationService.get_submission(integration, submission_id)


@router.post(
    "/submissions/{submission_id}/comments", response_model=JiraSubmissionResponse
)
def record_jira_comment(
    submission_id: str,
    body: JiraCommentReceipt,
    integration: dict[str, Any] = Depends(require_jira_integration),
):
    return JiraIntegrationService.record_comment(integration, submission_id, body)


@router.post(
    "/submissions/{submission_id}/fail", response_model=JiraSubmissionResponse
)
def fail_jira_submission(
    submission_id: str,
    body: JiraSubmissionFailure,
    integration: dict[str, Any] = Depends(require_jira_integration),
):
    return JiraIntegrationService.fail_submission(integration, submission_id, body)
