from fastapi.testclient import TestClient
from pymongo.errors import ServerSelectionTimeoutError
from unittest.mock import AsyncMock

import main


import pytest


@pytest.mark.asyncio
async def test_installation_checks_reuse_application_client(monkeypatch):
    from types import SimpleNamespace
    collection = SimpleNamespace(find_one=AsyncMock(return_value={"state": "INSTALLED"}))
    client = {main.settings.mongo_db: {main.COLLECTION: collection}}
    monkeypatch.setattr(main.app.state, "installation_client", client, raising=False)
    monkeypatch.setattr(main, "AsyncIOMotorClient", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("new client")))
    assert await main.installation_complete()
    assert await main.installation_complete()
    assert collection.find_one.await_count == 2


def test_ingestion_waits_for_installation(monkeypatch):
    async def pending():
        return False
    monkeypatch.setattr(main, "installation_complete", pending)
    client = TestClient(main.app)
    response = client.post("/api/v1/alerts/ingest", json={})
    assert response.status_code == 503
    assert response.json()["detail"] == "INSTALLATION_REQUIRED"
    assert client.get("/api/v1/health").status_code == 200


def test_installed_ingestion_reaches_normal_validation(monkeypatch):
    async def ready():
        return True
    monkeypatch.setattr(main, "installation_complete", ready)
    monkeypatch.setattr(main.kafka_publisher, "publish_dead_letter", AsyncMock())
    response = TestClient(main.app).post("/api/v1/alerts/ingest", json={})
    assert response.status_code == 422


def test_database_failure_fails_closed(monkeypatch):
    async def unavailable():
        raise ServerSelectionTimeoutError("synthetic safe test")
    monkeypatch.setattr(main, "installation_complete", unavailable)
    response = TestClient(main.app).post("/api/v1/alerts/ingest", json={})
    assert response.status_code == 503
    assert "synthetic safe test" not in response.text
