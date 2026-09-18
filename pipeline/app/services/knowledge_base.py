from __future__ import annotations

import hashlib
import json
from typing import Any

from tierx_kb import (
    RETRIEVAL_VERSION,
    build_alert_query,
    mongo_candidate_filter,
    rank_chunks,
)

from app.core.config import settings
from tierx_kb.hybrid import HYBRID_VERSION, merge_results, search_semantic_async


class KnowledgeBaseRetriever:
    DOCUMENTS = "kb_documents"
    CHUNKS = "kb_chunks"

    @staticmethod
    def _checksum(value: Any) -> str:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    async def search_alert(
        self,
        db: Any,
        *,
        alert_type: str,
        normalized_payload: dict[str, Any],
        top_k: int,
        tenant_id: str = "",
        retrieval_mode: str = "deterministic",
    ) -> dict[str, Any]:
        query = build_alert_query(alert_type, normalized_payload)
        safe_query = {
            "field_count": len(query.get("field_values") or []),
            "term_count": len(query.get("terms") or []),
            "ip_count": len(query.get("ips") or []),
            "synonym_source_terms": sorted((query.get("synonyms") or {}).keys()),
        }
        query_sha = self._checksum(query)
        documents = (
            await db[self.DOCUMENTS]
            .find(
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
            .to_list(length=None)
        )
        if not documents:
            return {
                "status": "KB_NOT_AVAILABLE",
                "retrieval_version": HYBRID_VERSION if retrieval_mode == "hybrid" else RETRIEVAL_VERSION,
                "query_sha256": query_sha,
                "query_summary": safe_query,
                "matches": [],
                "retrieval_mode": retrieval_mode,
                "semantic_status": "NOT_INDEXED" if retrieval_mode == "hybrid" else "NOT_REQUESTED",
            }
        by_id = {str(item["document_id"]): item for item in documents}
        clauses = [
            {
                "document_id": item["document_id"],
                "index_generation": item["active_index_generation"],
            }
            for item in documents
        ]
        chunks = (
            await db[self.CHUNKS]
            .find(
                {
                    "$and": [
                        {"$or": clauses},
                        mongo_candidate_filter(query),
                    ]
                },
                {"_id": 0},
            )
            .sort([("document_id", 1), ("chunk_index", 1)])
            .to_list(length=settings.knowledge_base_max_candidates)
        )
        ranked = rank_chunks(chunks, query, top_k=len(chunks) if retrieval_mode == "hybrid" else top_k)
        semantic = {"semantic_status": "NOT_REQUESTED", "degraded": False}
        if retrieval_mode == "hybrid":
            semantic = await search_semantic_async(tenant_id, query)
            ranked = merge_results(ranked, semantic.get("items", []), top_k)
        matches = []
        for item in ranked:
            document = by_id.get(str(item["document_id"]), {})
            matches.append(
                {
                    "document_id": item["document_id"],
                    "document_version": int(item.get("document_version") or 1),
                    "chunk_id": item["chunk_id"],
                    "chunk_index": int(item["chunk_index"]),
                    "filename": document.get("original_filename", "unknown"),
                    "heading_path": list(item.get("heading_path") or []),
                    "text": item["text"],
                    "text_sha256": item["text_sha256"],
                    "score": float(item["score"]),
                    "matched_by": item["matched_by"],
                    **{key: item[key] for key in ("retrieval_channels", "deterministic_score",
                        "semantic_score", "fusion_score", "model", "model_digest") if key in item},
                }
            )
        return {
            "status": "OK" if matches else "NO_MATCH",
            "retrieval_version": HYBRID_VERSION if retrieval_mode == "hybrid" else RETRIEVAL_VERSION,
            "query_sha256": query_sha,
            "query_summary": safe_query,
            "matches": matches,
            "retrieval_mode": retrieval_mode,
            "semantic_status": semantic["semantic_status"],
            "degraded": semantic["degraded"],
            "semantic_metadata": {key: semantic[key] for key in ("threshold", "elapsed_ms", "model", "model_digest") if key in semantic},
        }
