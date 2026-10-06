"""First-run installation uses only synthetic identities and isolated storage."""
import asyncio
import hashlib
from concurrent.futures import ThreadPoolExecutor

import httpx
import mongomock
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from main import app
from app.core.security import create_access_token
from app.services.platform_configuration_service import PlatformConfigurationService as Service
from tierx_runtime import COLLECTION, IDENTITY, DEFAULTS, effective, validate


@pytest.fixture
def db(monkeypatch):
    database = mongomock.MongoClient(tz_aware=True).platform
    database.users.create_index("email", unique=True)
    database.users.create_index("user_id", unique=True)
    monkeypatch.setattr(Service, "db", staticmethod(lambda: database))
    for name in (*DEFAULTS, "platform_admin_email", "platform_admin_password",
                 "bootstrap_configured", "installation_enabled", "installation_token"):
        for prefix in ("", "TIERX_", "SOC_MIND_"):
            monkeypatch.delenv(prefix + name.upper(), raising=False)
    monkeypatch.setenv("TIERX_INSTALLATION_TOKEN", "synthetic-one-time-token")
    monkeypatch.setattr(app.state, "configuration_ready", False, raising=False)
    return database


def complete(db, **values):
    Service.initialize()
    Service.reserve("admin@example.com", "synthetic-password-only", {**DEFAULTS, **values})


def auth(role="PLATFORM_ADMIN"):
    return {"Authorization": "Bearer " + create_access_token(
        "synthetic-user", "admin@example.com", role, "synthetic-tenant")}


def test_token_hash_consumption_and_permanent_closure(db, monkeypatch):
    Service.initialize()
    doc = Service.document()
    assert doc["token_hash"] == hashlib.sha256(b"synthetic-one-time-token").hexdigest()
    assert "synthetic-one-time-token" not in str(doc)
    with pytest.raises(HTTPException) as exc:
        Service.authorize_setup("wrong")
    assert exc.value.status_code == 403
    Service.authorize_setup("synthetic-one-time-token")
    Service.reserve("admin@example.com", "synthetic-password-only", DEFAULTS)
    assert "token_hash" not in Service.document()
    monkeypatch.setenv("TIERX_INSTALLATION_ENABLED", "true")
    with pytest.raises(HTTPException) as exc:
        Service.authorize_setup("synthetic-one-time-token")
    assert exc.value.status_code == 404
    assert db.users.count_documents({}) == 1


def test_generated_token_is_logged_only_once(db, monkeypatch, caplog):
    monkeypatch.delenv("TIERX_INSTALLATION_TOKEN")
    Service.initialize()
    first = caplog.text
    assert "one-time installation token:" in first
    Service.initialize()
    assert caplog.text == first


def test_disabled_installation_and_incomplete_bootstrap(db, monkeypatch):
    monkeypatch.setenv("TIERX_INSTALLATION_ENABLED", "false")
    Service.initialize()
    with pytest.raises(HTTPException) as exc:
        Service.authorize_setup("synthetic-one-time-token")
    assert exc.value.status_code == 404
    monkeypatch.setenv("TIERX_BOOTSTRAP_CONFIGURED", "true")
    with pytest.raises(RuntimeError, match="TIERX_PLATFORM_ADMIN_EMAIL.*TIERX_PLATFORM_ADMIN_PASSWORD.*TIERX_PUBLIC_URL"):
        Service.initialize()
    assert db.users.count_documents({}) == 0
    assert Service.document()["state"] == "PENDING"


