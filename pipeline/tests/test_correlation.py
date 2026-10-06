import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

import app.workers.correlation_worker as correlation_module
from app.schemas.messages import ClusteredAlertMessage
from app.services.trace import TraceSpan
from app.workers.correlation_worker import (
    ANALYSIS_RUNS_COLLECTION,
    ALERTS_COLLECTION,
    CLUSTERS_COLLECTION,
    CorrelationClusteringWorker,
    as_utc,
    debounce_ms,
    display_pair,
    extract_correlation_values,
    match_entities,
    parse_severity,
)


def test_extracts_flat_nested_arrays_and_ignores_empty_and_pid():
    entities, techniques = extract_correlation_values(
        {
            "source.ip": ["10.0.0.1", "", None, "10.0.0.1"],
            "host": {"hostname": "WIN-1", "ip": ["10.0.0.2"]},
            "user": {"target": {"name": ["alice", "bob"]}},
            "process.pid": 42,
            "threat.technique.id": ["T1059.001", "T1059.001"],
        }
    )
    displayed = sorted(map(display_pair, entities))
    assert displayed == [
        "host.hostname:WIN-1",
        "host.ip:10.0.0.2",
        "source.ip:10.0.0.1",
        "user.target.name:alice",
        "user.target.name:bob",
    ]
    assert techniques == {"T1059.001"}
    assert not any("process.pid" in value for value in displayed)


def test_match_is_exact_same_field_and_mitre_is_independent():
    entities, techniques = extract_correlation_values(
        {"source.ip": "10.0.0.1", "threat.technique.id": "T1059"}
    )
    entity_matches, technique_matches = match_entities(
        entities,
        techniques,
        {"source.ip": "10.0.0.1", "threat.technique.id": "T1059"},
    )
    assert sorted(map(display_pair, entity_matches)) == ["source.ip:10.0.0.1"]
    assert technique_matches == {"T1059"}

    cross_field, no_technique = match_entities(
        entities,
        set(),
        {"destination.ip": "10.0.0.1"},
    )
    assert cross_field == set()
    assert no_technique == set()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(5, 5), ("5", 5), ("critical", 5), ("HIGH", 4), ("medium", 3), (2, 2), ("low", 1)],
)
def test_severity_parsing(raw, expected):
    assert parse_severity(raw) == expected


@pytest.mark.parametrize("raw", [None, True, 0, 6, "info", "", float("inf"), float("-inf"), float("nan")])
def test_unsupported_severity_fails_closed(raw):
    with pytest.raises(ValueError):
        parse_severity(raw)


@pytest.mark.asyncio
@pytest.mark.parametrize("severity", [None, "unsupported", float("inf"), float("nan")])
@pytest.mark.parametrize("persisted_candidate", [False, True])
async def test_invalid_severity_trace_matches_dead_letter_classification(monkeypatch, severity, persisted_candidate):
    monkeypatch.setattr(correlation_module.settings, "debug_trace_enabled", True)
    worker = CorrelationClusteringWorker()
    worker._tenant = AsyncMock(return_value={"db_name": "tenant-db", "settings": {}})
    worker._ensure_indexes = AsyncMock()
    worker._resolve_cluster = AsyncMock(return_value=None)
    worker._candidates = AsyncMock(return_value=[{
        "alert_id": "earlier-invalid-alert",
        "normalized_payload": {"event.severity": severity, "source.ip": "10.0.0.1"},
        "created_at": datetime.now(timezone.utc),
    }] if persisted_candidate else [])
    worker.produce_dead_letter = AsyncMock()
    publisher = AsyncMock()
    worker.trace_span = lambda stage, data: TraceSpan(
        publisher=publisher, stage=stage, service="test", data=data
    )
    alerts, clusters = AsyncMock(), AsyncMock()
    alerts.find_one.return_value = None
    monkeypatch.setattr(correlation_module, "get_client", lambda: {
        "tenant-db": {ALERTS_COLLECTION: alerts, CLUSTERS_COLLECTION: clusters}
    })
    payload = {
        "alert_id": "synthetic-alert", "tenant_id": "tenant-1",
        "alert_type": "login", "source_system": "SPLUNK",
        "normalized_payload": {"event.severity": "medium" if persisted_candidate else severity,
                               "source.ip": "10.0.0.1"},
        "raw_payload": {}, "fingerprint": "synthetic-fingerprint",
        "kafka_state": "ENRICHED", "status": "ANALYZING",
        "validated": True, "normalized": True, "enriched": True,
    }
    from types import SimpleNamespace
    await worker._handle(SimpleNamespace(value=payload))
    terminal = publisher.call_args.args[0]
    assert terminal["outcome"] == "FAILED"
    assert terminal["error"]["type"] == "CORRELATION_EXCEPTION"
    assert terminal["error"]["failed_fields"] == ["event.severity"]
    assert publisher.call_count == 2
    assert worker.produce_dead_letter.call_args.kwargs["error_type"] == "CORRELATION_EXCEPTION"
    assert terminal["error"]["detail"] == worker.produce_dead_letter.call_args.kwargs["error_detail"]
    assert terminal["error"]["detail"]
    clusters.insert_one.assert_not_called()


