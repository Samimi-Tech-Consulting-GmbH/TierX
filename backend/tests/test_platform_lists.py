from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import mongomock
import mongoengine
import pytest
from fastapi.testclient import TestClient

from main import app
from app.core.alert_metrics import severity_from_alert
from app.core.security import create_access_token
from app.models.tenant import Tenant
from app.services.alert_type_schema_service import AlertTypeSchemaService
from app.services.platform_list_service import PlatformListService
from app.services.playbook_service import PlaybookService


client = TestClient(app)

mongoengine.disconnect_all()
mongoengine.connect(
    "soc_mind_platform",
    host="mongodb://unit-test.invalid/",
    mongo_client_class=mongomock.MongoClient,
    alias="default",
    uuidRepresentation="standard",
)


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


def _headers(role: str = "PLATFORM_ADMIN", tenant_id: str | None = None) -> dict:
    token = create_access_token(
        user_id="test-user",
        email="test@example.com",
        role=role,
        tenant_id=tenant_id,
    )
    return {"Authorization": f"Bearer {token}"}


def _tenant(name: str, status: str = "ACTIVE") -> Tenant:
    return Tenant(
        tenant_id=str(uuid4()),
        name=name,
        display_name=f"{name.title()} Tenant",
        db_name=f"soc_mind_tenant_{name}",
        status=status,
        created_by="test@example.com",
    ).save()


def _db(tenant: Tenant):
    return MockDatabaseManager.get_tenant_database(str(tenant.db_name))


def _alert(tenant: Tenant, alert_id: str, created_at: datetime, **values):
    row = {
        "alert_id": alert_id,
        "tenant_id": tenant.tenant_id,
        "alert_type": "endpoint.malware",
        "source_system": "splunk",
        "fingerprint": f"fp-{alert_id}",
        "created_at": created_at,
        "updated_at": created_at,
    }
    row.update(values)
    _db(tenant).alerts.insert_one(row)


def _cluster(tenant: Tenant, cluster_id: str, created_at: datetime, **values):
    row = {
        "cluster_id": cluster_id,
        "tenant_id": tenant.tenant_id,
        "status": "OPEN",
        "clustering_status": "CORRELATED",
        "alert_count": 2,
        "severity": {"max": 4},
        "first_seen": created_at,
        "last_seen": created_at,
        "assigned_to": None,
        "is_open_for_grouping": True,
        "summary": None,
        "correlation_basis": {"mitre_techniques": []},
        "created_at": created_at,
    }
    row.update(values)
    _db(tenant).clusters.insert_one(row)


def _schema(tenant: Tenant, schema_id: str, updated_at: datetime, **values):
    row = {
        "schema_id": schema_id,
        "tenant_id": tenant.tenant_id,
        "alert_type": "endpoint.malware",
        "version": "1.0.0",
        "description": "Endpoint schema",
        "fields": [],
        "critical_fields": ["host.hostname"],
        "field_mapping": {"host.hostname": "result.host"},
        "is_active": True,
        "severity": "4",
        "created_by": "test@example.com",
        "created_at": updated_at,
        "updated_at": updated_at,
    }
    row.update(values)
    _db(tenant).alert_type_schemas.insert_one(row)


def _playbook(tenant: Tenant, playbook_id: str, updated_at: datetime, **values):
    row = {
        "playbook_id": playbook_id,
        "version": 1,
        "tenant_id": tenant.tenant_id,
        "playbook_name": "Endpoint triage",
        "actions": [],
        "prompt": "Analyze endpoint evidence",
        "description": "Endpoint analysis",
        "alert_types": ["endpoint.malware"],
        "is_active": True,
        "is_system": False,
        "created_by": "test@example.com",
        "created_at": updated_at,
        "updated_at": updated_at,
    }
    row.update(values)
    _db(tenant).playbooks.insert_one(row)


