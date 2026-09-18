from types import SimpleNamespace

import mongomock
import pytest

from engine import MODEL_ID, subchunks
from worker import claim, cleanup, discover, process, validated_matches
from tierx_kb.hybrid import merge_results, semantic_query


class Tokenizer:
    def no_truncation(self):
        pass

    def encode(self, text):
        return SimpleNamespace(ids=list(text))


class FakeEngine:
    tokenizer = Tokenizer()

    def __init__(self):
        self.records = {}
        self.deleted = []

    def ensure(self, tenant_id, text, metadata):
        self.records.setdefault(metadata["source_key"], (tenant_id, text, metadata))
        return metadata["source_key"]

    def delete_generation(self, tenant_id, generation):
        self.deleted.append((tenant_id, generation))


def fixture_db():
    db = mongomock.MongoClient().tenant
    db.kb_documents.insert_one(
        {
            "document_id": "doc",
            "document_version": 1,
            "original_filename": "network.md",
            "active_index_generation": "g1",
            "deleted_at": None,
        }
    )
    db.kb_chunks.insert_one(
        {
            "document_id": "doc",
            "document_version": 1,
            "chunk_id": "chunk",
            "chunk_index": 0,
            "index_generation": "g1",
            "text": "10.0.0.0/8 Netzwerk",
            "text_sha256": "checksum",
        }
    )
    return db


def test_subchunks_preserve_every_character_and_offsets():
    text = "über\nNetzwerk — " * 100
    parts = list(subchunks(text, Tokenizer(), 31))
    assert "".join(part[2] for part in parts) == text
    assert all(
        text[start:end] == value and len(value) <= 31 for start, end, value in parts
    )
    assert list(subchunks("", Tokenizer())) == []


def test_exact_matches_outrank_semantics_and_scores_are_separate():
    base = {"document_id": "doc", "document_version": 1}
    det = [
        {
            **base,
            "chunk_id": "cidr",
            "score": 120,
            "matched_by": [{"method": "CIDR_CONTAINS"}],
        },
        {**base, "chunk_id": "lexical", "score": 25, "matched_by": []},
    ]
    sem = [
        {**base, "chunk_id": "semantic", "semantic_score": 0.99},
        {**base, "chunk_id": "lexical", "semantic_score": 0.8},
    ]
    result = merge_results(det, sem, 3)
    assert [r["chunk_id"] for r in result] == ["cidr", "lexical", "semantic"]
    assert result[1]["score"] == 25
    assert result[1]["semantic_score"] == 0.8
    assert result[1]["retrieval_channels"] == ["deterministic", "semantic"]


def test_query_uses_only_explicit_allowlisted_values():
    assert (
        semantic_query(
            {
                "raw_payload": "secret",
                "field_values": [{"field": "host", "value": "EXAMPLE-DB01"}],
            }
        )
        == "host: EXAMPLE-DB01"
    )


def test_job_replay_is_idempotent_and_generation_activates():
    db, engine = fixture_db(), FakeEngine()
    discover(db, "tenant-a")
    discover(db, "tenant-a")
    assert db.kb_semantic_jobs.count_documents({}) == 1
    job = claim(db)
    assert claim(db) is None
    process(db, job, engine)
    doc = db.kb_documents.find_one()
    assert doc["semantic_index"]["status"] == "INDEXED"
    assert doc["semantic_index"]["generation"] == job["job_id"]
    assert db.kb_semantic_jobs.find_one()["state"] == "SUCCEEDED"
    assert len(engine.records) == 1


@pytest.mark.parametrize("mutation", ["deleted", "generation", "checksum", "model"])
def test_stale_and_deleted_semantic_hits_are_rejected(mutation):
    db = fixture_db()
    db.kb_documents.update_one(
        {}, {"$set": {"semantic_index": {"status": "INDEXED", "generation": "s1"}}}
    )
    row = {
        "score": 0.9,
        "metadata": {
            "document_id": "doc",
            "chunk_id": "chunk",
            "index_generation": "g1",
            "semantic_generation": "s1",
            "text_sha256": "checksum",
            "model_id": MODEL_ID,
        },
    }
    assert len(validated_matches(db, [row], 0.7)) == 1
    if mutation == "deleted":
        db.kb_documents.update_one({}, {"$set": {"deleted_at": "now"}})
    elif mutation == "generation":
        row["metadata"]["index_generation"] = "old"
    elif mutation == "checksum":
        row["metadata"]["text_sha256"] = "wrong"
    else:
        row["metadata"]["model_id"] = "old"
    assert validated_matches(db, [row], 0.7) == []