def test_environment_only_bootstrap_and_restart(db, monkeypatch):
    for key, value in {"BOOTSTRAP_CONFIGURED": "true", "INSTALLATION_ENABLED": "false",
                       "PLATFORM_ADMIN_EMAIL": "admin@example.com",
                       "PLATFORM_ADMIN_PASSWORD": "synthetic-password-only",
                       "PUBLIC_URL": "https://tierx.example.com", "OLLAMA_URL": "http://ollama:11434",
                       "OLLAMA_MODEL": "synthetic-model"}.items():
        monkeypatch.setenv("TIERX_" + key, value)
    Service.initialize()
    original = db.users.find_one({})
    monkeypatch.setenv("TIERX_PLATFORM_ADMIN_PASSWORD", "different-password-only")
    Service.initialize()
    assert Service.document()["state"] == "INSTALLED"
    assert db.users.find_one({}) == original


def test_existing_admin_is_not_reset_or_reopened(db):
    db.users.insert_one({"user_id": "legacy", "email": "legacy@example.com",
                         "role": "PLATFORM_ADMIN", "hashed_password": "unchanged"})
    Service.initialize()
    assert Service.document()["state"] == "INSTALLED"
    assert db.users.find_one({})["hashed_password"] == "unchanged"


def test_interrupted_completion_recovers_reserved_identity(db, monkeypatch):
    Service.initialize()
    original = Service.finish_pending
    monkeypatch.setattr(Service, "finish_pending", lambda doc: (_ for _ in ()).throw(RuntimeError("synthetic crash")))
    with pytest.raises(RuntimeError):
        Service.reserve("admin@example.com", "synthetic-password-only", DEFAULTS)
    reserved = Service.document()["pending_admin"]["user_id"]
    monkeypatch.setattr(Service, "finish_pending", original)
    Service.initialize()
    Service.initialize()
    assert db.users.count_documents({}) == 1
    assert db.users.find_one({})["user_id"] == reserved
    assert Service.document()["state"] == "INSTALLED"


def test_concurrent_completion_creates_one_admin(db):
    Service.initialize()
    def submit(index):
        try:
            Service.reserve(f"admin{index}@example.com", "synthetic-password-only", DEFAULTS)
            return 200
        except HTTPException as exc:
            return exc.status_code
    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(submit, range(4)))
    assert outcomes.count(200) == 1
    assert outcomes.count(409) == 3
    assert db.users.count_documents({}) == 1


@pytest.mark.asyncio
async def test_revision_conflict_and_environment_shadow_value(db, monkeypatch):
    complete(db)
    monkeypatch.setenv("TIERX_OLLAMA_MODEL", "environment-model")
    values = Service.read()["values"]
    assert "ollama_model" in Service.read()["locked_fields"]
    values["public_url"] = "https://tierx.example.com"
    result = await Service.update(values, 1, "admin@example.com")
    assert result["revision"] == 2
    assert result["values"]["ollama_model"] == "environment-model"
    assert Service.document()["values"]["ollama_model"] == DEFAULTS["ollama_model"]
    with pytest.raises(HTTPException) as exc:
        await Service.update(values, 1, "admin@example.com")
    assert exc.value.status_code == 409
    monkeypatch.delenv("TIERX_OLLAMA_MODEL")
    assert Service.read()["values"]["ollama_model"] == DEFAULTS["ollama_model"]


@pytest.mark.asyncio
async def test_analysis_dependency_validation_and_failed_preflight(db, monkeypatch):
    complete(db)
    async def fail(values):
        raise HTTPException(422, "Synthetic model unavailable")
    monkeypatch.setattr(Service, "test", fail)
    with pytest.raises(HTTPException):
        await Service.update({"llm_analysis_enabled": True}, 1, "admin@example.com")
    assert Service.document()["revision"] == 1
    async def passed(values):
        assert values["correlation_enabled"]
    monkeypatch.setattr(Service, "test", passed)
    await Service.update({"llm_analysis_enabled": True}, 1, "admin@example.com")
    with pytest.raises(ValueError, match="requires correlation"):
        await Service.update({"correlation_enabled": False}, 2, "admin@example.com")


