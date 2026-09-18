from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import time

from app.core.security import create_access_token
from app.models.tenant import Tenant
from app.schemas.dashboard import (
    DashboardActivity,
    DashboardActivityBucket,
    DashboardCoverage,
    DashboardKpis,
    PlatformDashboardSummary,
    TenantDashboardSummary,
)
from app.services.dashboard_service import PlatformDashboardService
from tests.test_tenants import client, get_auth_headers


def _tenant(index: int, status: str = "ACTIVE") -> Tenant:
    tenant = Tenant(
        tenant_id=f"tenant-{index}",
        name=f"tenant-{index}",
        display_name=f"Tenant {index}",
        db_name=f"tenant_db_{index}",
        status=status,
    )
    tenant.save()
    return tenant


def _empty_summary(now: datetime | None = None) -> PlatformDashboardSummary:
    now = now or datetime.now(timezone.utc)
    bucket = DashboardActivityBucket(
        start_at=now - timedelta(hours=1),
        end_at=now,
    )
    return PlatformDashboardSummary(
        generated_at=now,
        cache_expires_at=now + timedelta(seconds=30),
        coverage=DashboardCoverage(
            eligible_tenants=0,
            successful_tenants=0,
            failed_tenants=0,
            partial=False,
            failure_details=[],
        ),
        kpis=DashboardKpis(),
        activity=DashboardActivity(
            daily=[bucket], weekly=[bucket], monthly=[bucket]
        ),
    )


def _aggregate_result(tenant: Tenant, windows, value: int = 1):
    activity = {
        name: [{"_id": ranges[0][0], "count": value}]
        for name, ranges in windows.items()
    }
    return {
        "tenant_id": tenant.tenant_id,
        "total_alerts": value,
        "critical_alerts": value,
        "escalated_alerts": value,
        "open_alerts": value,
        "active_clusters": value,
        "resolved_clusters": value,
        "alert_activity": activity,
        "dead_letter_activity": activity,
        "recent_critical": None,
        "recent_cluster": None,
    }


def _empty_tenant_summary(now: datetime | None = None) -> TenantDashboardSummary:
    platform = _empty_summary(now)
    return TenantDashboardSummary(
        generated_at=platform.generated_at,
        cache_expires_at=platform.cache_expires_at,
        kpis=platform.kpis,
        activity=platform.activity,
    )


def setup_function():
    Tenant.drop_collection()
    PlatformDashboardService.reset_cache()


def test_dashboard_requires_platform_admin(monkeypatch):
    monkeypatch.setattr(
        PlatformDashboardService,
        "get_summary",
        classmethod(lambda cls: _empty_summary()),
    )
    assert client.get("/api/v1/admin/dashboard/summary").status_code in (401, 403)

    token = create_access_token(
        user_id="tenant-user",
        email="tenant@example.com",
        role="TENANT_ADMIN",
        tenant_id="tenant-1",
    )
    response = client.get(
        "/api/v1/admin/dashboard/summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403

    response = client.get(
        "/api/v1/admin/dashboard/summary", headers=get_auth_headers()
    )
    assert response.status_code == 200


def test_tenant_dashboard_enforces_tenant_isolation(monkeypatch):
    _tenant(1)
    monkeypatch.setattr(
        PlatformDashboardService,
        "get_tenant_summary",
        classmethod(lambda cls, tenant_id: _empty_tenant_summary()),
    )
    token = create_access_token(
        user_id="tenant-user",
        email="tenant@example.com",
        role="TENANT_OPERATOR",
        tenant_id="tenant-1",
    )
    headers = {"Authorization": f"Bearer {token}"}

    assert client.get(
        "/api/v1/tenants/tenant-1/dashboard/summary", headers=headers
    ).status_code == 200
    assert client.get(
        "/api/v1/tenants/tenant-2/dashboard/summary", headers=headers
    ).status_code == 403


def test_windows_are_contiguous_and_have_expected_sizes():
    now = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
    windows = PlatformDashboardService._windows(now)
    assert [len(windows[name]) for name in ("daily", "weekly", "monthly")] == [
        8,
        7,
        10,
    ]
    assert windows["daily"][0][0] == now - timedelta(hours=24)
    assert windows["weekly"][0][0] == now - timedelta(days=7)
    assert windows["monthly"][0][0] == now - timedelta(days=30)
    assert all(
        current[1] == following[0]
        for ranges in windows.values()
        for current, following in zip(ranges, ranges[1:])
    )


def test_summary_includes_more_than_200_tenants_and_excludes_deleted(monkeypatch):
    for index in range(205):
        _tenant(index)
    _tenant(205, status="SUSPENDED")
    _tenant(206, status="DELETED")

    monkeypatch.setattr(
        PlatformDashboardService,
        "_aggregate_tenant",
        classmethod(lambda cls, tenant, windows: _aggregate_result(tenant, windows)),
    )
    monkeypatch.setattr(
        PlatformDashboardService,
        "_aggregate_platform_dead_letters",
        classmethod(lambda cls, windows: {}),
    )

    summary = PlatformDashboardService._build_summary(
        datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
    )
    assert summary.coverage.eligible_tenants == 206
    assert summary.coverage.successful_tenants == 206
    assert summary.kpis.total_alerts == 206
    assert summary.kpis.critical_alerts == 206
    assert summary.kpis.open_alerts == 206
    assert summary.kpis.active_clusters == 206
    assert summary.kpis.resolved_incidents == 206
    assert summary.kpis.resolved_clusters == 206


def test_summary_reports_partial_sources_and_platform_dead_letters(monkeypatch):
    _tenant(1)
    _tenant(2, status="SUSPENDED")

    def aggregate(cls, tenant, windows):
        if tenant.tenant_id == "tenant-2":
            raise RuntimeError("tenant unavailable")
        return _aggregate_result(tenant, windows, value=2)

    def platform_dead_letters(cls, windows):
        return {
            name: [{"_id": ranges[0][0], "count": 3}]
            for name, ranges in windows.items()
        }

    monkeypatch.setattr(
        PlatformDashboardService, "_aggregate_tenant", classmethod(aggregate)
    )
    monkeypatch.setattr(
        PlatformDashboardService,
        "_aggregate_platform_dead_letters",
        classmethod(platform_dead_letters),
    )

    summary = PlatformDashboardService._build_summary(
        datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
    )
    assert summary.coverage.partial is True
    assert summary.coverage.failed_tenants == 1
    assert summary.coverage.failed_sources == ["tenant:tenant-2"]
    assert summary.coverage.failure_details == [
        {
            "source": "tenant:tenant-2",
            "error_type": "RuntimeError",
        }
    ]
    assert summary.activity.daily[0].alerts == 2
    assert summary.activity.daily[0].dead_letters == 5


def test_cache_is_reused_and_concurrent_refresh_is_single_flight(monkeypatch):
    calls = 0

    def build(cls, generated_at):
        nonlocal calls
        calls += 1
        time.sleep(0.05)
        return _empty_summary(generated_at)

    monkeypatch.setattr(
        PlatformDashboardService, "_build_summary", classmethod(build)
    )
    with ThreadPoolExecutor(max_workers=4) as executor:
        summaries = list(executor.map(lambda _: PlatformDashboardService.get_summary(), range(4)))
    assert calls == 1
    assert len(summaries) == 4

    PlatformDashboardService._cache_deadline = 0
    PlatformDashboardService.get_summary()
    assert calls == 2
