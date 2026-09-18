from __future__ import annotations

import codecs
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath
from typing import Any, AsyncIterator
from urllib.parse import quote
from uuid import uuid4

import gridfs
from tierx_kb.hybrid import HYBRID_VERSION, merge_results, search_semantic
from pymongo import ASCENDING, DESCENDING, ReturnDocument
from tierx_kb import (
    INDEX_VERSION,
    PARSER_VERSION,
    RETRIEVAL_VERSION,
    build_text_query,
    mongo_candidate_filter,
    parse_document,
    rank_chunks,
)

from app.core.errors import ResourceNotFoundError
from app.db.mongodb import DatabaseManager
from app.models.tenant import Tenant
from app.schemas.knowledge_base import (
    KnowledgeBaseChunk,
    KnowledgeBaseChunkPage,
    KnowledgeBaseDocument,
    KnowledgeBaseDocumentPage,
    KnowledgeBaseSearchMatch,
    KnowledgeBaseSearchResponse,
)
from app.schemas.user import AuthenticatedUser

MAX_FILE_BYTES = 50 * 1024 * 1024
UPLOAD_CHUNK_BYTES = 1024 * 1024
DOCUMENT_COLLECTION = "kb_documents"
CHUNK_COLLECTION = "kb_chunks"
FILE_BUCKET = "kb_files"
SUPPORTED_FORMATS = {
    ".md": ("md", "text/markdown; charset=utf-8"),
    ".txt": ("txt", "text/plain; charset=utf-8"),
}


class KnowledgeBaseValidationError(ValueError):
    def __init__(self, detail: str, status_code: int = 422):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


