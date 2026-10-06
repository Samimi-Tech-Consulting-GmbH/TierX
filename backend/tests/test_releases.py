import asyncio
import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.v1 import releases
from app.api.dependencies.auth import get_current_user
from app.schemas.user import AuthenticatedUser, UserRole
from app.services.release_service import ReleaseService


def payload(tag="v0.2.1", **extra):
    return {"tag_name": tag, "draft": False, "prerelease": False, **extra}


@pytest.mark.asyncio
async def test_cache_single_flight_and_expiry():
    calls = 0
    clock = [0]
    async def fetch():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return payload()
    service = ReleaseService(fetch, clock=lambda: clock[0])
    results = await asyncio.gather(*(service.latest() for _ in range(8)))
    assert calls == 1
    assert all(item.latest_version == "0.2.1" for item in results)
    assert results[0].release_url.endswith("/v0.2.1")
    await service.latest()
    assert calls == 1
    clock[0] = 3600
    await service.latest()
    assert calls == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [
    {}, [], payload("banana"), payload("v0.2.1-rc.1"),
    payload(draft=True), payload(prerelease=True), payload("v00.2.1"),
])
async def test_invalid_releases_are_unknown(value):
    async def fetch(): return value
    assert (await ReleaseService(fetch).latest()).status == "UNAVAILABLE"


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [
    httpx.ReadTimeout("timeout"),
    httpx.HTTPStatusError("rate limit", request=httpx.Request("GET", "https://api.github.com"), response=httpx.Response(429)),
    ValueError("malformed JSON"),
    TimeoutError(),
])
async def test_safe_cached_failure(error):
    calls = 0
    async def fetch():
        nonlocal calls
        calls += 1
        raise error
    service = ReleaseService(fetch)
    result = await service.latest()
    assert result.status == "UNAVAILABLE"
    assert result.latest_version is None
    assert result.checked_at is not None
    await service.latest()
    assert calls == 1


@pytest.mark.asyncio
async def test_disabled_never_contacts_github(monkeypatch):
    monkeypatch.setenv("TIERX_UPDATE_CHECK_ENABLED", "false")
    async def fetch(): pytest.fail("disabled update check made a network request")
    result = await ReleaseService(fetch).latest()
    assert not result.enabled
    assert result.status == "DISABLED"


def test_endpoint_authentication_and_all_roles(monkeypatch):
    app = FastAPI()
    app.include_router(releases.router, prefix="/api/v1")
    async def fetch(): return payload()
    monkeypatch.setattr(releases, "release_service", ReleaseService(fetch))
    with TestClient(app) as client:
        assert client.get("/api/v1/releases/latest").status_code in (401, 403)
        for role in UserRole:
            app.dependency_overrides[get_current_user] = lambda role=role: AuthenticatedUser(
                user_id="test-user", email="test@example.com", role=role)
            response = client.get("/api/v1/releases/latest")
            assert response.status_code == 200
            assert response.json()["latest_version"] == "0.2.1"