@pytest.fixture(autouse=True)
def database(monkeypatch):
    import app.db.mongodb
    import app.services.alert_type_schema_service
    import app.services.platform_list_service
    import app.services.playbook_service
    import app.services.tenant_service

    for module in (
        app.db.mongodb,
        app.services.alert_type_schema_service,
        app.services.platform_list_service,
        app.services.playbook_service,
        app.services.tenant_service,
    ):
        monkeypatch.setattr(module, "DatabaseManager", MockDatabaseManager)

    for tenant in Tenant.objects:
        db = _db(tenant)
        for collection_name in db.list_collection_names():
            db[collection_name].drop()
    Tenant.drop_collection()
    yield
    for tenant in Tenant.objects:
        db = _db(tenant)
        for collection_name in db.list_collection_names():
            db[collection_name].drop()
    Tenant.drop_collection()


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/admin/alerts",
        "/api/v1/admin/clusters",
        "/api/v1/admin/alert-type-schemas",
        "/api/v1/admin/playbooks",
    ],
)
def test_platform_lists_require_platform_admin(path):
    assert client.get(path).status_code in {401, 403}
    assert client.get(
        path, headers=_headers("TENANT_ADMIN", "tenant-1")
    ).status_code == 403
    response = client.get(path, headers=_headers())
    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "skip": 0, "limit": 25}


@pytest.mark.parametrize(
    "path",
    ["/api/v1/admin/alerts/stats", "/api/v1/admin/playbooks/stats"],
)
def test_platform_stats_require_platform_admin(path):
    assert client.get(path).status_code in {401, 403}
    assert client.get(
        path, headers=_headers("TENANT_ADMIN", "tenant-1")
    ).status_code == 403
    assert client.get(path, headers=_headers()).status_code == 200


def test_alerts_active_scope_global_paging_sort_and_exact_priority():
    now = datetime.now(timezone.utc)
    alpha = _tenant("alpha")
    beta = _tenant("beta")
    suspended = _tenant("suspended", "SUSPENDED")
    _alert(alpha, "alert-old", now - timedelta(hours=2))
    _alert(beta, "alert-new", now)
    _alert(suspended, "alert-hidden", now + timedelta(hours=1))

    page = client.get(
        "/api/v1/admin/alerts?skip=1&limit=1", headers=_headers()
    )
    assert page.status_code == 200
    body = page.json()
    assert body["total"] == 2
    assert body["items"][0]["alert_id"] == "alert-old"
    assert body["items"][0]["tenant_name"] == alpha.display_name

    _alert(
        beta,
        "alert-exact",
        now - timedelta(days=1),
        source_system="ordinary",
    )
    _alert(alpha, "newer-substring", now + timedelta(hours=1), source_system="alert-exact")
    exact = client.get(
        "/api/v1/admin/alerts?q=alert-exact", headers=_headers()
    )
    assert exact.status_code == 200
    assert exact.json()["items"][0]["alert_id"] == "alert-exact"


def test_alert_search_fields_and_since_hours():
    now = datetime.now(timezone.utc)
    tenant = _tenant("search")
    _alert(tenant, "recent", now, fingerprint="Needle-Fingerprint")
    _alert(
        tenant,
        "old",
        now - timedelta(hours=48),
        alert_type="Needle-Type",
    )
    response = client.get(
        "/api/v1/admin/alerts?q=needle&since_hours=24", headers=_headers()
    )
    assert response.status_code == 200
    assert [item["alert_id"] for item in response.json()["items"]] == ["recent"]


