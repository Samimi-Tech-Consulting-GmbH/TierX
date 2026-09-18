"""Shared hybrid ranking; security matches are never inferred by a model."""

from __future__ import annotations

import os
import math
from typing import Any

import httpx

HYBRID_VERSION = "kb-hybrid-v1"


def setting(name: str, default: str = "") -> str:
    return os.getenv(f"TIERX_{name}", os.getenv(name, default))


def enabled(name: str) -> bool:
    return setting(name, "false").strip().lower() in {"1", "true", "yes", "on"}


def semantic_enabled() -> bool:
    return enabled("KB_SEMANTIC_RETRIEVAL_ENABLED")


def semantic_query(query: dict[str, Any]) -> str:
    # Input must be produced by build_alert_query/build_text_query, never raw alerts.
    return "\n".join(
        f"{row['field']}: {row['value']}" for row in query.get("field_values", [])
    )[:4096]


def merge_results(
    deterministic: list[dict], semantic: list[dict], top_k: int
) -> list[dict]:
    def identity(row):
        return (
            str(row["document_id"]),
            int(row.get("document_version", 1)),
            str(row["chunk_id"]),
        )

    rows: dict[tuple, dict] = {}
    for channel, candidates in (
        ("deterministic", deterministic),
        ("semantic", semantic),
    ):
        seen = set()
        for rank, item in enumerate(candidates, 1):
            key = identity(item)
            if key in seen:
                continue
            seen.add(key)
            row = rows.setdefault(
                key,
                {
                    **item,
                    "matched_by": list(item.get("matched_by", [])),
                    "retrieval_channels": [],
                    "fusion_score": 0.0,
                },
            )
            row["retrieval_channels"].append(channel)
            row["fusion_score"] += 1.0 / (60 + rank)
            row[f"{channel}_score"] = float(
                item.get(f"{channel}_score", item.get("score", 0))
            )
            if channel == "semantic":
                row["model"] = item.get("model")
                row["model_digest"] = item.get("model_digest")
                row["matched_by"].append(
                    {"method": "SEMANTIC", "score": row["semantic_score"]}
                )
                # Keep score backwards compatible: deterministic score, never cosine + lexical.
                row.setdefault("deterministic_score", 0.0)
                row["score"] = row["deterministic_score"]

    def order(row):
        exact = any(
            r.get("method") in {"CIDR_CONTAINS", "EXACT_ENTITY"}
            for r in row["matched_by"]
        )
        return (
            0 if exact else 1,
            -row.get("deterministic_score", 0) if exact else -row["fusion_score"],
            *identity(row),
        )

    return sorted(rows.values(), key=order)[:top_k]


def search_semantic(tenant_id: str, query: dict) -> dict:
    import asyncio

    # Sync backend routes run in FastAPI's worker pool. Use the same outer deadline.
    return asyncio.run(search_semantic_async(tenant_id, query))


async def search_semantic_async(tenant_id: str, query: dict) -> dict:
    import asyncio

    if not semantic_enabled():
        return {"items": [], "semantic_status": "DISABLED", "degraded": True}
    try:
        async with asyncio.timeout(5):
            async with httpx.AsyncClient(timeout=4.5, trust_env=False) as client:
                response = await client.post(
                    setting("KB_SEMANTIC_URL", "http://kb-semantic:8010") + "/search",
                    json={"tenant_id": tenant_id, "query": semantic_query(query)},
                )
                response.raise_for_status()
                if len(response.content) > 1024 * 1024:
                    raise ValueError("SEMANTIC_RESPONSE_TOO_LARGE")
                result = response.json()
                if (
                    not isinstance(result, dict)
                    or not isinstance(result.get("items"), list)
                    or len(result["items"]) > 50
                ):
                    raise ValueError("INVALID_SEMANTIC_RESPONSE")
                if not isinstance(result.get("semantic_status"), str) or not isinstance(
                    result.get("degraded"), bool
                ):
                    raise ValueError("INVALID_SEMANTIC_RESPONSE")
                for row in result["items"]:
                    if not isinstance(row, dict) or any(
                        not isinstance(row.get(key), str)
                        for key in (
                            "document_id",
                            "chunk_id",
                            "text",
                            "text_sha256",
                            "filename",
                            "parser_version",
                            "index_version",
                        )
                    ):
                        raise ValueError("INVALID_SEMANTIC_MATCH")
                    if any(
                        not isinstance(row.get(key), int)
                        for key in (
                            "document_version",
                            "chunk_index",
                            "source_start_line",
                            "source_end_line",
                        )
                    ):
                        raise ValueError("INVALID_SEMANTIC_MATCH")
                    if not isinstance(row.get("heading_path"), list) or not all(
                        isinstance(value, str) for value in row["heading_path"]
                    ):
                        raise ValueError("INVALID_SEMANTIC_MATCH")
                    if not isinstance(row.get("matched_by"), list) or not all(
                        isinstance(reason, dict)
                        and isinstance(reason.get("method"), str)
                        for reason in row["matched_by"]
                    ):
                        raise ValueError("INVALID_SEMANTIC_MATCH")
                    score = float(row["semantic_score"])
                    if (
                        not math.isfinite(score)
                        or not 0 <= score <= 1
                        or len(row["text"].encode()) > 12800
                    ):
                        raise ValueError("INVALID_SEMANTIC_MATCH")
                return result
    except Exception:
        return {"items": [], "semantic_status": "UNAVAILABLE", "degraded": True}
