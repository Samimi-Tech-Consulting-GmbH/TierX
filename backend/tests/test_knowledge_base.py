import hashlib
import io
import os
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import mongomock
import mongomock.gridfs
import mongoengine
import pytest
from fastapi.testclient import TestClient

mongomock.gridfs.enable_gridfs_integration()

from main import app
from app.core.security import create_access_token

client = TestClient(app)
KB_FIXTURES = Path(__file__).parent / "fixtures" / "knowledge_base"

mongoengine.disconnect_all()
mongoengine.connect(
    "soc_mind_platform",
    host="mongodb://unit-test.invalid/",
    mongo_client_class=mongomock.MongoClient,
    alias="default",
    uuidRepresentation="standard",
)

import app.db.mongodb
import app.services.knowledge_base_service
import app.services.tenant_service


class MockDatabaseManager:
    @staticmethod
    def initialize():
        pass

    @staticmethod
    def get_tenant_db_alias(db_name: str) -> str:
        alias = f"tenant_{db_name}"
        if alias not in mongoengine.connection._connections:
            mongoengine.connect(
                db_name,
                host="mongodb://unit-test.invalid/",
                mongo_client_class=mongomock.MongoClient,
                alias=alias,
                uuidRepresentation="standard",
            )
        return alias

    @staticmethod
    def get_tenant_database(db_name: str):
        alias = MockDatabaseManager.get_tenant_db_alias(db_name)
        return mongoengine.connection.get_db(alias)