def test_alert_stats_match_list_search_period_and_canonical_severity(monkeypatch):
    import app.services.platform_list_service
    import app.services.tenant_service

    def mongomock_stats(collection, query):
        counts = {
            "CRITICAL": 0,
            "HIGH": 0,
            "MEDIUM": 0,
            "LOW": 0,
            "UNKNOWN": 0,
        }
        rows = list(collection.find(query))
        for row in rows:
            counts[severity_from_alert(row)] += 1
        return {"filtered_total": len(rows), "severity": counts}

    monkeypatch.setattr(
        app.services.platform_list_service,
        "aggregate_alert_stats",
        mongomock_stats,
    )
    monkeypatch.setattr(
        app.services.tenant_service,
        "aggregate_alert_stats",
        mongomock_stats,
    )
    now = datetime.now(timezone.utc)
    alpha = _tenant("stats-alpha")
    beta = _tenant("stats-beta")
    _alert(
        alpha,
        "needle-critical",
        now,
        normalized_payload={"event.severity": "5"},
    )
    _alert(
        beta,
        "needle-high",
        now,
        normalized_payload={"event": {"severity": "high"}},
    )
    _alert(
        alpha,
        "needle-old",
        now - timedelta(hours=48),
        severity="LOW",
    )
    _alert(alpha, "unrelated", now, normalized_payload={})

    params = {"q": "needle", "since_hours": 24}
    listed = client.get(
        "/api/v1/admin/alerts", params=params, headers=_headers()
    )
    stats = client.get(
        "/api/v1/admin/alerts/stats", params=params, headers=_headers()
    )
    tenant_stats = client.get(
        f"/api/v1/tenants/{alpha.tenant_id}/alerts/stats",
        params=params,
        headers=_headers("TENANT_OPERATOR", alpha.tenant_id),
    )

    assert listed.status_code == 200
    assert stats.status_code == 200
    assert stats.json() == {
        "filtered_total": listed.json()["total"],
        "severity": {
            "CRITICAL": 1,
            "HIGH": 1,
            "MEDIUM": 0,
            "LOW": 0,
            "UNKNOWN": 0,
        },
    }
    assert tenant_stats.status_code == 200
    assert tenant_stats.json()["filtered_total"] == 1
    assert tenant_stats.json()["severity"]["CRITICAL"] == 1


def test_platform_playbook_stats_aggregate_latest_revisions_across_tenants():
    now = datetime.now(timezone.utc)
    alpha = _tenant("playbook-stats-alpha")
    beta = _tenant("playbook-stats-beta")
    _playbook(alpha, "alpha-one", now, alert_types=["TYPE.A"])
    _playbook(
        alpha,
        "alpha-one",
        now + timedelta(seconds=1),
        version=2,
        is_active=False,
        is_system=True,
        alert_types=["TYPE.B"],
    )
    _playbook(beta, "beta-one", now, alert_types=["TYPE.B", "TYPE.C"])

    response = client.get("/api/v1/admin/playbooks/stats", headers=_headers())

    assert response.status_code == 200
    assert response.json() == {
        "total_playbooks": 2,
        "active_playbooks": 1,
        "system_playbooks": 1,
        "covered_alert_types": 2,
    }


def test_alert_totals_include_more_than_two_hundred_active_tenants():
    now = datetime.now(timezone.utc)
    for index in range(205):
        tenant = _tenant(f"many-{index}")
        _alert(tenant, f"alert-{index:03d}", now - timedelta(seconds=index))
    response = client.get(
        "/api/v1/admin/alerts?limit=200", headers=_headers()
    )
    assert response.status_code == 200
    assert response.json()["total"] == 205
    assert len(response.json()["items"]) == 200


def test_cluster_search_ignores_status_and_matches_analysis_and_mitre():
    now = datetime.now(timezone.utc)
    tenant = _tenant("clusters")
    _cluster(
        tenant,
        "cluster-closed",
        now,
        status="CLOSED",
        summary={"headline": "Credential theft", "narrative": "PowerShell"},
        correlation_basis={"mitre_techniques": ["T1059.001"]},
    )
    for query in ("cluster-closed", "credential", "powershell", "t1059.001"):
        response = client.get(
            f"/api/v1/admin/clusters?q={query}&status=OPEN",
            headers=_headers(),
        )
        assert response.status_code == 200
        assert response.json()["total"] == 1


def test_schema_and_playbook_search_ignore_active_filter():
    now = datetime.now(timezone.utc)
    tenant = _tenant("settings")
    _schema(
        tenant,
        "schema-draft",
        now,
        alert_type="Draft.Special",
        is_active=False,
    )
    _playbook(
        tenant,
        "playbook-inactive",
        now,
        playbook_name="Rare Investigation",
        alert_types=["Draft.Special"],
        is_active=False,
    )
    schema = client.get(
        "/api/v1/admin/alert-type-schemas?q=schema-draft&is_active=true",
        headers=_headers(),
    )
    assert schema.status_code == 200
    assert schema.json()["items"][0]["is_active"] is False
    for query in ("rare", "draft.special", "playbook-inactive"):
        playbook = client.get(
            f"/api/v1/admin/playbooks?q={query}&is_active=true",
            headers=_headers(),
        )
        assert playbook.status_code == 200
        assert playbook.json()["items"][0]["is_active"] is False