def test_other_tenant_database_cannot_resolve_hits():
    assert (
        validated_matches(
            mongomock.MongoClient().other,
            [{"score": 1, "metadata": {"model_id": MODEL_ID}}],
            0.7,
        )
        == []
    )


def test_failed_index_is_not_activated():
    db = fixture_db()
    discover(db, "tenant")
    engine = FakeEngine()
    engine.ensure = lambda *_: (_ for _ in ()).throw(RuntimeError("private text"))
    process(db, claim(db), engine)
    assert db.kb_semantic_jobs.find_one()["state"] == "RETRY"
    assert "private text" not in str(db.kb_semantic_jobs.find_one())
    assert db.kb_documents.find_one()["semantic_index"]["status"] == "PENDING"


def test_deletion_cleanup_retains_durable_tombstone():
    db, engine = fixture_db(), FakeEngine()
    discover(db, "tenant")
    process(db, claim(db), engine)
    db.kb_documents.update_one({}, {"$set": {"deleted_at": "now"}})
    cleanup(db, "tenant", engine)
    assert db.kb_semantic_jobs.find_one()["state"] == "DELETED"
    assert db.kb_semantic_mappings.count_documents({}) == 0
    assert len(engine.deleted) == 1


def test_expired_lease_reclaims_and_exhaustion_is_visible():
    from datetime import timedelta
    from worker import now

    db = fixture_db()
    discover(db, "tenant")
    first = claim(db)
    db.kb_semantic_jobs.update_one(
        {}, {"$set": {"lease_until": now() - timedelta(seconds=1)}}
    )
    second = claim(db)
    assert first["lease_token"] != second["lease_token"]
    assert second["attempts"] == 2
    db.kb_semantic_jobs.update_one(
        {}, {"$set": {"attempts": 3, "lease_until": now() - timedelta(seconds=1)}}
    )
    assert claim(db) is None
    assert db.kb_semantic_jobs.find_one()["state"] == "FAILED"
    assert db.kb_documents.find_one()["semantic_index"]["status"] == "FAILED"


def test_semantic_outage_and_malformed_response_fall_back(monkeypatch):
    import httpx
    from tierx_kb.hybrid import search_semantic

    monkeypatch.setenv("TIERX_KB_SEMANTIC_RETRIEVAL_ENABLED", "true")

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, *args, **kwargs):
            return httpx.Response(
                200,
                json={"items": [{"text": "bad"}]},
                request=httpx.Request("POST", "http://internal/search"),
            )

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    assert search_semantic("tenant", {})["semantic_status"] == "UNAVAILABLE"
    monkeypatch.setenv("TIERX_KB_SEMANTIC_RETRIEVAL_ENABLED", "false")
    assert search_semantic("tenant", {})["semantic_status"] == "DISABLED"


def expire_lease(db):
    from datetime import timedelta
    from worker import now

    expired = now() - timedelta(seconds=1)
    db.kb_semantic_jobs.update_one({}, {"$set": {"lease_until": expired}})
    db.kb_documents.update_one({}, {"$set": {"semantic_index.lease_until": expired}})


@pytest.mark.parametrize("replacement_succeeds", [False, True])
def test_stale_worker_cannot_change_replacement_document(replacement_succeeds):
    db, engine = fixture_db(), FakeEngine()
    discover(db, "tenant")
    stale = claim(db)
    expire_lease(db)
    replacement = claim(db)
    if replacement_succeeds:
        process(db, replacement, engine)
    expected = db.kb_documents.find_one()["semantic_index"]
    process(db, stale, engine)
    assert db.kb_documents.find_one()["semantic_index"] == expected


