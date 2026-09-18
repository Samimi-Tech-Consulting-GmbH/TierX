import hashlib
import pytest

from tierx_kb import (
    build_alert_query,
    build_text_query,
    extract_indicators,
    parse_document,
    rank_chunks,
)


@pytest.mark.asyncio
async def test_empty_hybrid_retrieval_preserves_version():
    from app.services.knowledge_base import KnowledgeBaseRetriever
    from tierx_kb.hybrid import HYBRID_VERSION

    class EmptyCollection:
        def find(self, *args, **kwargs):
            return self

        async def to_list(self, **kwargs):
            return []

    result = await KnowledgeBaseRetriever().search_alert(
        {"kb_documents": EmptyCollection()}, alert_type="endpoint", normalized_payload={},
        top_k=5, tenant_id="tenant", retrieval_mode="hybrid",
    )
    assert result["retrieval_version"] == HYBRID_VERSION
    assert result["semantic_status"] == "NOT_INDEXED"


def chunks(text: str, file_format: str = "md"):
    return parse_document(
        text,
        file_format=file_format,
        document_id="doc-1",
        document_version=1,
        document_sha256=hashlib.sha256(text.encode()).hexdigest(),
        index_generation="generation-1",
    )


def test_markdown_heading_chunking_is_stable():
    text = (
        "# Network\n\nCorporate network details.\n\n## Production\n\nEXAMPLE-DB01 is critical."
    )
    first = chunks(text)
    second = chunks(text)
    assert first == second
    assert [item["heading_path"] for item in first] == [
        ["Network"],
        ["Network", "Production"],
    ]
    assert [item["source_start_line"] for item in first] == [3, 7]


def test_plain_text_and_oversized_blocks_have_bounded_chunks():
    parsed = chunks("first paragraph\n\nsecond paragraph", "txt")
    assert len(parsed) == 1
    long = chunks("x " * 2_000, "txt")
    assert len(long) >= 2
    assert all(len(item["text"]) <= 3_200 for item in long)


def test_cidr_exact_lexical_synonym_and_fuzzy_ranking():
    corpus = chunks(
        "# Production\n\nEXAMPLE-DB01 is in 203.0.113.0/24.\n\n"
        "# Accounts\n\nInteraktive Anmeldung eines Dienstkonto ist verdächtig.\n\n"
        "# Endpoint\n\nUngewöhnliche PowerShell-Befehle müssen untersucht werden."
    )
    cidr = rank_chunks(
        corpus,
        build_alert_query("security.notice", {"destination": {"ip": "203.0.113.10"}}),
    )
    assert cidr[0]["heading_path"] == ["Production"]
    assert any(item["method"] == "CIDR_CONTAINS" for item in cidr[0]["matched_by"])

    synonym = rank_chunks(corpus, build_text_query("service account login"))
    assert synonym[0]["heading_path"] == ["Accounts"]
    assert any(item["method"] == "SOC_SYNONYM" for item in synonym[0]["matched_by"])

    fuzzy = rank_chunks(corpus, build_text_query("endpoint powershel"))
    assert fuzzy[0]["heading_path"] == ["Endpoint"]


def test_unrelated_query_returns_no_matches():
    assert (
        rank_chunks(
            chunks("EXAMPLE-DB01 production database"), build_text_query("banana orchard")
        )
        == []
    )


def test_alert_query_uses_only_the_approved_normalized_field_allowlist():
    query = build_alert_query(
        "qzx.unmatched",
        {
            "event": {"severity": "5", "type": "numbered-section"},
            "rule": {"id": "internal-rule-id"},
            "user": {"id": "internal-user-id"},
            "process": {"parent": {"name": "parent-only.exe"}},
            "host": {"domain": "approved.example.com"},
        },
    )
    values = {(item["field"], item["value"]) for item in query["field_values"]}

    assert ("host.domain", "approved.example.com") in values
    assert ("event.severity", "5") not in values
    assert ("event.type", "numbered-section") not in values
    assert ("rule.id", "internal-rule-id") not in values
    assert ("user.id", "internal-user-id") not in values
    assert ("process.parent.name", "parent-only.exe") not in values


def test_indicator_extraction_requires_explicit_port_context_and_finds_domains():
    indicators = extract_indicators(
        "See https://security.example.com/report and corp.example.com. "
        "TCP port 443 is allowed, but 8443 appears without port context."
    )
    assert indicators["domains"] == ["corp.example.com", "security.example.com"]
    assert indicators["ports"] == ["443"]
