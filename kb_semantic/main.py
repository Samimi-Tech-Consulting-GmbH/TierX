"""Private retrieval API and single semantic indexing scheduler."""

import asyncio
import logging
import os
import threading
from contextlib import asynccontextmanager
from time import monotonic

from fastapi import FastAPI
from pydantic import BaseModel, Field
from pymongo import MongoClient

from engine import Engine, MODEL, MODEL_DIGEST, INDEX_VERSION
from worker import claim, cleanup, discover, now, process, validated_matches
from tierx_kb.hybrid import enabled

logger = logging.getLogger("tierx-kb-semantic")


def index_tenants(client, engine):
    for tenant in client.soc_mind_platform.tenants.find({}):
        db = client[tenant["db_name"]]
        if tenant.get("status") == "DELETED":
            cleanup(db, tenant["tenant_id"], engine, tenant_deleted=True)
            continue
        discover(db, tenant["tenant_id"])
        cleanup(db, tenant["tenant_id"], engine)
        job = claim(db)
        if job:
            process(db, job, engine)


@asynccontextmanager
async def lifespan(app):
    app.state.engine = None
    app.state.client = MongoClient(
        os.environ["MONGO_URL"], tz_aware=True, serverSelectionTimeoutMS=2000
    )
    app.state.stop = threading.Event()
    app.state.search_lock = threading.Lock()

    def run():
        while not app.state.stop.is_set():
            try:
                indexing = enabled("KB_SEMANTIC_INDEXING_ENABLED")
                retrieval = enabled("KB_SEMANTIC_RETRIEVAL_ENABLED")
                if indexing or retrieval:
                    if app.state.engine is None:
                        app.state.engine = Engine()
                    platform = app.state.client["soc_mind_platform"]
                    platform.service_heartbeats.update_one(
                        {"service": "kb-semantic"},
                        {"$set": {"seen_at": now()}},
                        upsert=True,
                    )
                    if indexing:
                        index_tenants(app.state.client, app.state.engine)
            except Exception as exc:
                # Do not log exception text: providers can include source content.
                logger.warning(
                    "Semantic scheduler unavailable error_type=%s", type(exc).__name__
                )
            app.state.stop.wait(5)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    yield
    app.state.stop.set()
    app.state.client.close()


app = FastAPI(
    title="TierX private KB semantic service",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
)


class Search(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=128)
    query: str = Field(min_length=1, max_length=4096)


@app.get("/health")
def health():
    return {
        "status": "READY" if app.state.engine else "DISABLED_OR_STARTING",
        "model": MODEL,
        "model_digest": MODEL_DIGEST,
    }


@app.post("/search")
async def search(payload: Search):
    started = monotonic()
    result = {"items": [], "semantic_status": "UNAVAILABLE", "degraded": True}
    if not enabled("KB_SEMANTIC_RETRIEVAL_ENABLED"):
        return {**result, "semantic_status": "DISABLED"}
    if not app.state.engine:
        return result

    def perform():
        if not app.state.search_lock.acquire(blocking=False):
            return {**result, "semantic_status": "BUSY"}
        try:
            tenant_id = str(payload.tenant_id)
            tenant = app.state.client.soc_mind_platform.tenants.find_one(
                {"tenant_id": tenant_id, "status": {"$ne": "DELETED"}}
            )
            if not tenant:
                return {**result, "semantic_status": "NOT_AVAILABLE"}
            db = app.state.client[tenant["db_name"]]
            if not db.kb_documents.find_one(
                {
                    "deleted_at": None,
                    "semantic_index.status": "INDEXED",
                    "semantic_index.model": MODEL,
                    "semantic_index.model_digest": MODEL_DIGEST,
                    "semantic_index.index_version": INDEX_VERSION,
                    "semantic_index.source_generation": {"$exists": True, "$ne": None},
                    "active_index_generation": {"$exists": True, "$ne": None},
                    "$expr": {
                        "$eq": [
                            "$semantic_index.source_generation",
                            "$active_index_generation",
                        ]
                    },
                }
            ):
                return {**result, "semantic_status": "NOT_INDEXED"}
            rows = app.state.engine.search(tenant_id, payload.query)
            threshold = float(os.getenv("KB_SEMANTIC_MIN_SCORE", "0.70"))
            if not 0 <= threshold <= 1:
                raise ValueError("INVALID_THRESHOLD")
            return {
                "items": validated_matches(db, rows, threshold),
                "semantic_status": "AVAILABLE",
                "degraded": False,
                "threshold": threshold,
                "model": MODEL,
                "model_digest": MODEL_DIGEST,
            }
        finally:
            app.state.search_lock.release()

    try:
        async with asyncio.timeout(4):
            result = await asyncio.to_thread(perform)
    except Exception:
        pass
    return {**result, "elapsed_ms": round((monotonic() - started) * 1000, 2)}
