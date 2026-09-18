import os
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pymongo import MongoClient

from app.core.alert_metrics import aggregate_alert_stats
from app.services.dashboard_service import PlatformDashboardService


MONGO44_URL = os.getenv("MONGO44_URL")


@pytest.mark.skipif(not MONGO44_URL, reason="requires a real MongoDB 4.4 server")
def test_alert_stats_execute_on_real_mongodb_44_without_get_field():
    client = MongoClient(MONGO44_URL, serverSelectionTimeoutMS=5000)
    version = client.server_info()["version"]
    assert version.startswith("4.4."), version
    database = client[f"soc_mind_kpi_test_{uuid4().hex}"]
    try:
        database.alerts.insert_many(
            [
                {"severity": "CRITICAL"},
                {"normalized_payload": {"event.severity": "5"}},
                {"normalized_payload": {"event": {"severity": "high"}}},
                {"normalized_payload": {"event.severity": 3}},
                {"normalized_payload": {"event": {"severity": "2"}}},
                {"normalized_payload": {"event.severity": "invalid"}},
                {},
            ]
        )

        result = aggregate_alert_stats(database.alerts, {})

        assert result == {
            "filtered_total": 7,
            "severity": {
                "CRITICAL": 2,
                "HIGH": 1,
                "MEDIUM": 1,
                "LOW": 1,
                "UNKNOWN": 2,
            },
        }
    finally:
        client.drop_database(database.name)


@pytest.mark.skipif(not MONGO44_URL, reason="requires a real MongoDB 4.4 server")
def test_dashboard_definitions_execute_on_mongodb_44(monkeypatch):
    client = MongoClient(MONGO44_URL, serverSelectionTimeoutMS=5000)
    database = client[f"soc_mind_dashboard_test_{uuid4().hex}"]
    now = datetime.now(timezone.utc)
    try:
        database.alerts.insert_many(
            [
                {
                    "alert_id": "critical-flat",
                    "normalized_payload": {"event.severity": "5"},
                    "created_at": now,
                },
                {
                    "alert_id": "critical-nested",
                    "normalized_payload": {"event": {"severity": "critical"}},
                    "created_at": now,
                },
                {
                    "alert_id": "low",
                    "severity": "LOW",
                    "created_at": now,
                },
            ]
        )
        database.clusters.insert_many(
            [
                {"cluster_id": "open", "status": "OPEN", "alert_count": 2},
                {
                    "cluster_id": "investigating",
                    "status": "UNDER_INVESTIGATION",
                    "alert_count": 3,
                },
                {
                    "cluster_id": "escalated",
                    "status": "ESCALATED",
                    "alert_count": 4,
                },
                {"cluster_id": "closed", "status": "CLOSED", "alert_count": 5},
                {
                    "cluster_id": "false-positive",
                    "status": "FALSE_POSITIVE",
                    "alert_count": 6,
                },
                {
                    "cluster_id": "unknown-workflow",
                    "status": "PENDING",
                    "alert_count": 100,
                },
            ]
        )
        monkeypatch.setattr(
            "app.services.dashboard_service.DatabaseManager.get_tenant_database",
            lambda db_name: database,
        )

        result = PlatformDashboardService._aggregate_tenant(
            SimpleNamespace(tenant_id="tenant-1", db_name=database.name),
            PlatformDashboardService._windows(now),
        )

        assert result["total_alerts"] == 3
        assert result["critical_alerts"] == 2
        assert result["active_clusters"] == 3
        assert result["open_alerts"] == 9
        assert result["resolved_clusters"] == 2
    finally:
        client.drop_database(database.name)