def test_debounce_defaults_and_tenant_override():
    assert debounce_ms(5, {}) == 0
    assert debounce_ms(4, {}) == 120_000
    assert debounce_ms(3, {}) == 300_000
    assert debounce_ms(1, {}) == 600_000
    assert debounce_ms(3, {"correlation_debounce_medium_ms": 7}) == 7
    with pytest.raises(ValueError):
        debounce_ms(4, {"correlation_debounce_high_ms": -1})


def test_cluster_selection_has_stable_tie_break():
    later = datetime(2026, 1, 2, tzinfo=timezone.utc)
    earlier = datetime(2026, 1, 1, tzinfo=timezone.utc)
    selected = CorrelationClusteringWorker._select_cluster(
        [
            {"cluster_id": "z", "alert_count": 3, "created_at": later},
            {"cluster_id": "b", "alert_count": 3, "created_at": earlier},
            {"cluster_id": "a", "alert_count": 3, "created_at": earlier},
            {"cluster_id": "large", "alert_count": 2, "created_at": earlier},
        ]
    )
    assert selected["cluster_id"] == "a"


def test_cluster_selection_orders_mixed_legacy_and_aware_dates():
    selected = CorrelationClusteringWorker._select_cluster(
        [
            {
                "cluster_id": "aware",
                "alert_count": 2,
                "created_at": datetime(2026, 1, 2, tzinfo=timezone.utc),
            },
            {
                "cluster_id": "legacy-naive",
                "alert_count": 2,
                "created_at": datetime(2026, 1, 1),
            },
        ]
    )
    assert selected["cluster_id"] == "legacy-naive"


@pytest.mark.asyncio
async def test_analysis_request_persists_same_version_retry_payload():
    worker = CorrelationClusteringWorker()
    cluster = {
        "cluster_id": "cluster-1",
        "tenant_id": "tenant-1",
        "lead_alert_id": "alert-1",
        "analysis_type": "CLUSTER_ANALYSIS",
        "requested_analysis_version": 2,
    }
    updated = {**cluster, "requested_analysis_version": 3}
    clusters = AsyncMock()
    clusters.find_one_and_update.return_value = updated
    db = {CLUSTERS_COLLECTION: clusters}

    message = await worker._request_analysis(
        db,
        cluster,
        outcome="IMMEDIATE",
        trigger_reason="MEMBERSHIP_CHANGED",
        is_final=False,
    )

    assert message["requested_analysis_version"] == 3
    update = clusters.find_one_and_update.await_args.args[1]
    assert update["$set"]["pending_analysis_request"] == message
    assert update["$inc"] == {"requested_analysis_version": 1}


@pytest.mark.asyncio
async def test_successful_publication_updates_all_members_and_clears_pending():
    worker = CorrelationClusteringWorker()
    worker.produce = AsyncMock()
    alerts = AsyncMock()
    clusters = AsyncMock()
    db = {
        ALERTS_COLLECTION: alerts,
        CLUSTERS_COLLECTION: clusters,
    }
    message = ClusteredAlertMessage(
        alert_id="alert-1",
        tenant_id="tenant-1",
        cluster_id="cluster-1",
        analysis_type="CLUSTER_ANALYSIS",
        debounce_outcome="IMMEDIATE",
        requested_analysis_version=4,
        trigger_reason="MEMBERSHIP_CHANGED",
        is_final=False,
    ).model_dump()

    assert await worker._publish_request(db, message) is True

    worker.produce.assert_awaited_once()
    member_update = alerts.update_many.await_args.args[1]["$set"]
    assert member_update["analysis_type"] == "CLUSTER_ANALYSIS"
    assert member_update["clustering_status"] == "CORRELATED"
    assert member_update["debounce_outcome"] == "IMMEDIATE"
    publication_update = clusters.update_one.await_args.args[1]
    assert publication_update["$max"] == {"published_analysis_version": 4}
    assert publication_update["$unset"] == {"pending_analysis_request": ""}