def headers(role="PLATFORM_ADMIN", tenant_id=None):
    token = create_access_token(
        user_id=f"{role.lower()}-id",
        email=f"{role.lower()}@example.com",
        role=role,
        tenant_id=tenant_id,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def mock_mongo(monkeypatch):
    for module in (
        app.db.mongodb,
        app.services.tenant_service,
        app.services.knowledge_base_service,
    ):
        monkeypatch.setattr(module, "DatabaseManager", MockDatabaseManager)
    yield


@pytest.fixture(autouse=True)
def clean_db(mock_mongo):
    from app.models.tenant import Tenant
    from app.models.user import User

    for tenant in Tenant.objects:
        connection = mongoengine.connection.get_connection(
            MockDatabaseManager.get_tenant_db_alias(str(tenant.db_name))
        )
        connection.drop_database(str(tenant.db_name))
    Tenant.drop_collection()
    User.drop_collection()
    yield


@pytest.fixture
def tenants():
    first = client.post(
        "/api/v1/admin/tenants",
        json={"name": "kb-one", "display_name": "KB One"},
        headers=headers(),
    ).json()
    second = client.post(
        "/api/v1/admin/tenants",
        json={"name": "kb-two", "display_name": "KB Two"},
        headers=headers(),
    ).json()
    return first, second


def ooxml_bytes(kind: str) -> bytes:
    target = "word/document.xml" if kind == "docx" else "xl/workbook.xml"
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr(target, "<root/>")
    return stream.getvalue()


def upload(tenant_id: str, name: str, content: bytes, request_headers=None):
    return client.post(
        f"/api/v1/tenants/{tenant_id}/knowledge-base/documents",
        headers=request_headers or headers(),
        files={"file": (name, content, "application/octet-stream")},
    )


def test_processing_indexes_are_compatible_with_existing_upload_index(tenants):
    from app.services.knowledge_base_service import KnowledgeBaseService

    tenant, _ = tenants
    db = MockDatabaseManager.get_tenant_database(tenant["db_name"])
    db.kb_documents.create_index(
        [("status", 1), ("uploaded_at", -1)], name="status_uploaded_at"
    )

    KnowledgeBaseService._ensure_database_indexes(db)

    assert db.kb_documents.index_information()["status_uploaded_at"]["key"] == [
        ("status", 1),
        ("uploaded_at", -1),
    ]


@pytest.mark.parametrize(
    ("name", "content", "expected_format"),
    [
        ("notes.md", b"# Investigation\n", "md"),
        ("notes.txt", "Evidence\n".encode(), "txt"),
    ],
)
def test_uploads_supported_formats(tenants, name, content, expected_format):
    tenant, _ = tenants
    response = upload(tenant["tenant_id"], name, content)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["file_format"] == expected_format
    assert body["status"] == "PENDING"
    assert body["size_bytes"] == len(content)
    assert body["sha256"] == hashlib.sha256(content).hexdigest()
    assert body["uploaded_by"]["email"] == "platform_admin@example.com"
    assert "gridfs_id" not in body


@pytest.mark.parametrize(
    ("name", "content", "detail"),
    [
        ("empty.txt", b"", "Empty files"),
        ("binary.txt", b"hello\x00world", "NUL"),
        ("invalid.txt", b"\xff", "UTF-8"),
        ("wrong.pdf", b"not a pdf", "Unsupported"),
        ("wrong.docx", b"not a zip", "Unsupported"),
        ("wrong.xlsx", ooxml_bytes("docx"), "Unsupported"),
        ("script.exe", b"hello", "Unsupported"),
    ],
)
def test_rejects_invalid_uploads_and_cleans_partial_gridfs(
    tenants, name, content, detail
):
    tenant, _ = tenants
    response = upload(tenant["tenant_id"], name, content)
    assert response.status_code == (415 if detail == "Unsupported" else 422)
    assert detail in response.json()["detail"]

    db = MockDatabaseManager.get_tenant_database(tenant["db_name"])
    assert db.kb_documents.count_documents({}) == 0
    assert db.kb_files.files.count_documents({}) == 0
    assert db.kb_files.chunks.count_documents({}) == 0
    onboarding = db.onboarding_status.find_one({})
    assert onboarding["kb_document_uploaded"] is False


def test_enforces_size_boundary_without_retaining_partial_file(tenants, monkeypatch):
    tenant, _ = tenants
    monkeypatch.setattr(app.services.knowledge_base_service, "MAX_FILE_BYTES", 4)

    accepted = upload(tenant["tenant_id"], "four.txt", b"four")
    assert accepted.status_code == 201
    rejected = upload(tenant["tenant_id"], "five.txt", b"fives")
    assert rejected.status_code == 413

    db = MockDatabaseManager.get_tenant_database(tenant["db_name"])
    assert db.kb_documents.count_documents({}) == 1
    assert db.kb_files.files.count_documents({}) == 1


def test_metadata_failure_removes_gridfs_bytes(tenants, monkeypatch):
    tenant, _ = tenants
    db = MockDatabaseManager.get_tenant_database(tenant["db_name"])
    collection = db.kb_documents

    def fail_insert(_document):
        raise RuntimeError("metadata write failed")

    monkeypatch.setattr(collection, "insert_one", fail_insert)
    with pytest.raises(RuntimeError, match="metadata write failed"):
        upload(tenant["tenant_id"], "metadata.txt", b"metadata")

    assert db.kb_files.files.count_documents({}) == 0
    assert db.kb_files.chunks.count_documents({}) == 0
    assert db.onboarding_status.find_one({})["kb_document_uploaded"] is False


def test_download_is_exact_and_forced_as_attachment(tenants):
    tenant, _ = tenants
    content = b"exact bytes\n"
    created = upload(tenant["tenant_id"], "evidence report.txt", content).json()

    response = client.get(
        f"/api/v1/tenants/{tenant['tenant_id']}/knowledge-base/documents/"
        f"{created['document_id']}/download",
        headers=headers("TENANT_OPERATOR", tenant["tenant_id"]),
    )
    assert response.status_code == 200
    assert response.content == content
    assert response.headers["content-length"] == str(len(content))
    assert response.headers["content-disposition"].startswith("attachment;")
    assert response.headers["x-content-type-options"] == "nosniff"


def test_duplicates_are_independent_and_list_is_stably_paginated(tenants):
    tenant, _ = tenants
    first = upload(tenant["tenant_id"], "same.txt", b"same").json()
    second = upload(tenant["tenant_id"], "same.txt", b"same").json()
    assert first["document_id"] != second["document_id"]

    response = client.get(
        f"/api/v1/tenants/{tenant['tenant_id']}/knowledge-base/documents?skip=0&limit=1",
        headers=headers("TENANT_OPERATOR", tenant["tenant_id"]),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert body["skip"] == 0
    assert body["limit"] == 1
    assert len(body["items"]) == 1


def test_processes_chunks_and_supports_search_and_reprocessing(tenants):
    from app.services.knowledge_base_service import KnowledgeBaseService

    tenant, _ = tenants
    content = (
        "# Production Environment\n\n"
        "The critical server EXAMPLE-DB01 is located in 203.0.113.0/24.\n\n"
        "## Endpoint guidance\n\n"
        "Ungewöhnliche PowerShell-Befehle müssen untersucht werden.\n"
    ).encode()
    created = upload(tenant["tenant_id"], "environment.md", content).json()
    db = MockDatabaseManager.get_tenant_database(tenant["db_name"])
    claimed = KnowledgeBaseService.claim_next(db)
    assert claimed["document_id"] == created["document_id"]
    assert KnowledgeBaseService.process_claimed(db, claimed) == 2

    detail = client.get(
        f"/api/v1/tenants/{tenant['tenant_id']}/knowledge-base/documents/{created['document_id']}",
        headers=headers("TENANT_OPERATOR", tenant["tenant_id"]),
    )
    assert detail.status_code == 200
    assert detail.json()["status"] == "INDEXED"
    assert detail.json()["chunk_count"] == 2

    chunks = client.get(
        f"/api/v1/tenants/{tenant['tenant_id']}/knowledge-base/documents/{created['document_id']}/chunks",
        headers=headers("TENANT_OPERATOR", tenant["tenant_id"]),
    ).json()
    assert chunks["total"] == 2
    assert chunks["items"][0]["heading_path"] == ["Production Environment"]

    semantic_term = client.post(
        f"/api/v1/tenants/{tenant['tenant_id']}/knowledge-base/search",
        headers=headers("TENANT_OPERATOR", tenant["tenant_id"]),
        json={"query": "suspicious powershell", "top_k": 5},
    )
    assert semantic_term.status_code == 200
    assert semantic_term.json()["status"] == "OK"
    assert "PowerShell" in semantic_term.json()["items"][0]["text"]

    cidr = client.post(
        f"/api/v1/tenants/{tenant['tenant_id']}/knowledge-base/search",
        headers=headers("TENANT_OPERATOR", tenant["tenant_id"]),
        json={"query": "203.0.113.10"},
    ).json()
    assert any(
        reason["method"] == "CIDR_CONTAINS" for reason in cidr["items"][0]["matched_by"]
    )

    reprocess = client.post(
        f"/api/v1/tenants/{tenant['tenant_id']}/knowledge-base/documents/{created['document_id']}/reprocess",
        headers=headers(),
    )
    assert reprocess.status_code == 200
    assert reprocess.json()["status"] == "PENDING"
    claimed_again = KnowledgeBaseService.claim_next(db)
    assert KnowledgeBaseService.process_claimed(db, claimed_again) == 2
    assert db.kb_chunks.count_documents({"document_id": created["document_id"]}) == 2


def test_supplied_document_shapes_produce_stable_golden_results():
    from tierx_kb import parse_document

    observed = {}
    for path in sorted(KB_FIXTURES.iterdir()):
        content = path.read_text(encoding="utf-8")
        checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()
        first = parse_document(
            content,
            file_format=path.suffix.removeprefix("."),
            document_id=path.stem,
            document_version=1,
            document_sha256=checksum,
            index_generation="generation-a",
        )
        replay = parse_document(
            content,
            file_format=path.suffix.removeprefix("."),
            document_id=path.stem,
            document_version=1,
            document_sha256=checksum,
            index_generation="generation-b",
        )
        assert [item["chunk_id"] for item in first] == [
            item["chunk_id"] for item in replay
        ]
        assert all(
            item["source_start_line"] <= item["source_end_line"] for item in first
        )
        observed[path.name] = len(first)

    assert observed == {
        "01_network.md": 2,
        "02_identity.md": 1,
        "03_baselines.md": 1,
        "04_environment.txt": 1,
    }


def test_failed_reprocessing_preserves_last_successful_generation(tenants, monkeypatch):
    from app.services.knowledge_base_service import KnowledgeBaseService

    tenant, _ = tenants
    created = upload(
        tenant["tenant_id"], "stable.md", b"# Production\n\nEXAMPLE-DB01 is 203.0.113.10."
    ).json()
    db = MockDatabaseManager.get_tenant_database(tenant["db_name"])
    first_claim = KnowledgeBaseService.claim_next(db)
    KnowledgeBaseService.process_claimed(db, first_claim)
    before = db.kb_documents.find_one({"document_id": created["document_id"]})
    old_generation = before["active_index_generation"]

    KnowledgeBaseService.reprocess_document(tenant["tenant_id"], created["document_id"])
    second_claim = KnowledgeBaseService.claim_next(db)
    monkeypatch.setattr(
        "app.services.knowledge_base_service.parse_document",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("broken parser")),
    )
    with pytest.raises(ValueError, match="broken parser"):
        KnowledgeBaseService.process_claimed(db, second_claim)

    failed = db.kb_documents.find_one({"document_id": created["document_id"]})
    assert failed["status"] == "FAILED"
    assert failed["active_index_generation"] == old_generation
    assert (
        db.kb_chunks.count_documents(
            {"document_id": created["document_id"], "index_generation": old_generation}
        )
        == 1
    )
    result = KnowledgeBaseService.search(tenant["tenant_id"], "EXAMPLE-DB01", top_k=5)
    assert result.status == "OK"


def test_expired_claim_cannot_commit_after_another_worker_reclaims_it(tenants):
    from app.services.knowledge_base_service import KnowledgeBaseService

    tenant, _ = tenants
    created = upload(tenant["tenant_id"], "lease.md", b"# Host\n\nEXAMPLE-DB01").json()
    db = MockDatabaseManager.get_tenant_database(tenant["db_name"])
    stale_claim = KnowledgeBaseService.claim_next(db, lease_seconds=60)
    db.kb_documents.update_one(
        {"document_id": created["document_id"]},
        {
            "$set": {
                "processing_lease_expires_at": datetime.now(timezone.utc)
                - timedelta(seconds=1)
            }
        },
    )
    active_claim = KnowledgeBaseService.claim_next(db, lease_seconds=60)
    assert active_claim["processing_lease_id"] != stale_claim["processing_lease_id"]

    with pytest.raises(RuntimeError, match="lease was lost"):
        KnowledgeBaseService.process_claimed(db, stale_claim)
    current = db.kb_documents.find_one({"document_id": created["document_id"]})
    assert current["status"] == "PROCESSING"
    assert current["processing_lease_id"] == active_claim["processing_lease_id"]
    assert db.kb_chunks.count_documents({"document_id": created["document_id"]}) == 0


def test_legacy_non_text_document_remains_stored_only(tenants):
    import gridfs
    from datetime import datetime, timezone

    tenant, _ = tenants
    db = MockDatabaseManager.get_tenant_database(tenant["db_name"])
    file_id = gridfs.GridFS(db, collection="kb_files").put(
        b"%PDF-1.7\n", filename="legacy.pdf"
    )
    now = datetime.now(timezone.utc)
    db.kb_documents.insert_one(
        {
            "document_id": "legacy-pdf",
            "tenant_id": tenant["tenant_id"],
            "original_filename": "legacy.pdf",
            "file_format": "pdf",
            "content_type": "application/pdf",
            "size_bytes": 9,
            "sha256": hashlib.sha256(b"%PDF-1.7\n").hexdigest(),
            "status": "PENDING",
            "gridfs_id": file_id,
            "uploaded_by": {"user_id": "legacy", "email": "legacy@example.com"},
            "uploaded_at": now,
            "updated_at": now,
            "deleted_at": None,
        }
    )
    listed = client.get(
        f"/api/v1/tenants/{tenant['tenant_id']}/knowledge-base/documents",
        headers=headers("TENANT_OPERATOR", tenant["tenant_id"]),
    ).json()
    legacy = next(
        item for item in listed["items"] if item["document_id"] == "legacy-pdf"
    )
    assert legacy["processing_supported"] is False


def test_operator_can_read_but_not_upload_or_delete(tenants):
    tenant, _ = tenants
    created = upload(tenant["tenant_id"], "readable.md", b"# readable").json()
    operator = headers("TENANT_OPERATOR", tenant["tenant_id"])

    listed = client.get(
        f"/api/v1/tenants/{tenant['tenant_id']}/knowledge-base/documents",
        headers=operator,
    )
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    denied_upload = upload(
        tenant["tenant_id"], "denied.txt", b"denied", request_headers=operator
    )
    assert denied_upload.status_code == 403
    denied_delete = client.delete(
        f"/api/v1/tenants/{tenant['tenant_id']}/knowledge-base/documents/"
        f"{created['document_id']}",
        headers=operator,
    )
    assert denied_delete.status_code == 403


def test_tenant_isolation_blocks_cross_tenant_reads(tenants):
    first, second = tenants
    created = upload(first["tenant_id"], "isolated.txt", b"private").json()
    second_operator = headers("TENANT_OPERATOR", second["tenant_id"])

    listed = client.get(
        f"/api/v1/tenants/{first['tenant_id']}/knowledge-base/documents",
        headers=second_operator,
    )
    assert listed.status_code == 403
    downloaded = client.get(
        f"/api/v1/tenants/{first['tenant_id']}/knowledge-base/documents/"
        f"{created['document_id']}/download",
        headers=second_operator,
    )
    assert downloaded.status_code == 403


def test_tenant_admin_uploads_and_deletes_bytes_with_soft_delete_audit(tenants):
    tenant, _ = tenants
    tenant_admin = headers("TENANT_ADMIN", tenant["tenant_id"])
    created = upload(
        tenant["tenant_id"], "delete-me.txt", b"delete", request_headers=tenant_admin
    ).json()
    db = MockDatabaseManager.get_tenant_database(tenant["db_name"])
    metadata = db.kb_documents.find_one({"document_id": created["document_id"]})
    assert db.kb_files.files.count_documents({"_id": metadata["gridfs_id"]}) == 1

    response = client.delete(
        f"/api/v1/tenants/{tenant['tenant_id']}/knowledge-base/documents/"
        f"{created['document_id']}",
        headers=tenant_admin,
    )
    assert response.status_code == 204
    metadata = db.kb_documents.find_one({"document_id": created["document_id"]})
    assert metadata["deleted_at"] is not None
    assert metadata["deleted_by"]["email"] == "tenant_admin@example.com"
    assert db.kb_files.files.count_documents({"_id": metadata["gridfs_id"]}) == 0
    assert db.kb_files.chunks.count_documents({"files_id": metadata["gridfs_id"]}) == 0

    listed = client.get(
        f"/api/v1/tenants/{tenant['tenant_id']}/knowledge-base/documents",
        headers=tenant_admin,
    )
    assert listed.json()["total"] == 0
    missing = client.get(
        f"/api/v1/tenants/{tenant['tenant_id']}/knowledge-base/documents/"
        f"{created['document_id']}/download",
        headers=tenant_admin,
    )
    assert missing.status_code == 404


def test_onboarding_updates_only_after_successful_persistence(tenants):
    tenant, _ = tenants
    failed = upload(tenant["tenant_id"], "bad.pdf", b"bad")
    assert failed.status_code == 415
    db = MockDatabaseManager.get_tenant_database(tenant["db_name"])
    assert db.onboarding_status.find_one({})["kb_document_uploaded"] is False

    succeeded = upload(tenant["tenant_id"], "good.md", b"# good")
    assert succeeded.status_code == 201
    assert db.onboarding_status.find_one({})["kb_document_uploaded"] is True


def test_unauthenticated_requests_are_rejected(tenants):
    tenant, _ = tenants
    response = client.get(
        f"/api/v1/tenants/{tenant['tenant_id']}/knowledge-base/documents"
    )
    assert response.status_code in {401, 403}


@pytest.mark.skipif(not os.getenv("MONGO44_URL"), reason="MongoDB 4.4 not available")
def test_mongo44_gridfs_round_trip_supports_processor_text_read():
    import gridfs
    from pymongo import MongoClient

    mongo = MongoClient(os.environ["MONGO44_URL"], serverSelectionTimeoutMS=3000)
    db_name = f"tierx_kb_gridfs_test_{uuid4().hex}"
    db = mongo[db_name]
    try:
        fs = gridfs.GridFS(db, collection="kb_files")
        content = "# Production\n\nEXAMPLE-DB01 uses 203.0.113.10.".encode("utf-8")
        file_id = fs.put(content, filename="environment.md")
        stored = fs.get(file_id)
        try:
            assert stored.read().decode("utf-8") == content.decode("utf-8")
        finally:
            stored.close()
    finally:
        mongo.drop_database(db_name)
        mongo.close()


def test_hybrid_search_keeps_deterministic_evidence_on_service_failure(tenants, monkeypatch):
    from app.services.knowledge_base_service import KnowledgeBaseService
    tenant, _ = tenants
    upload(tenant["tenant_id"], "net.md", b"# Network\n\nProduction network 10.0.0.0/8 and EXAMPLE-DB01")
    db = MockDatabaseManager.get_tenant_database(tenant["db_name"])
    KnowledgeBaseService.process_claimed(db, KnowledgeBaseService.claim_next(db))
    monkeypatch.setattr(app.services.knowledge_base_service, "search_semantic",
                        lambda *_: {"items": [], "semantic_status": "UNAVAILABLE", "degraded": True})
    response = client.post(f"/api/v1/tenants/{tenant['tenant_id']}/knowledge-base/search",
        headers=headers("TENANT_OPERATOR", tenant["tenant_id"]),
        json={"query": "10.1.2.3", "retrieval_mode": "hybrid"})
    assert response.status_code == 200
    result = response.json()
    assert result["degraded"] and result["retrieval_mode"] == "hybrid"
    assert result["items"][0]["matched_by"][0]["method"] == "CIDR_CONTAINS"
    assert result["items"][0]["retrieval_channels"] == ["deterministic"]


def test_playbook_hybrid_mode_defaults_and_validation():
    from app.schemas.playbook import PlaybookKnowledgeBase
    from pydantic import ValidationError
    assert PlaybookKnowledgeBase(enabled=True).retrieval_mode == "deterministic"
    assert PlaybookKnowledgeBase(enabled=True, retrieval_mode="hybrid").retrieval_mode == "hybrid"
    with pytest.raises(ValidationError):
        PlaybookKnowledgeBase(retrieval_mode="cloud")


def test_semantic_progress_excludes_internal_lease_fields(tenants):
    tenant, _ = tenants
    doc = upload(tenant["tenant_id"], "network.md", b"network context").json()
    db = MockDatabaseManager.get_tenant_database(tenant["db_name"])
    db.kb_documents.update_one({"document_id": doc["document_id"]}, {"$set": {
        "semantic_index": {"status": "PROCESSING", "model": "granite-embedding:278m",
                           "lease_token": "internal-fencing-value", "lease_attempt": 2,
                           "lease_until": "internal-date", "future_internal_field": "hidden"},
    }})
    base = f"/api/v1/tenants/{tenant['tenant_id']}/knowledge-base/documents"
    for endpoint in (base, base + "/" + doc["document_id"]):
        response = client.get(endpoint, headers=headers("TENANT_OPERATOR", tenant["tenant_id"]))
        assert response.status_code == 200
        value = response.json()
        if "items" in value:
            value = value["items"][0]
        assert value["semantic_index"]["status"] == "PROCESSING"
        assert not ({"lease_token", "lease_attempt", "lease_until", "future_internal_field"} & value["semantic_index"].keys())


def test_empty_hybrid_search_reports_hybrid_version(tenants):
    from tierx_kb.hybrid import HYBRID_VERSION

    tenant, _ = tenants
    response = client.post(f"/api/v1/tenants/{tenant['tenant_id']}/knowledge-base/search",
                           headers=headers(), json={"query": "network", "retrieval_mode": "hybrid"})
    assert response.status_code == 200
    assert response.json()["retrieval_version"] == HYBRID_VERSION
    assert response.json()["semantic_status"] == "NOT_INDEXED"


def test_legacy_knowledge_base_import_reexports_tierx_package():
    from soc_mind_kb import parse_document as legacy_parse
    from tierx_kb import parse_document as canonical_parse

    assert legacy_parse is canonical_parse