class KnowledgeBaseService:
    @staticmethod
    def _safe_original_filename(value: str | None) -> str:
        normalized = (value or "").replace("\\", "/")
        filename = PurePosixPath(normalized).name.strip()
        filename = "".join(ch for ch in filename if ord(ch) >= 32 and ord(ch) != 127)
        if not filename:
            raise KnowledgeBaseValidationError("A filename is required")
        if len(filename.encode("utf-8")) > 255:
            raise KnowledgeBaseValidationError("Filename must be at most 255 bytes")
        return filename

    @classmethod
    def _tenant_database(cls, tenant_id: str):
        tenant = Tenant.objects(tenant_id=tenant_id).first()
        if not tenant:
            raise ResourceNotFoundError(f"Tenant with ID {tenant_id} not found")
        db = DatabaseManager.get_tenant_database(str(tenant.db_name))
        cls._ensure_database_indexes(db)
        return db

    @staticmethod
    def _ensure_database_indexes(db) -> None:
        documents = db[DOCUMENT_COLLECTION]
        documents.create_index("document_id", unique=True)
        documents.create_index(
            [("uploaded_at", DESCENDING), ("document_id", DESCENDING)]
        )
        documents.create_index(
            [("status", ASCENDING), ("uploaded_at", DESCENDING)],
            name="status_uploaded_at",
        )
        chunks = db[CHUNK_COLLECTION]
        chunks.create_index(
            [("chunk_id", ASCENDING), ("index_generation", ASCENDING)], unique=True
        )
        chunks.create_index(
            [
                ("document_id", ASCENDING),
                ("index_generation", ASCENDING),
                ("chunk_index", ASCENDING),
            ],
            unique=True,
            name="document_generation_chunk",
        )
        chunks.create_index("normalized_terms")

    @classmethod
    def ensure_indexes(cls) -> None:
        for tenant in Tenant.objects(status__ne="DELETED").only("db_name"):
            cls._ensure_database_indexes(
                DatabaseManager.get_tenant_database(str(tenant.db_name))
            )

    @staticmethod
    def _public_document(raw: dict[str, Any]) -> KnowledgeBaseDocument:
        value = dict(raw)
        value.setdefault(
            "processing_supported", value.get("file_format") in {"md", "txt"}
        )
        value.setdefault("document_version", 1)
        value.setdefault("chunk_count", 0)
        return KnowledgeBaseDocument(**value)

    @classmethod
    async def upload_document(
        cls, tenant_id: str, upload: Any, user: AuthenticatedUser
    ) -> KnowledgeBaseDocument:
        filename = cls._safe_original_filename(upload.filename)
        suffix = PurePosixPath(filename).suffix.lower()
        if suffix not in SUPPORTED_FORMATS:
            raise KnowledgeBaseValidationError(
                "Unsupported file type. Use .md or .txt", status_code=415
            )
        file_format, content_type = SUPPORTED_FORMATS[suffix]
        db = cls._tenant_database(tenant_id)
        fs = gridfs.GridFS(db, collection=FILE_BUCKET)
        now = datetime.now(timezone.utc)
        document_id = str(uuid4())
        grid_in = fs.new_file(
            filename=filename,
            content_type=content_type,
            metadata={"tenant_id": tenant_id, "document_id": document_id},
        )
        gridfs_id = grid_in._id
        size = 0
        checksum = hashlib.sha256()
        decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
        metadata_inserted = False
        try:
            while True:
                chunk = await upload.read(UPLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_FILE_BYTES:
                    raise KnowledgeBaseValidationError(
                        "File exceeds the 50 MiB upload limit", status_code=413
                    )
                if b"\x00" in chunk:
                    raise KnowledgeBaseValidationError(
                        "Text files must not contain NUL bytes"
                    )
                try:
                    decoder.decode(chunk, final=False)
                except UnicodeDecodeError as exc:
                    raise KnowledgeBaseValidationError(
                        "Text files must contain valid UTF-8"
                    ) from exc
                checksum.update(chunk)
                grid_in.write(chunk)
            if size == 0:
                raise KnowledgeBaseValidationError("Empty files are not allowed")
            try:
                decoder.decode(b"", final=True)
            except UnicodeDecodeError as exc:
                raise KnowledgeBaseValidationError(
                    "Text files must contain valid UTF-8"
                ) from exc
            grid_in.close()
            raw = {
                "document_id": document_id,
                "tenant_id": tenant_id,
                "original_filename": filename,
                "file_format": file_format,
                "content_type": content_type,
                "size_bytes": size,
                "sha256": checksum.hexdigest(),
                "status": "PENDING",
                "processing_supported": True,
                "document_version": 1,
                "parser_version": None,
                "index_version": None,
                "active_index_generation": None,
                "chunk_count": 0,
                "processing_started_at": None,
                "processing_completed_at": None,
                "processing_error": None,
                "processing_lease_expires_at": None,
                "gridfs_id": gridfs_id,
                "uploaded_by": {"user_id": user.user_id, "email": user.email},
                "uploaded_at": now,
                "updated_at": now,
                "deleted_at": None,
                "deleted_by": None,
            }
            db[DOCUMENT_COLLECTION].insert_one(raw)
            metadata_inserted = True
            db["onboarding_status"].update_one(
                {},
                {
                    "$set": {"kb_document_uploaded": True},
                    "$setOnInsert": {"kb_document_uploaded_at": now},
                },
                upsert=True,
            )
            return cls._public_document(raw)
        except Exception:
            if metadata_inserted:
                try:
                    db[DOCUMENT_COLLECTION].delete_one({"document_id": document_id})
                except Exception:
                    pass
            try:
                grid_in.close()
            except Exception:
                pass
            try:
                if fs.exists(gridfs_id):
                    fs.delete(gridfs_id)
            except Exception:
                pass
            raise
        finally:
            await upload.close()

    @classmethod
    def list_documents(
        cls, tenant_id: str, *, skip: int, limit: int
    ) -> KnowledgeBaseDocumentPage:
        db = cls._tenant_database(tenant_id)
        query = {"deleted_at": None}
        collection = db[DOCUMENT_COLLECTION]
        cursor = (
            collection.find(
                query,
                {
                    "gridfs_id": 0,
                    "deleted_at": 0,
                    "deleted_by": 0,
                    "processing_lease_expires_at": 0,
                },
            )
            .sort([("uploaded_at", DESCENDING), ("document_id", DESCENDING)])
            .skip(skip)
            .limit(limit)
        )
        return KnowledgeBaseDocumentPage(
            items=[cls._public_document(row) for row in cursor],
            total=collection.count_documents(query),
            skip=skip,
            limit=limit,
        )

    @classmethod
    def get_document(cls, tenant_id: str, document_id: str) -> KnowledgeBaseDocument:
        raw = cls._tenant_database(tenant_id)[DOCUMENT_COLLECTION].find_one(
            {"document_id": document_id, "deleted_at": None}
        )
        if not raw:
            raise ResourceNotFoundError(
                f"Knowledge Base document {document_id} not found"
            )
        return cls._public_document(raw)

    @classmethod
    def get_download(cls, tenant_id: str, document_id: str):
        db = cls._tenant_database(tenant_id)
        raw = db[DOCUMENT_COLLECTION].find_one(
            {"document_id": document_id, "deleted_at": None}
        )
        if not raw:
            raise ResourceNotFoundError(
                f"Knowledge Base document {document_id} not found"
            )
        try:
            stored = gridfs.GridFS(db, collection=FILE_BUCKET).get(raw["gridfs_id"])
        except (gridfs.errors.NoFile, KeyError):
            raise ResourceNotFoundError(
                f"Knowledge Base document {document_id} not found"
            )
        return raw, stored

    @staticmethod
    def download_headers(filename: str, size: int) -> dict[str, str]:
        ascii_name = (
            re.sub(r"[^A-Za-z0-9._ -]", "_", filename).strip(" .") or "document"
        )
        return {
            "Content-Disposition": f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(filename, safe="")}',
            "Content-Length": str(size),
            "X-Content-Type-Options": "nosniff",
        }

    @staticmethod
    def iter_download(stored: Any) -> AsyncIterator[bytes]:
        async def chunks():
            try:
                while True:
                    chunk = stored.read(UPLOAD_CHUNK_BYTES)
                    if not chunk:
                        break
                    yield chunk
            finally:
                stored.close()

        return chunks()

    @classmethod
    def list_chunks(
        cls, tenant_id: str, document_id: str, *, skip: int, limit: int
    ) -> KnowledgeBaseChunkPage:
        db = cls._tenant_database(tenant_id)
        document = db[DOCUMENT_COLLECTION].find_one(
            {"document_id": document_id, "deleted_at": None}
        )
        if not document:
            raise ResourceNotFoundError(
                f"Knowledge Base document {document_id} not found"
            )
        generation = document.get("active_index_generation")
        query = {"document_id": document_id, "index_generation": generation}
        collection = db[CHUNK_COLLECTION]
        total = collection.count_documents(query) if generation else 0
        rows = (
            collection.find(
                query,
                {
                    "_id": 0,
                    "normalized_text": 0,
                    "normalized_terms": 0,
                    "term_frequencies": 0,
                    "term_count": 0,
                    "indicators": 0,
                },
            )
            .sort("chunk_index", ASCENDING)
            .skip(skip)
            .limit(limit)
            if total
            else []
        )
        return KnowledgeBaseChunkPage(
            items=[KnowledgeBaseChunk(**row) for row in rows],
            total=total,
            skip=skip,
            limit=limit,
        )

    @classmethod
    def _active_chunks(
        cls, db: Any, query: dict[str, Any], maximum: int = 500
    ) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
        documents = list(
            db[DOCUMENT_COLLECTION].find(
                {
                    "deleted_at": None,
                    "processing_supported": {"$ne": False},
                    "active_index_generation": {"$ne": None},
                },
                {
                    "_id": 0,
                    "document_id": 1,
                    "document_version": 1,
                    "active_index_generation": 1,
                    "original_filename": 1,
                },
            )
        )
        by_id = {str(row["document_id"]): row for row in documents}
        clauses = [
            {
                "document_id": row["document_id"],
                "index_generation": row["active_index_generation"],
            }
            for row in documents
        ]
        if not clauses:
            return [], by_id
        selector = {
            "$and": [
                {"$or": clauses},
                mongo_candidate_filter(query),
            ]
        }
        chunks = list(
            db[CHUNK_COLLECTION]
            .find(selector, {"_id": 0})
            .sort([("document_id", ASCENDING), ("chunk_index", ASCENDING)])
            .limit(maximum)
        )
        return chunks, by_id

    @classmethod
    def search(
        cls, tenant_id: str, query_text: str, *, top_k: int, retrieval_mode: str = "deterministic"
    ) -> KnowledgeBaseSearchResponse:
        query = build_text_query(query_text)
        chunks, documents = cls._active_chunks(cls._tenant_database(tenant_id), query)
        query_sha = hashlib.sha256(
            json.dumps(query, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        if not documents:
            return KnowledgeBaseSearchResponse(
                query_sha256=query_sha,
                retrieval_version=HYBRID_VERSION if retrieval_mode == "hybrid" else RETRIEVAL_VERSION,
                status="KB_NOT_AVAILABLE",
                items=[],
                retrieval_mode=retrieval_mode,
                semantic_status="NOT_INDEXED" if retrieval_mode == "hybrid" else "NOT_REQUESTED",
            )
        ranked = rank_chunks(chunks, query, top_k=len(chunks) if retrieval_mode == "hybrid" else top_k)
        semantic = {"semantic_status": "NOT_REQUESTED", "degraded": False}
        if retrieval_mode == "hybrid":
            semantic = search_semantic(tenant_id, query)
            ranked = merge_results(ranked, semantic.get("items", []), top_k)
        items = []
        for row in ranked:
            if str(row["document_id"]) not in documents:
                continue
            document = documents[str(row["document_id"])]
            items.append(
                KnowledgeBaseSearchMatch(
                    **{
                        key: value
                        for key, value in row.items()
                        if key in KnowledgeBaseChunk.model_fields
                    },
                    filename=document["original_filename"],
                    score=row["score"],
                    matched_by=row["matched_by"],
                    **{key: row[key] for key in ("retrieval_channels", "deterministic_score",
                        "semantic_score", "fusion_score", "model", "model_digest") if key in row},
                )
            )
        return KnowledgeBaseSearchResponse(
            query_sha256=query_sha,
            retrieval_version=HYBRID_VERSION if retrieval_mode == "hybrid" else RETRIEVAL_VERSION,
            status="OK" if items else "NO_MATCH",
            items=items,
            retrieval_mode=retrieval_mode,
            semantic_status=semantic["semantic_status"],
            degraded=semantic["degraded"],
            semantic_metadata={key: semantic[key] for key in ("threshold", "elapsed_ms", "model", "model_digest") if key in semantic},
        )

    @classmethod
    def reprocess_document(
        cls, tenant_id: str, document_id: str
    ) -> KnowledgeBaseDocument:
        db = cls._tenant_database(tenant_id)
        raw = db[DOCUMENT_COLLECTION].find_one_and_update(
            {
                "document_id": document_id,
                "deleted_at": None,
                "file_format": {"$in": ["md", "txt"]},
            },
            {
                "$set": {
                    "status": "PENDING",
                    "processing_supported": True,
                    "processing_error": None,
                    "processing_started_at": None,
                    "processing_completed_at": None,
                    "processing_lease_expires_at": None,
                    "processing_lease_id": None,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        if not raw:
            raise ResourceNotFoundError(
                f"Processable Knowledge Base document {document_id} not found"
            )
        return cls._public_document(raw)

    @classmethod
    def claim_next(cls, db: Any, *, lease_seconds: int = 600) -> dict[str, Any] | None:
        now = datetime.now(timezone.utc)
        return db[DOCUMENT_COLLECTION].find_one_and_update(
            {
                "deleted_at": None,
                "file_format": {"$in": ["md", "txt"]},
                "$or": [
                    {"status": "PENDING"},
                    {
                        "status": "PROCESSING",
                        "processing_lease_expires_at": {"$lte": now},
                    },
                ],
            },
            {
                "$set": {
                    "status": "PROCESSING",
                    "processing_supported": True,
                    "processing_started_at": now,
                    "processing_lease_expires_at": now
                    + timedelta(seconds=lease_seconds),
                    "processing_lease_id": str(uuid4()),
                    "processing_error": None,
                    "updated_at": now,
                }
            },
            sort=[("uploaded_at", ASCENDING), ("document_id", ASCENDING)],
            return_document=ReturnDocument.AFTER,
        )

    @classmethod
    def process_claimed(cls, db: Any, document: dict[str, Any]) -> int:
        generation = str(uuid4())
        chunks_collection = db[CHUNK_COLLECTION]
        try:
            stored = gridfs.GridFS(db, collection=FILE_BUCKET).get(
                document["gridfs_id"]
            )
            try:
                text = stored.read().decode("utf-8")
            finally:
                stored.close()
            chunks = parse_document(
                text,
                file_format=document["file_format"],
                document_id=document["document_id"],
                document_version=int(document.get("document_version") or 1),
                document_sha256=document["sha256"],
                index_generation=generation,
            )
            if not chunks:
                raise ValueError("Document did not contain indexable text")
            chunks_collection.insert_many(chunks, ordered=True)
            now = datetime.now(timezone.utc)
            result = db[DOCUMENT_COLLECTION].update_one(
                {
                    "_id": document["_id"],
                    "deleted_at": None,
                    "status": "PROCESSING",
                    "processing_lease_id": document.get("processing_lease_id"),
                },
                {
                    "$set": {
                        "status": "INDEXED",
                        "parser_version": PARSER_VERSION,
                        "index_version": INDEX_VERSION,
                        "active_index_generation": generation,
                        "chunk_count": len(chunks),
                        "processing_completed_at": now,
                        "processing_error": None,
                        "updated_at": now,
                    },
                    "$unset": {
                        "processing_lease_expires_at": "",
                        "processing_lease_id": "",
                    },
                },
            )
            if result.modified_count != 1:
                raise RuntimeError("Document processing lease was lost")
            chunks_collection.delete_many(
                {
                    "document_id": document["document_id"],
                    "index_generation": {"$ne": generation},
                }
            )
            return len(chunks)
        except Exception as exc:
            chunks_collection.delete_many(
                {"document_id": document["document_id"], "index_generation": generation}
            )
            now = datetime.now(timezone.utc)
            db[DOCUMENT_COLLECTION].update_one(
                {
                    "_id": document["_id"],
                    "deleted_at": None,
                    "status": "PROCESSING",
                    "processing_lease_id": document.get("processing_lease_id"),
                },
                {
                    "$set": {
                        "status": "FAILED",
                        "processing_completed_at": now,
                        "processing_error": {
                            "code": type(exc).__name__,
                            "detail": "Document processing failed",
                        },
                        "updated_at": now,
                    },
                    "$unset": {
                        "processing_lease_expires_at": "",
                        "processing_lease_id": "",
                    },
                },
            )
            raise

    @classmethod
    def delete_document(
        cls, tenant_id: str, document_id: str, user: AuthenticatedUser
    ) -> None:
        db = cls._tenant_database(tenant_id)
        collection = db[DOCUMENT_COLLECTION]
        now = datetime.now(timezone.utc)
        raw = collection.find_one_and_update(
            {"document_id": document_id, "deleted_at": None},
            {
                "$set": {
                    "deleted_at": now,
                    "deleted_by": {"user_id": user.user_id, "email": user.email},
                    "updated_at": now,
                }
            },
            return_document=ReturnDocument.BEFORE,
        )
        if not raw:
            raise ResourceNotFoundError(
                f"Knowledge Base document {document_id} not found"
            )
        try:
            gridfs.GridFS(db, collection=FILE_BUCKET).delete(raw["gridfs_id"])
            db[CHUNK_COLLECTION].delete_many({"document_id": document_id})
        except Exception:
            collection.update_one(
                {"document_id": document_id, "deleted_at": now},
                {
                    "$set": {
                        "deleted_at": None,
                        "deleted_by": None,
                        "updated_at": raw.get("updated_at", now),
                    }
                },
            )
            raise