@pytest.mark.asyncio
async def test_concurrent_settings_updates_only_one_revision_wins(db):
    complete(db)
    outcomes = await asyncio.gather(
        Service.update({"ollama_model": "first-model"}, 1, "first@example.com"),
        Service.update({"ollama_model": "second-model"}, 1, "second@example.com"),
        return_exceptions=True,
    )
    assert sum(isinstance(result, dict) for result in outcomes) == 1
    assert any(isinstance(result, HTTPException) and result.status_code == 409 for result in outcomes)
    assert Service.document()["revision"] == 2


def test_unsafe_bootstrap_password_does_not_reserve_installation(db):
    Service.initialize()
    with pytest.raises(ValueError, match="password"):
        Service.reserve("admin@example.com", "short", DEFAULTS)
    assert Service.document()["state"] == "PENDING"
    assert db.users.count_documents({}) == 0


def test_existing_non_admin_email_does_not_leave_incomplete_reservation(db):
    Service.initialize()
    db.users.insert_one({"user_id": "existing-operator", "email": "admin@example.com", "role": "TENANT_OPERATOR"})
    with pytest.raises(HTTPException) as exc:
        Service.reserve("admin@example.com", "synthetic-password-only", DEFAULTS)
    assert exc.value.status_code == 409
    assert Service.document()["state"] == "PENDING"


@pytest.mark.parametrize("url", ["https://user:password@example.com", "https://example.com?q=1",
                                "https://example.com/#fragment", "http://remote.example.com", "https://example.com/api"])
def test_invalid_public_urls(url):
    with pytest.raises(ValueError):
        validate({"public_url": url})


@pytest.mark.parametrize("failure", ["missing", "redirect", "malformed", "unavailable"])
def test_ollama_failures_are_safe(failure):
    def handler(request):
        if failure == "redirect":
            return httpx.Response(302, headers={"Location": "https://other.example.com"})
        if failure == "unavailable":
            raise httpx.ConnectError("synthetic failure", request=request)
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [] if failure == "missing" else [{"name": "phi3:latest"}]})
        return httpx.Response(200, json={"response": "not JSON"})
    with httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False) as client:
        with pytest.raises(HTTPException) as exc:
            Service.check_ollama(client, DEFAULTS)
    assert exc.value.status_code == 422
    assert "synthetic failure" not in exc.value.detail


def test_ollama_success():
    def handler(request):
        return httpx.Response(200, json={"models": [{"name": "phi3:latest"}]} if request.method == "GET" else {"response": '{"ready":true}'})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert Service.check_ollama(client, DEFAULTS)["ok"]


def test_api_gate_permissions_and_secret_redaction(db, monkeypatch):
    Service.initialize()
    monkeypatch.setattr(app.state, "configuration_ready", True)
    client = TestClient(app)
    assert client.get("/api/v1/admin/settings/platform", headers=auth()).status_code == 503
    assert client.get("/api/v1/installation/status").json()["wizard_available"]
    assert client.post("/api/v1/installation/complete", headers={"X-TierX-Installation-Token": "wrong"},
                       json={"email": "admin@example.com", "password": "synthetic-password-only", "values": DEFAULTS}).status_code == 403
    response = client.post("/api/v1/installation/complete", headers={"X-TierX-Installation-Token": "synthetic-one-time-token"},
                           json={"email": "admin@example.com", "password": "synthetic-password-only", "values": DEFAULTS})
    assert response.status_code == 200
    assert client.get("/api/v1/installation/status").json() == {"installed": True, "wizard_available": False}
    assert client.get("/api/v1/admin/settings/platform").status_code in (401, 403)
    assert client.get("/api/v1/admin/settings/platform", headers=auth("TENANT_ADMIN")).status_code == 403
    assert client.get("/api/v1/admin/settings/platform", headers=auth("TENANT_OPERATOR")).status_code == 403
    response = client.get("/api/v1/admin/settings/platform", headers=auth())
    assert response.status_code == 200
    assert "token" not in response.text and "hashed_password" not in response.text
    assert client.get("/api/v1/installation/status").headers["cache-control"] == "no-store"