@pytest.mark.asyncio
async def test_failed_publication_retains_pending_request():
    worker = CorrelationClusteringWorker()
    worker.produce = AsyncMock(side_effect=[RuntimeError("broker unavailable"), None])
    worker.logger.exception = lambda *args, **kwargs: None
    alerts = AsyncMock()
    clusters = AsyncMock()
    db = {
        ALERTS_COLLECTION: alerts,
        CLUSTERS_COLLECTION: clusters,
    }
    message = ClusteredAlertMessage(
        alert_id="alert-1",
        tenant_id="tenant-1",
        cluster_id="cluster-1",
        analysis_type="SINGLE_ALERT_ANALYSIS",
        debounce_outcome="PROMOTED",
        requested_analysis_version=1,
        trigger_reason="PROMOTED",
        is_final=False,
    ).model_dump()

    assert await worker._publish_request(db, message) is False

    alerts.update_many.assert_not_awaited()
    clusters.update_one.assert_not_awaited()


def test_legacy_naive_datetime_is_normalized_to_utc():
    naive = datetime(2026, 7, 28, 14, 30)
    aware = as_utc(naive)
    assert aware.tzinfo is timezone.utc
    assert aware.isoformat() == "2026-07-28T14:30:00+00:00"


def test_client_regression_pair_has_three_exact_overlaps_with_mixed_dates():
    fixtures = (
        Path(__file__).parents[2]
        / "test-samples"
        / "pipeline-scenarios"
        / "06-correlation"
    )
    first = json.loads((fixtures / "synthetic-alert-a.json").read_text())
    second = json.loads((fixtures / "synthetic-alert-b.json").read_text())
    first_entities, first_techniques = extract_correlation_values(
        first["normalized_payload"]
    )
    shared_entities, shared_techniques = match_entities(
        first_entities,
        first_techniques,
        second["normalized_payload"],
    )

    assert sorted(map(display_pair, shared_entities)) == [
        "host.hostname:EXAMPLE-SERVER-01",
        "source.ip:192.0.2.15",
        "user.name:example.user",
    ]
    assert shared_techniques == set()

    legacy_created_at = datetime(2026, 7, 28, 12, 0)
    incoming_created_at = datetime(2026, 7, 29, 11, 59, tzinfo=timezone.utc)
    assert incoming_created_at - as_utc(legacy_created_at) < timedelta(hours=24)


@pytest.mark.asyncio
async def test_unmatched_alert_creates_mandatory_debouncing_cluster(monkeypatch):
    monkeypatch.setattr(correlation_module.settings, "debug_trace_enabled", False)
    worker = CorrelationClusteringWorker()
    worker._tenant = AsyncMock(
        return_value={"db_name": "tenant-db", "settings": {}}
    )
    worker._ensure_indexes = AsyncMock()
    worker._candidates = AsyncMock(return_value=[])

    alerts = AsyncMock()
    alerts.find_one.return_value = None
    clusters = AsyncMock()
    runs = AsyncMock()
    db = {
        ALERTS_COLLECTION: alerts,
        CLUSTERS_COLLECTION: clusters,
        ANALYSIS_RUNS_COLLECTION: runs,
    }
    monkeypatch.setattr(correlation_module, "get_client", lambda: {"tenant-db": db})

    result = await worker.process(
        {
            "alert_id": "solo-alert",
            "tenant_id": "tenant-1",
            "alert_type": "endpoint-malware",
            "source_system": "SPLUNK",
            "normalized_payload": {
                "event.severity": "medium",
                "host.hostname": "UNIQUE-HOST",
            },
            "raw_payload": {},
            "fingerprint": "unique-fingerprint",
            "kafka_state": "ENRICHED",
            "status": "ANALYZING",
            "validated": True,
            "normalized": True,
            "enriched": True,
        }
    )

    assert result is None
    cluster = clusters.insert_one.await_args.args[0]
    assert cluster["alert_ids"] == ["solo-alert"]
    assert cluster["alert_count"] == 1
    assert cluster["clustering_status"] == "DEBOUNCING"
    assert cluster["analysis_type"] == "SINGLE_ALERT_ANALYSIS"
    assert cluster["requested_analysis_version"] == 0
    member_update = alerts.update_many.await_args_list[-1].args[1]["$set"]
    assert member_update["cluster_id"] == cluster["cluster_id"]
    assert member_update["clustering_status"] == "DEBOUNCING"


