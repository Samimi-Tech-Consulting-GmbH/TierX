from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse

from app.api.dependencies.auth import (
    get_current_user,
    require_tenant_admin,
    verify_tenant_access,
)
from app.schemas.knowledge_base import (
    KnowledgeBaseChunkPage,
    KnowledgeBaseDocument,
    KnowledgeBaseDocumentPage,
    KnowledgeBaseSearchRequest,
    KnowledgeBaseSearchResponse,
)
from app.schemas.user import AuthenticatedUser
from app.services.knowledge_base_service import (
    KnowledgeBaseService,
    KnowledgeBaseValidationError,
)

router = APIRouter(
    prefix="/tenants/{tenant_id}/knowledge-base",
    tags=["Knowledge Base"],
)


@router.post(
    "/documents",
    status_code=status.HTTP_201_CREATED,
    response_model=KnowledgeBaseDocument,
)
async def upload_document(
    file: UploadFile = File(...),
    tenant_id: str = Depends(verify_tenant_access),
    user: AuthenticatedUser = Depends(require_tenant_admin),
) -> Any:
    try:
        return await KnowledgeBaseService.upload_document(tenant_id, file, user)
    except KnowledgeBaseValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get("/documents", response_model=KnowledgeBaseDocumentPage)
def list_documents(
    skip: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=200),
    tenant_id: str = Depends(verify_tenant_access),
    _: AuthenticatedUser = Depends(get_current_user),
) -> Any:
    return KnowledgeBaseService.list_documents(tenant_id, skip=skip, limit=limit)


@router.get("/documents/{document_id}", response_model=KnowledgeBaseDocument)
def get_document(
    document_id: str,
    tenant_id: str = Depends(verify_tenant_access),
    _: AuthenticatedUser = Depends(get_current_user),
) -> Any:
    return KnowledgeBaseService.get_document(tenant_id, document_id)


@router.get("/documents/{document_id}/chunks", response_model=KnowledgeBaseChunkPage)
def list_chunks(
    document_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=200),
    tenant_id: str = Depends(verify_tenant_access),
    _: AuthenticatedUser = Depends(get_current_user),
) -> Any:
    return KnowledgeBaseService.list_chunks(
        tenant_id, document_id, skip=skip, limit=limit
    )


@router.post("/documents/{document_id}/reprocess", response_model=KnowledgeBaseDocument)
def reprocess_document(
    document_id: str,
    tenant_id: str = Depends(verify_tenant_access),
    _: AuthenticatedUser = Depends(require_tenant_admin),
) -> Any:
    return KnowledgeBaseService.reprocess_document(tenant_id, document_id)


@router.post("/search", response_model=KnowledgeBaseSearchResponse)
def search_documents(
    payload: KnowledgeBaseSearchRequest,
    tenant_id: str = Depends(verify_tenant_access),
    _: AuthenticatedUser = Depends(get_current_user),
) -> Any:
    return KnowledgeBaseService.search(tenant_id, payload.query, top_k=payload.top_k,
                                      retrieval_mode=payload.retrieval_mode)


@router.get("/documents/{document_id}/download")
def download_document(
    document_id: str,
    tenant_id: str = Depends(verify_tenant_access),
    _: AuthenticatedUser = Depends(get_current_user),
) -> StreamingResponse:
    metadata, stored = KnowledgeBaseService.get_download(tenant_id, document_id)
    return StreamingResponse(
        KnowledgeBaseService.iter_download(stored),
        media_type=metadata["content_type"],
        headers=KnowledgeBaseService.download_headers(
            metadata["original_filename"], metadata["size_bytes"]
        ),
    )


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: str,
    tenant_id: str = Depends(verify_tenant_access),
    user: AuthenticatedUser = Depends(require_tenant_admin),
) -> None:
    KnowledgeBaseService.delete_document(tenant_id, document_id, user)
