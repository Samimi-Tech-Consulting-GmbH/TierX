"""Durable per-generation jobs; a single scheduler owns embedding writes."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from pymongo import ReturnDocument

from engine import INDEX_VERSION, MODEL, MODEL_DIGEST, MODEL_ID, checksum, subchunks


def now():
    return datetime.now(timezone.utc)


def indexed_document(db, job):
    return db.kb_documents.find_one(
        {
            "document_id": job["document_id"],
            "deleted_at": None,
            "active_index_generation": job["generation"],
            "semantic_index.generation": job["job_id"],
            "semantic_index.status": "INDEXED",
        }
    )


def reconcile_completed(db, job):
    # The document is the commit record. A crash may precede the job acknowledgement.
    if not indexed_document(db, job):
        return False
    db.kb_semantic_jobs.update_one(
        {
            "job_id": job["job_id"],
            "state": job["state"],
            "lease_token": job.get("lease_token"),
        },
        {"$set": {"state": "SUCCEEDED", "completed_at": now()}},
    )
    return True


def discover(db, tenant_id):
    jobs = db.kb_semantic_jobs
    jobs.create_index("job_id", unique=True)
    jobs.create_index([("state", 1), ("lease_until", 1)])
    db.kb_semantic_mappings.create_index("generation")
    for doc in db.kb_documents.find(
        {
            "deleted_at": None,
            "processing_supported": {"$ne": False},
            "active_index_generation": {"$ne": None},
        }
    ):
        generation = doc["active_index_generation"]
        job_id = checksum([tenant_id, doc["document_id"], generation, MODEL_ID])
        jobs.update_one(
            {"job_id": job_id},
            {
                "$setOnInsert": {
                    "job_id": job_id,
                    "document_id": doc["document_id"],
                    "tenant_id": tenant_id,
                    "generation": generation,
                    "model_id": MODEL_ID,
                    "state": "PENDING",
                    "attempts": 0,
                    "created_at": now(),
                }
            },
            upsert=True,
        )
        if (doc.get("semantic_index") or {}).get("generation") != job_id:
            db.kb_documents.update_one(
                {"_id": doc["_id"], "active_index_generation": generation},
                {
                    "$set": {
                        "semantic_index": {
                            "status": "PENDING",
                            "generation": job_id,
                            "model": MODEL,
                            "model_digest": MODEL_DIGEST,
                            "index_version": INDEX_VERSION,
                        }
                    }
                },
            )


def claim(db):
    # Repair the document-commit/job-ack crash window before reclaiming a lease.
    for job in db.kb_semantic_jobs.find(
        {
            "$or": [
                {"state": "RUNNING", "lease_until": {"$lt": now()}},
                {"state": "FAILED"},
            ],
        }
    ):
        reconcile_completed(db, job)
    exhausted = {
        "attempts": {"$gte": 3},
        "state": "RUNNING",
        "lease_until": {"$lt": now()},
    }
    for job in db.kb_semantic_jobs.find(exhausted):
        changed = db.kb_semantic_jobs.update_one(
            {**exhausted, "job_id": job["job_id"], "lease_token": job["lease_token"]},
            {"$set": {"state": "FAILED", "error": "LEASE_EXHAUSTED"}},
        )
        if not changed.matched_count:
            continue
        db.kb_documents.update_one(
            {
                "document_id": job["document_id"],
                "semantic_index.generation": job["job_id"],
                "semantic_index.lease_token": job["lease_token"],
                "semantic_index.status": "PROCESSING",
            },
            {
                "$set": {
                    "semantic_index.status": "FAILED",
                    "semantic_index.error": "LEASE_EXHAUSTED",
                }
            },
        )
    token = str(uuid4())
    lease_until = now() + timedelta(seconds=600)
    job = db.kb_semantic_jobs.find_one_and_update(
        {
            "model_id": MODEL_ID,
            "attempts": {"$lt": 3},
            "$or": [
                {"state": "PENDING"},
                {"state": "RUNNING", "lease_until": {"$lt": now()}},
                {"state": "RETRY", "retry_at": {"$lte": now()}},
            ],
        },
        {
            "$set": {
                "state": "RUNNING",
                "lease_token": token,
                "lease_until": lease_until,
            },
            "$inc": {"attempts": 1},
        },
        sort=[("created_at", 1)],
        return_document=ReturnDocument.AFTER,
    )
    if not job:
        return None
    # Fencing lives on the document as well as the job: cross-collection reads
    # cannot authorize a later write. Attempts increase monotonically per job.
    attached = db.kb_documents.update_one(
        {
            "document_id": job["document_id"],
            "deleted_at": None,
            "active_index_generation": job["generation"],
            "semantic_index.generation": job["job_id"],
            "semantic_index.status": {"$ne": "INDEXED"},
            "$or": [
                {"semantic_index.lease_attempt": {"$exists": False}},
                {"semantic_index.lease_attempt": {"$lt": job["attempts"]}},
            ],
        },
        {
            "$set": {
                "semantic_index.status": "PROCESSING",
                "semantic_index.lease_token": token,
                "semantic_index.lease_attempt": job["attempts"],
                "semantic_index.lease_until": lease_until,
            }
        },
    )
    if not attached.matched_count:
        if not reconcile_completed(db, job):
            db.kb_semantic_jobs.update_one(
                {"job_id": job["job_id"], "lease_token": token, "state": "RUNNING"},
                {"$set": {"state": "FAILED", "error": "STALE_GENERATION"}},
            )
        return None
    return job


def process(db, job, engine):
    identity = {
        "job_id": job["job_id"],
        "lease_token": job["lease_token"],
        "state": "RUNNING",
    }
    document_selector = {
        "document_id": job["document_id"],
        "deleted_at": None,
        "active_index_generation": job["generation"],
        "semantic_index.generation": job["job_id"],
        "semantic_index.lease_token": job["lease_token"],
        "semantic_index.status": "PROCESSING",
    }
    try:
        count = 0
        for chunk in db.kb_chunks.find(
            {"document_id": job["document_id"], "index_generation": job["generation"]}
        ).sort("chunk_index", 1):
            for start, end, text in subchunks(chunk["text"], engine.tokenizer):
                lease_until = now() + timedelta(seconds=600)
                renewed = db.kb_semantic_jobs.update_one(
                    {**identity, "lease_until": {"$gt": now()}},
                    {
                        "$set": {
                            "lease_until": lease_until,
                            "heartbeat_at": now(),
                        }
                    },
                )
                if not renewed.matched_count:
                    raise ValueError("LEASE_LOST")
                fenced = db.kb_documents.update_one(
                    {**document_selector, "semantic_index.lease_until": {"$gt": now()}},
                    {"$set": {"semantic_index.lease_until": lease_until}},
                )
                if not fenced.matched_count:
                    raise ValueError("STALE_GENERATION")
                source_key = checksum(
                    [job["tenant_id"], job["job_id"], chunk["chunk_id"], start, end]
                )
                memory_id = engine.ensure(
                    job["tenant_id"],
                    text,
                    {
                        "source_key": source_key,
                        "semantic_generation": job["job_id"],
                        "document_id": job["document_id"],
                        "index_generation": job["generation"],
                        "chunk_id": chunk["chunk_id"],
                        "text_sha256": chunk["text_sha256"],
                        "start_offset": start,
                        "end_offset": end,
                        "model_id": MODEL_ID,
                    },
                )
                db.kb_semantic_mappings.update_one(
                    {"_id": source_key},
                    {
                        "$set": {
                            "memory_id": memory_id,
                            "generation": job["job_id"],
                            "chunk_id": chunk["chunk_id"],
                            "start_offset": start,
                            "end_offset": end,
                        }
                    },
                    upsert=True,
                )
                count += 1
        if not db.kb_semantic_jobs.find_one(identity):
            raise ValueError("LEASE_LOST")
        result = db.kb_documents.update_one(
            {**document_selector, "semantic_index.lease_until": {"$gt": now()}},
            {
                "$set": {
                    "semantic_index": {
                        "status": "INDEXED",
                        "generation": job["job_id"],
                        "source_generation": job["generation"],
                        "model": MODEL,
                        "model_digest": MODEL_DIGEST,
                        "index_version": INDEX_VERSION,
                        "subchunk_count": count,
                        "completed_at": now(),
                    }
                }
            },
        )
        if not result.matched_count:
            raise ValueError("STALE_GENERATION")
        db.kb_semantic_jobs.update_one(
            identity, {"$set": {"state": "SUCCEEDED", "completed_at": now()}}
        )
    except Exception as exc:
        exhausted = job["attempts"] >= 3
        changed = db.kb_semantic_jobs.update_one(
            {**identity, "lease_until": {"$gt": now()}},
            {
                "$set": {
                    "state": "FAILED" if exhausted else "RETRY",
                    "error": type(exc).__name__,
                    "retry_at": now() + timedelta(seconds=30 * job["attempts"]),
                }
            },
        )
        if not changed.matched_count:
            return
        db.kb_documents.update_one(
            {**document_selector, "semantic_index.lease_until": {"$gt": now()}},
            {
                "$set": {
                    "semantic_index.status": "FAILED" if exhausted else "PENDING",
                    "semantic_index.error": "SEMANTIC_INDEX_FAILED",
                }
            },
        )


def cleanup(db, tenant_id, engine, *, tenant_deleted=False):
    if tenant_deleted:
        # Fence any in-flight activation before purging this tenant's derived data.
        db.kb_documents.update_many(
            {"semantic_index": {"$exists": True}},
            {
                "$set": {
                    "semantic_index.status": "SKIPPED",
                    "semantic_index.error": "TENANT_DELETED",
                }
            },
        )
    # Jobs are durable tombstones, including writes made just before a process crash.
    for job in db.kb_semantic_jobs.find({"state": {"$ne": "DELETED"}}):
        if (
            not tenant_deleted
            and job["state"] == "FAILED"
            and not job.get("cleanup_completed")
        ):
            if reconcile_completed(db, job):
                continue
            engine.delete_generation(tenant_id, job["job_id"])
            db.kb_semantic_mappings.delete_many({"generation": job["job_id"]})
            db.kb_semantic_jobs.update_one(
                {"job_id": job["job_id"]}, {"$set": {"cleanup_completed": True}}
            )
        doc = db.kb_documents.find_one(
            {"document_id": job["document_id"], "deleted_at": None}
        )
        stale = (
            tenant_deleted
            or not doc
            or (
                (
                    doc.get("active_index_generation") != job["generation"]
                    or job.get("model_id") != MODEL_ID
                )
                and (doc.get("semantic_index") or {}).get("status") == "INDEXED"
            )
        )
        if stale:
            engine.delete_generation(tenant_id, job["job_id"])
            db.kb_semantic_mappings.delete_many({"generation": job["job_id"]})
            db.kb_semantic_jobs.update_one(
                {"job_id": job["job_id"]}, {"$set": {"state": "DELETED"}}
            )


def validated_matches(db, rows, threshold):
    matches = {}
    for row in rows[:50]:
        if float(row.get("score", 0)) < threshold:
            continue
        meta = row.get("metadata") or {}
        if meta.get("model_id") != MODEL_ID:
            continue
        doc = db.kb_documents.find_one(
            {
                "document_id": meta.get("document_id"),
                "deleted_at": None,
                "active_index_generation": meta.get("index_generation"),
                "semantic_index.status": "INDEXED",
                "semantic_index.generation": meta.get("semantic_generation"),
            }
        )
        if not doc:
            continue
        chunk = db.kb_chunks.find_one(
            {
                "document_id": doc["document_id"],
                "chunk_id": meta.get("chunk_id"),
                "index_generation": doc["active_index_generation"],
                "text_sha256": meta.get("text_sha256"),
            },
            {"_id": 0},
        )
        if not chunk:
            continue
        key = (chunk["document_id"], chunk["chunk_id"])
        item = {
            **chunk,
            "filename": doc["original_filename"],
            "score": 0,
            "semantic_score": float(row["score"]),
            "matched_by": [],
            "model": MODEL,
            "model_digest": MODEL_DIGEST,
        }
        if (
            key not in matches
            or item["semantic_score"] > matches[key]["semantic_score"]
        ):
            matches[key] = item
    return sorted(
        matches.values(),
        key=lambda m: (-m["semantic_score"], m["document_id"], m["chunk_id"]),
    )
