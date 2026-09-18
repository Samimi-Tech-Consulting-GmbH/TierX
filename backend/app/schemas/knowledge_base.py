from datetime import datetime
from typing import Any, List, Literal

from pydantic import BaseModel, Field


class KnowledgeBaseUploader(BaseModel):
    user_id: str
    email: str


class KnowledgeBaseSemanticIndex(BaseModel):
    """Public progress only; internal ownership/fencing fields are discarded."""

    status: Literal["PENDING", "PROCESSING", "INDEXED", "FAILED", "SKIPPED"]
    generation: str | None = None
    source_generation: str | None = None
    model: str | None = None
    model_digest: str | None = None
    index_version: str | None = None
    subchunk_count: int | None = None
    completed_at: datetime | None = None
    error: str | None = None


class KnowledgeBaseDocument(BaseModel):
    document_id: str
    tenant_id: str
    original_filename: str
    file_format: Literal["md", "txt", "pdf", "docx", "xlsx"]
    content_type: str
    size_bytes: int = Field(ge=1)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    status: Literal["PENDING", "PROCESSING", "INDEXED", "FAILED"]
    processing_supported: bool = True
    document_version: int = 1
    parser_version: str | None = None
    index_version: str | None = None
    active_index_generation: str | None = None
    chunk_count: int = 0
    processing_started_at: datetime | None = None
    processing_completed_at: datetime | None = None
    processing_error: dict[str, Any] | None = None
    semantic_index: KnowledgeBaseSemanticIndex | None = None
    uploaded_by: KnowledgeBaseUploader
    uploaded_at: datetime
    updated_at: datetime


class KnowledgeBaseDocumentPage(BaseModel):
    items: List[KnowledgeBaseDocument]
    total: int
    skip: int
    limit: int


class KnowledgeBaseChunk(BaseModel):
    chunk_id: str
    document_id: str
    document_version: int
    chunk_index: int
    source_start_line: int
    source_end_line: int
    heading_path: List[str]
    text: str
    text_sha256: str
    parser_version: str
    index_version: str


class KnowledgeBaseChunkPage(BaseModel):
    items: List[KnowledgeBaseChunk]
    total: int
    skip: int
    limit: int


class KnowledgeBaseSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4096)
    top_k: int = Field(default=5, ge=1, le=20)
    retrieval_mode: Literal["deterministic", "hybrid"] = "deterministic"


class KnowledgeBaseSearchMatch(KnowledgeBaseChunk):
    filename: str
    score: float
    matched_by: List[dict[str, Any]]
    retrieval_channels: List[str] = Field(default_factory=list)
    deterministic_score: float | None = None
    semantic_score: float | None = None
    fusion_score: float | None = None
    model: str | None = None
    model_digest: str | None = None


class KnowledgeBaseSearchResponse(BaseModel):
    query_sha256: str
    retrieval_version: str
    status: Literal["OK", "KB_NOT_AVAILABLE", "NO_MATCH"]
    items: List[KnowledgeBaseSearchMatch]
    retrieval_mode: str = "deterministic"
    semantic_status: str = "NOT_REQUESTED"
    degraded: bool = False
    semantic_metadata: dict[str, Any] = Field(default_factory=dict)
