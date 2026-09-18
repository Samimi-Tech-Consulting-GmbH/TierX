from datetime import datetime, timedelta, timezone

import mongomock
import pytest
from fastapi import HTTPException

from app.services.cluster_service import ClusterService


def _cluster(cluster_id="cluster-1", status="OPEN"):
    now = datetime.now(timezone.utc)
    return {
        "cluster_id": cluster_id,
        "tenant_id": "tenant-1",
        "lead_alert_id": "alert-1",
        "alert_ids": ["alert-1"],
        "alert_count": 1,
        "is_open_for_grouping": True,
        "debounce_expires_at": now,
        "grouping_window_expires_at": now + timedelta(hours=24),
        "correlation_basis": {
            "method": "ENTITY_OVERLAP",
            "shared_entities": [],
            "mitre_techniques": [],
        },
        "first_seen": now,
        "last_seen": now,
        "severity": {"max": 3, "avg": 3.0, "distribution": {"3": 1}},
        "analysis_type": "SINGLE_ALERT_ANALYSIS",
        "status": status,
        "created_at": now,
        "updated_at": now,
    }


@pytest.fixture
def tenant_db(monkeypatch):
    database = mongomock.MongoClient()["tenant"]
    monkeypatch.setattr(
        ClusterService,
        "_db",
        staticmethod(lambda tenant_id: database),
    )
    return database


def test_cluster_list_detail_and_member_alerts(tenant_db):
    tenant_db.clusters.insert_one(_cluster())
    tenant_db.alerts.insert_one(
        {
            "alert_id": "alert-1",
            "tenant_id": "tenant-1",
            "created_at": datetime.now(timezone.utc),
        }
    )
    page = ClusterService.list_clusters(
        "tenant-1",
        skip=0,
        limit=50,
        cluster_status=None,
        assigned_to=None,
        is_open_for_grouping=True,
        created_after=None,
        created_before=None,
    )
    detail = ClusterService.get_cluster("tenant-1", "cluster-1")
    alerts = ClusterService.alerts("tenant-1", "cluster-1", 0, 50)
    assert page.total == 1
    assert detail.cluster_id == "cluster-1"
    assert detail.affected_host_count == 0
    assert alerts.total == 1


def test_cluster_detail_counts_all_distinct_hosts_beyond_first_200_alerts(tenant_db):
    alert_ids = [f"alert-{index}" for index in range(250)]
    cluster = _cluster()
    cluster["alert_ids"] = alert_ids
    cluster["alert_count"] = len(alert_ids)
    tenant_db.clusters.insert_one(cluster)
    tenant_db.alerts.insert_many(
        [
            {
                "alert_id": alert_id,
                "tenant_id": "tenant-1",
                "normalized_payload": (
                    {"host.hostname": f"WIN-{index}"}
                    if index % 2 == 0
                    else {"host": {"hostname": f"WIN-{index}"}}
                ),
                "created_at": datetime.now(timezone.utc),
            }
            for index, alert_id in enumerate(alert_ids)
        ]
    )

    detail = ClusterService.get_cluster("tenant-1", "cluster-1")

    assert detail.alert_count == 250
    assert detail.affected_host_count == 250


def test_status_assignment_notes_and_verdict_rules(tenant_db):
    tenant_db.clusters.insert_one(_cluster())
    investigating = ClusterService.update_status(
        "tenant-1", "cluster-1", "UNDER_INVESTIGATION"
    )
    assert investigating.status == "UNDER_INVESTIGATION"
    assigned = ClusterService.assign("tenant-1", "cluster-1", "analyst-1")
    assert assigned.assigned_to == "analyst-1"
    noted = ClusterService.add_note(
        "tenant-1", "cluster-1", "analyst@example.com", "Investigating"
    )
    assert noted.analyst_notes[0]["note"] == "Investigating"
    with pytest.raises(HTTPException) as error:
        ClusterService.set_verdict("tenant-1", "cluster-1", "TRUE_POSITIVE")
    assert error.value.status_code == 422
    closed = ClusterService.update_status("tenant-1", "cluster-1", "CLOSED")
    assert closed.closed_at is not None
    verdict = ClusterService.set_verdict(
        "tenant-1", "cluster-1", "TRUE_POSITIVE"
    )
    assert verdict.verdict == "TRUE_POSITIVE"


def test_summary_history_is_ordered_and_empty_before_analysis(tenant_db):
    tenant_db.clusters.insert_one(_cluster())
    assert ClusterService.summary_history("tenant-1", "cluster-1").items == []
    tenant_db.clusters.update_one(
        {"cluster_id": "cluster-1"},
        {
            "$set": {
                "summary": {
                    "version": 2,
                    "headline": "Current",
                    "history": [{"version": 1, "headline": "First"}],
                }
            }
        },
    )
    history = ClusterService.summary_history("tenant-1", "cluster-1")
    assert [item["version"] for item in history.items] == [1, 2]
