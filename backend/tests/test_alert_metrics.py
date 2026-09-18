from datetime import datetime, timedelta, timezone

import pytest

from app.core.alert_metrics import (
    build_alert_query,
    canonical_severity,
    host_from_alert,
    severity_expression,
    severity_from_alert,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (5, "CRITICAL"),
        ("critical", "CRITICAL"),
        (" Kritisch ", "CRITICAL"),
        (4, "HIGH"),
        ("hoch", "HIGH"),
        (3, "MEDIUM"),
        ("mittel", "MEDIUM"),
        (1, "LOW"),
        ("2", "LOW"),
        ("niedrig", "LOW"),
        (None, "UNKNOWN"),
        (True, "UNKNOWN"),
        ("urgent", "UNKNOWN"),
    ],
)
def test_canonical_severity(value, expected):
    assert canonical_severity(value) == expected


def test_alert_values_support_canonical_flat_nested_and_missing_fields():
    assert severity_from_alert({"severity": "HIGH"}) == "HIGH"
    assert severity_from_alert(
        {"normalized_payload": {"event.severity": "5"}}
    ) == "CRITICAL"
    assert severity_from_alert(
        {"normalized_payload": {"event": {"severity": "medium"}}}
    ) == "MEDIUM"
    assert severity_from_alert({"normalized_payload": {}}) == "UNKNOWN"
    assert host_from_alert(
        {"normalized_payload": {"host.hostname": " WIN-1 "}}
    ) == "WIN-1"
    assert host_from_alert(
        {"normalized_payload": {"host": {"hostname": "WIN-2"}}}
    ) == "WIN-2"


def test_mongo_severity_expression_does_not_use_get_field():
    assert "$getField" not in repr(severity_expression())


def test_alert_query_reuses_search_and_period_semantics():
    now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    query, search = build_alert_query(q=" malware ", since_hours=24, now=now)
    assert search == "malware"
    assert query["created_at"]["$gte"] == now - timedelta(hours=24)
    assert len(query["$or"]) == 4
