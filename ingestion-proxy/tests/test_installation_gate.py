from fastapi.testclient import TestClient
from pymongo.errors import ServerSelectionTimeoutError
from unittest.mock import AsyncMock

import main


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
