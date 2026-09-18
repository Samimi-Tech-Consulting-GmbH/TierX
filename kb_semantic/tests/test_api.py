import asyncio
import threading
from types import SimpleNamespace

import mongomock
import pytest
from fastapi.testclient import TestClient

import main
from engine import INDEX_VERSION, MODEL, MODEL_DIGEST
from worker import claim, discover, process
from test_semantic import FakeEngine


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("TIERX_KB_SEMANTIC_RETRIEVAL_ENABLED", "true")
    client = mongomock.MongoClient(tz_aware=True)
    client.soc_mind_platform.tenants.insert_one(
        {
            "tenant_id": "tenant-1",
            "status": "ACTIVE",
            "db_name": "tenant_db",
        }
    )
    client.tenant_db.kb_documents.insert_one(
        {
            "document_id": "doc",
            "deleted_at": None,
            "active_index_generation": "g1",
            "semantic_index": {
                "status": "INDEXED",
                "source_generation": "g1",
                "model": MODEL,
                "model_digest": MODEL_DIGEST,
                "index_version": INDEX_VERSION,
            },
        }
    )
    monkeypatch.setattr(main.app.state, "client", client, raising=False)
    monkeypatch.setattr(
        main.app.state, "engine", SimpleNamespace(search=lambda *_: []), raising=False
    )
    monkeypatch.setattr(main.app.state, "search_lock", threading.Lock(), raising=False)
    # No context manager: lifespan's real background thread/network is not started.
    return TestClient(main.app), client


def search(api):
    return api[0].post("/search", json={"tenant_id": "tenant-1", "query": "network"})


@pytest.mark.parametrize("value", ["1", "true", "yes", "on", " TRUE "])
def test_shared_truthy_flags(api, monkeypatch, value):
    from tierx_kb.hybrid import semantic_enabled

    monkeypatch.setenv("TIERX_KB_SEMANTIC_RETRIEVAL_ENABLED", value)
    assert main.enabled("KB_SEMANTIC_RETRIEVAL_ENABLED") and semantic_enabled()
    assert search(api).json()["semantic_status"] == "AVAILABLE"


def test_disabled_and_missing_engine(api, monkeypatch):
    monkeypatch.setenv("TIERX_KB_SEMANTIC_RETRIEVAL_ENABLED", "false")
    assert search(api).json()["semantic_status"] == "DISABLED"
    monkeypatch.setenv("TIERX_KB_SEMANTIC_RETRIEVAL_ENABLED", "true")
    main.app.state.engine = None
    assert search(api).json()["semantic_status"] == "UNAVAILABLE"


def test_deleted_unknown_and_other_tenant(api):
    for tenant in ("missing", "tenant-2"):
        assert (
            api[0]
            .post("/search", json={"tenant_id": tenant, "query": "x"})
            .json()["semantic_status"]
            == "NOT_AVAILABLE"
        )
    api[1].soc_mind_platform.tenants.update_one({}, {"$set": {"status": "DELETED"}})
    assert search(api).json()["semantic_status"] == "NOT_AVAILABLE"


@pytest.mark.parametrize(
    "field,value",
    [
        ("active_index_generation", "g2"),
        ("semantic_index.model_digest", "old"),
        ("semantic_index.index_version", "old"),
        ("semantic_index.status", "PENDING"),
        ("deleted_at", "deleted"),
        ("semantic_index.source_generation", None),
    ],
)
def test_stale_indexes_report_not_indexed(api, field, value):
    api[1].tenant_db.kb_documents.update_one({}, {"$set": {field: value}})
    result = search(api).json()
    assert result["semantic_status"] == "NOT_INDEXED" and result["degraded"]


def test_busy_and_provider_failure(api):
    main.app.state.search_lock.acquire()
    assert search(api).json()["semantic_status"] == "BUSY"
    main.app.state.search_lock.release()

    def fail(*_):
        raise RuntimeError("private provider detail")

    main.app.state.engine.search = fail
    result = search(api).json()
    assert result["semantic_status"] == "UNAVAILABLE"
    assert "private provider detail" not in str(result)


def test_timeout_falls_back(api, monkeypatch):
    async def timeout(*args):
        raise TimeoutError("private detail")

    monkeypatch.setattr(asyncio, "to_thread", timeout)
    assert search(api).json()["semantic_status"] == "UNAVAILABLE"


@pytest.mark.parametrize(
    "threshold,status",
    [("0.8", "AVAILABLE"), ("2", "UNAVAILABLE"), ("nan", "UNAVAILABLE")],
)
def test_threshold_validation(api, monkeypatch, threshold, status):
    monkeypatch.setenv("KB_SEMANTIC_MIN_SCORE", threshold)
    result = search(api).json()
    assert result["semantic_status"] == status
    if status == "AVAILABLE":
        assert result["threshold"] == 0.8


def test_deleted_tenant_is_purged_without_new_scheduling(api):
    db, engine = api[1].tenant_db, FakeEngine()
    discover(db, "tenant-1")
    process(db, claim(db), engine)
    api[1].soc_mind_platform.tenants.update_one({}, {"$set": {"status": "DELETED"}})
    main.index_tenants(api[1], engine)
    main.index_tenants(api[1], engine)
    assert len(engine.deleted) == 1
    assert db.kb_semantic_jobs.find_one()["state"] == "DELETED"
    assert db.kb_documents.find_one()["semantic_index"]["status"] == "SKIPPED"