@pytest.mark.parametrize("fails", [False, True])
def test_lease_reclaimed_during_embedding_fences_final_and_error_updates(fails):
    db, engine = fixture_db(), FakeEngine()
    discover(db, "tenant")
    stale = claim(db)
    replacement_engine = FakeEngine()

    def racing_ensure(*args):
        expire_lease(db)
        replacement = claim(db)
        process(db, replacement, replacement_engine)
        if fails:
            raise RuntimeError("safe mocked failure")
        return "old-memory"

    engine.ensure = racing_ensure
    process(db, stale, engine)
    assert db.kb_documents.find_one()["semantic_index"]["status"] == "INDEXED"
    assert db.kb_semantic_jobs.find_one()["state"] == "SUCCEEDED"


def test_expired_worker_cannot_activate_without_replacement():
    db, engine = fixture_db(), FakeEngine()
    discover(db, "tenant")
    job = claim(db)

    def delayed_ensure(*args):
        expire_lease(db)
        return "memory"

    engine.ensure = delayed_ensure
    process(db, job, engine)
    assert db.kb_documents.find_one()["semantic_index"]["status"] == "PROCESSING"
    assert db.kb_semantic_jobs.find_one()["state"] == "RUNNING"


@pytest.mark.parametrize("state", ["RUNNING", "FAILED"])
def test_document_commit_survives_missing_job_acknowledgement(state):
    db, engine = fixture_db(), FakeEngine()
    discover(db, "tenant")
    job = claim(db)
    process(db, job, engine)
    expected = db.kb_documents.find_one()["semantic_index"]
    db.kb_semantic_jobs.update_one({}, {"$set": {"state": state, "attempts": 3}})
    expire_lease(db)
    if state == "RUNNING":
        assert claim(db) is None
    cleanup(db, "tenant", engine)
    assert db.kb_semantic_jobs.find_one()["state"] == "SUCCEEDED"
    assert db.kb_documents.find_one()["semantic_index"]["status"] == "INDEXED"
    assert (
        db.kb_documents.find_one()["semantic_index"]["completed_at"]
        == expected["completed_at"]
    )
    assert engine.deleted == []
    assert db.kb_semantic_mappings.count_documents({}) == 1


def test_final_document_write_is_fenced_even_after_job_read(monkeypatch):
    db, engine = fixture_db(), FakeEngine()
    discover(db, "tenant")
    stale = claim(db)
    update = db.kb_documents.update_one
    raced = False

    def update_with_race(selector, change, *args, **kwargs):
        nonlocal raced
        if (
            change.get("$set", {}).get("semantic_index", {}).get("status") == "INDEXED"
            and not raced
        ):
            raced = True
            expire_lease(db)
            claim(db)
        return update(selector, change, *args, **kwargs)

    monkeypatch.setattr(db.kb_documents, "update_one", update_with_race)
    process(db, stale, engine)
    assert raced
    document = db.kb_documents.find_one()["semantic_index"]
    assert document["status"] == "PROCESSING"
    assert document["lease_token"] != stale["lease_token"]


def test_failed_staging_cleanup_and_explicit_new_generation_retry():
    db, engine = fixture_db(), FakeEngine()
    discover(db, "tenant")
    job = claim(db)
    db.kb_semantic_jobs.update_one({}, {"$set": {"state": "FAILED", "attempts": 3}})
    cleanup(db, "tenant", engine)
    cleanup(db, "tenant", engine)
    assert engine.deleted == [("tenant", job["job_id"])]
    assert claim(db) is None  # Bounded retries remain bounded.
    db.kb_documents.update_one({}, {"$set": {"active_index_generation": "g2"}})
    discover(db, "tenant")
    retry = claim(db)
    assert retry["job_id"] != job["job_id"]
    assert retry["attempts"] == 1


def test_semantic_search_accepts_bounded_string_tenant_ids():
    from main import Search
    from pydantic import ValidationError

    assert Search(tenant_id="tenant-1", query="network").tenant_id == "tenant-1"
    for invalid in ("", "x" * 129, {"$ne": None}):
        with pytest.raises(ValidationError):
            Search(tenant_id=invalid, query="network")