def test_exact_ids_rank_first_for_clusters_schemas_and_playbooks():
    now = datetime.now(timezone.utc)
    tenant = _tenant("exact-ranking")
    _cluster(tenant, "cluster-exact", now - timedelta(hours=1))
    _cluster(
        tenant,
        "cluster-newer",
        now,
        summary={"headline": "cluster-exact related"},
    )
    _schema(tenant, "schema-exact", now - timedelta(hours=1))
    _schema(
        tenant,
        "schema-newer",
        now,
        version="2.0.0",
        alert_type="schema-exact related",
    )
    _playbook(tenant, "playbook-exact", now - timedelta(hours=1))
    _playbook(
        tenant,
        "playbook-newer",
        now,
        playbook_name="playbook-exact related",
    )
    cases = (
        ("/api/v1/admin/clusters?q=cluster-exact", "cluster_id", "cluster-exact"),
        (
            "/api/v1/admin/alert-type-schemas?q=schema-exact",
            "schema_id",
            "schema-exact",
        ),
        (
            "/api/v1/admin/playbooks?q=playbook-exact",
            "playbook_id",
            "playbook-exact",
        ),
    )
    for path, field, expected in cases:
        response = client.get(path, headers=_headers())
        assert response.status_code == 200
        assert response.json()["items"][0][field] == expected


def test_search_escapes_regex_metacharacters():
    now = datetime.now(timezone.utc)
    tenant = _tenant("escaped")
    _alert(tenant, "literal", now, source_system="collector.*name")
    _alert(tenant, "ordinary", now, source_system="collector-any-name")
    response = client.get(
        "/api/v1/admin/alerts", params={"q": ".*"}, headers=_headers()
    )
    assert response.status_code == 200
    assert [item["alert_id"] for item in response.json()["items"]] == ["literal"]


def test_status_and_active_filters_apply_without_search():
    now = datetime.now(timezone.utc)
    tenant = _tenant("filters")
    _cluster(tenant, "open-cluster", now)
    _cluster(tenant, "closed-cluster", now, status="CLOSED")
    _schema(tenant, "active-schema", now)
    _schema(
        tenant,
        "draft-schema",
        now - timedelta(seconds=1),
        version="2.0.0",
        is_active=False,
    )
    _playbook(tenant, "active-playbook", now)
    _playbook(
        tenant,
        "inactive-playbook",
        now - timedelta(seconds=1),
        is_active=False,
    )
    clusters = client.get(
        "/api/v1/admin/clusters?status=CLOSED", headers=_headers()
    )
    schemas = client.get(
        "/api/v1/admin/alert-type-schemas?is_active=false", headers=_headers()
    )
    playbooks = client.get(
        "/api/v1/admin/playbooks?is_active=false", headers=_headers()
    )
    assert [item["cluster_id"] for item in clusters.json()["items"]] == [
        "closed-cluster"
    ]
    assert [item["schema_id"] for item in schemas.json()["items"]] == [
        "draft-schema"
    ]
    assert [item["playbook_id"] for item in playbooks.json()["items"]] == [
        "inactive-playbook"
    ]


def test_active_tenant_database_failure_returns_503(monkeypatch):
    good = _tenant("good")
    bad = _tenant("bad")
    _alert(good, "alert-good", datetime.now(timezone.utc))
    original = PlatformListService._database

    def failing_database(tenant):
        if tenant.tenant_id == bad.tenant_id:
            raise RuntimeError("database unavailable with private details")
        return original(tenant)

    monkeypatch.setattr(
        PlatformListService, "_database", staticmethod(failing_database)
    )
    response = client.get("/api/v1/admin/alerts", headers=_headers())
    assert response.status_code == 503
    assert response.json()["detail"] == (
        "One or more active tenant databases could not be queried"
    )
    stats = client.get("/api/v1/admin/alerts/stats", headers=_headers())
    assert stats.status_code == 503
    assert "tenant database could not be queried" in stats.json()["detail"]

    original_stats = PlaybookService.stats_values

    def failing_playbook_stats(tenant_id):
        if tenant_id == bad.tenant_id:
            raise RuntimeError("database unavailable with private details")
        return original_stats(tenant_id)

    monkeypatch.setattr(PlaybookService, "stats_values", failing_playbook_stats)
    playbooks = client.get("/api/v1/admin/playbooks/stats", headers=_headers())
    assert playbooks.status_code == 503
    assert "tenant database could not be queried" in playbooks.json()["detail"]