@pytest.mark.asyncio
async def test_unmatched_critical_alert_creates_promoted_solo_cluster(monkeypatch):
    monkeypatch.setattr(correlation_module.settings, "debug_trace_enabled", False)
    worker = CorrelationClusteringWorker()
    worker._tenant = AsyncMock(
        return_value={"db_name": "tenant-db", "settings": {}}
    )
    worker._ensure_indexes = AsyncMock()
    worker._candidates = AsyncMock(return_value=[])

    alerts = AsyncMock()
    alerts.find_one.return_value = None
    clusters = AsyncMock()
    clusters.find_one_and_update.return_value = {"requested_analysis_version": 1}
    db = {
        ALERTS_COLLECTION: alerts,
        CLUSTERS_COLLECTION: clusters,
        ANALYSIS_RUNS_COLLECTION: AsyncMock(),
    }
    monkeypatch.setattr(correlation_module, "get_client", lambda: {"tenant-db": db})

    output = await worker.process(
        {
            "alert_id": "critical-alert",
            "tenant_id": "tenant-1",
            "alert_type": "endpoint-malware",
            "source_system": "SPLUNK",
            "normalized_payload": {
                "event.severity": "critical",
                "host.hostname": "CRITICAL-HOST",
            },
            "raw_payload": {},
            "fingerprint": "critical-fingerprint",
            "kafka_state": "ENRICHED",
            "status": "ANALYZING",
            "validated": True,
            "normalized": True,
            "enriched": True,
        }
    )

    cluster = clusters.insert_one.await_args.args[0]
    assert cluster["clustering_status"] == "SOLO_CLUSTER"
    assert output["cluster_id"] == cluster["cluster_id"]
    assert output["analysis_type"] == "SINGLE_ALERT_ANALYSIS"
    assert output["debounce_outcome"] == "PROMOTED"
    assert output["trigger_reason"] == "PROMOTED"


@pytest.mark.asyncio
async def test_solo_analysis_request_is_cluster_scoped():
    worker = CorrelationClusteringWorker()
    clusters = AsyncMock()
    clusters.find_one_and_update.return_value = {
        "cluster_id": "cluster-1",
        "requested_analysis_version": 1,
    }
    db = {CLUSTERS_COLLECTION: clusters}
    message = await worker._request_analysis(
        db,
        {
            "cluster_id": "cluster-1",
            "tenant_id": "tenant-1",
            "lead_alert_id": "alert-1",
            "analysis_type": "SINGLE_ALERT_ANALYSIS",
            "requested_analysis_version": 0,
        },
        outcome="EXPIRED_SOLO_CLUSTER",
        trigger_reason="DEBOUNCE_EXPIRED",
        is_final=False,
    )
    assert message["cluster_id"] == "cluster-1"
    assert message["analysis_type"] == "SINGLE_ALERT_ANALYSIS"
    assert message["trigger_reason"] == "DEBOUNCE_EXPIRED"


@pytest.mark.asyncio
async def test_solo_publication_marks_members_as_solo_cluster():
    worker = CorrelationClusteringWorker()
    worker.produce = AsyncMock()
    alerts = AsyncMock()
    clusters = AsyncMock()
    db = {ALERTS_COLLECTION: alerts, CLUSTERS_COLLECTION: clusters}
    message = ClusteredAlertMessage(
        alert_id="alert-1",
        tenant_id="tenant-1",
        cluster_id="cluster-1",
        analysis_type="SINGLE_ALERT_ANALYSIS",
        debounce_outcome="EXPIRED_SOLO_CLUSTER",
        requested_analysis_version=1,
        trigger_reason="DEBOUNCE_EXPIRED",
        is_final=False,
    ).model_dump()

    assert await worker._publish_request(db, message) is True
    member_update = alerts.update_many.await_args.args[1]["$set"]
    assert member_update["clustering_status"] == "SOLO_CLUSTER"
    assert member_update["analysis_type"] == "SINGLE_ALERT_ANALYSIS"
    cluster_update = clusters.update_one.await_args.args[1]
    assert cluster_update["$max"]["published_analysis_version"] == 1
    assert cluster_update["$unset"] == {"pending_analysis_request": ""}