@pytest.mark.parametrize("reasons", [None, "bad", ["bad"], [{}], [{"method": []}]])
def test_malformed_semantic_reasons_use_deterministic_fallback(monkeypatch, reasons):
    import httpx
    from tierx_kb.hybrid import search_semantic

    monkeypatch.setenv("TIERX_KB_SEMANTIC_RETRIEVAL_ENABLED", "true")
    row = {
        key: "value"
        for key in (
            "document_id",
            "chunk_id",
            "text",
            "text_sha256",
            "filename",
            "parser_version",
            "index_version",
        )
    }
    row.update(
        {
            key: 1
            for key in (
                "document_version",
                "chunk_index",
                "source_start_line",
                "source_end_line",
            )
        }
    )
    row.update(heading_path=[], matched_by=reasons, semantic_score=0.9)

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, *args, **kwargs):
            return httpx.Response(
                200,
                json={
                    "items": [row],
                    "semantic_status": "AVAILABLE",
                    "degraded": False,
                },
                request=httpx.Request("POST", "http://internal/search"),
            )

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    result = search_semantic("tenant", {})
    assert result["semantic_status"] == "UNAVAILABLE"
    deterministic = [
        {"document_id": "d", "chunk_id": "c", "score": 120, "matched_by": []}
    ]
    assert merge_results(deterministic, result["items"], 5)[0]["chunk_id"] == "c"


def test_real_mem0_adapter_uses_infer_false_and_scopes_replay(monkeypatch, tmp_path):
    from mem0 import Memory
    from mem0.utils.factory import EmbedderFactory, LlmFactory
    from engine import Engine
    from qdrant_client import QdrantClient

    class Embeddings:
        def embed(self, text, memory_action=None):
            return [1.0, 0.0, 0.0]

    class NoInference:
        def generate_response(self, *args, **kwargs):
            raise AssertionError("Document indexing must never invoke an LLM")

    monkeypatch.setattr(EmbedderFactory, "create", lambda *args: Embeddings())
    monkeypatch.setattr(LlmFactory, "create", lambda *args: NoInference())
    memory = Memory.from_config(
        {
            "vector_store": {
                "provider": "qdrant",
                "config": {
                    "path": str(tmp_path / "vectors"),
                    "client": QdrantClient(":memory:"),
                    "collection_name": "documents",
                    "embedding_model_dims": 3,
                },
            },
            "history_db_path": str(tmp_path / "history.db"),
        }
    )
    engine = Engine.__new__(Engine)
    engine.memory, engine.tokenizer = memory, Tokenizer()
    metadata = {
        "source_key": "source1",
        "semantic_generation": "generation1",
        "model_id": MODEL_ID,
    }
    first = engine.ensure("tenant-a", "Original text", metadata)
    assert engine.ensure("tenant-a", "Original text", metadata) == first
    assert engine.ensure("tenant-b", "Original text", metadata) != first
    assert len(engine.search("tenant-a", "Original")) == 1
    engine.delete_generation("tenant-a", "generation1")
    assert engine.search("tenant-a", "Original") == []
    assert len(engine.search("tenant-b", "Original")) == 1
    memory.vector_store.client.close()


def test_engine_startup_uses_real_factory_and_local_adapter(monkeypatch, tmp_path):
    import engine as module
    import qdrant_client
    from mem0.utils.factory import EmbedderFactory

    actual_client = qdrant_client.QdrantClient
    monkeypatch.setattr(
        qdrant_client, "QdrantClient", lambda **_: actual_client(":memory:")
    )
    monkeypatch.setattr(
        module, "Tokenizer", SimpleNamespace(from_file=lambda _: Tokenizer())
    )
    monkeypatch.setenv("MEM0_HISTORY_PATH", str(tmp_path / "history.db"))
    monkeypatch.setenv("OLLAMA_URL", "http://local-ollama:11434")
    # Keep the actual factory and Memory.from_config. No class-constructor stubs.
    original = EmbedderFactory.provider_to_class["ollama"]
    monkeypatch.setitem(EmbedderFactory.provider_to_class, "ollama", original)
    instance = module.Engine()
    assert isinstance(instance.memory.embedding_model, module.Mem0LocalEmbedder)
    assert instance.memory.embedding_model.url == "http://local-ollama:11434"
    assert isinstance(instance.memory.db, module.NoConversationHistory)
    instance.memory.vector_store.client.close()