def test_per_tenant_alert_and_cluster_search():
    now = datetime.now(timezone.utc)
    tenant = _tenant("scoped")
    _alert(tenant, "alert-match", now, source_system="CrowdStrike")
    _alert(tenant, "alert-other", now - timedelta(minutes=1))
    _cluster(
        tenant,
        "cluster-match",
        now,
        status="CLOSED",
        summary={"headline": "Searchable cluster"},
    )
    headers = _headers("TENANT_OPERATOR", tenant.tenant_id)
    alerts = client.get(
        f"/api/v1/tenants/{tenant.tenant_id}/alerts?q=crowd",
        headers=headers,
    )
    assert alerts.status_code == 200
    assert [item["alert_id"] for item in alerts.json()["items"]] == ["alert-match"]
    admin_alerts = client.get(
        f"/api/v1/admin/tenants/{tenant.tenant_id}/alerts?q=alert-match",
        headers=_headers(),
    )
    assert admin_alerts.status_code == 200
    assert admin_alerts.json()["items"][0]["alert_id"] == "alert-match"
    clusters = client.get(
        f"/api/v1/tenants/{tenant.tenant_id}/clusters?q=searchable&status=OPEN",
        headers=headers,
    )
    assert clusters.status_code == 200
    assert clusters.json()["items"][0]["cluster_id"] == "cluster-match"


def test_raw_schema_and_playbook_services_do_not_leak_between_tenants():
    now = datetime.now(timezone.utc)
    alpha = _tenant("concurrent-alpha")
    beta = _tenant("concurrent-beta")
    _schema(alpha, "schema-alpha", now, alert_type="alpha.type")
    _schema(beta, "schema-beta", now, alert_type="beta.type")
    _playbook(alpha, "playbook-alpha", now, playbook_name="Alpha")
    _playbook(beta, "playbook-beta", now, playbook_name="Beta")

    def read(tenant):
        schemas = AlertTypeSchemaService.list_schemas(tenant.tenant_id)
        playbooks = PlaybookService.list_playbooks(tenant.tenant_id)
        return (
            {item.tenant_id for item in schemas.items},
            {item.tenant_id for item in playbooks},
        )

    tenants = [alpha, beta] * 20
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(read, tenants))
    for tenant, (schema_tenants, playbook_tenants) in zip(tenants, results):
        assert schema_tenants == {tenant.tenant_id}
        assert playbook_tenants == {tenant.tenant_id}


def test_platform_list_indexes_are_idempotent():
    tenant = _tenant("indexes")
    PlatformListService.ensure_indexes()
    PlatformListService.ensure_indexes()
    db = _db(tenant)
    alert_keys = {
        tuple(index["key"].items()) for index in db.alerts.list_indexes()
    }
    cluster_keys = {
        tuple(index["key"].items()) for index in db.clusters.list_indexes()
    }
    schema_keys = {
        tuple(index["key"].items())
        for index in db.alert_type_schemas.list_indexes()
    }
    playbook_keys = {
        tuple(index["key"].items()) for index in db.playbooks.list_indexes()
    }
    assert (("alert_id", 1),) in alert_keys
    assert (("created_at", -1), ("alert_id", 1)) in alert_keys
    assert (("cluster_id", 1),) in cluster_keys
    assert (("status", 1), ("created_at", -1)) in cluster_keys
    assert (("is_active", 1), ("updated_at", -1)) in schema_keys
    assert (("is_active", 1), ("updated_at", -1)) in playbook_keys
