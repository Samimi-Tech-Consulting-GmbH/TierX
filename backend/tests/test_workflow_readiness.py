from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize("age,state,expected", [(0, "READY", "green"), (60, "READY", "red"), (0, "FAILED", "red"), (None, None, "red")])
async def test_health_requires_workflow_heartbeat(monkeypatch, age, state, expected):
    import main
    record = None if age is None else {"updated_at": datetime.now(timezone.utc) - timedelta(seconds=age), "state": state}
    collection = SimpleNamespace(find_one=lambda *args: record)
    mongo = SimpleNamespace(admin=SimpleNamespace(command=lambda *args: {}), soc_mind_platform=SimpleNamespace(service_heartbeats=collection))
    monkeypatch.setattr(main, "MongoClient", lambda *args, **kwargs: mongo)
    monkeypatch.setattr(main, "KNOWLEDGE_BASE_PROCESSING_ENABLED", False)
    monkeypatch.setattr(main, "LLM_ANALYSIS_ENABLED", False)
    monkeypatch.setattr(main.app.state, "configuration_ready", False, raising=False)
    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, *args): return httpx.Response(503)
    monkeypatch.setattr(main.httpx, "AsyncClient", lambda **kwargs: Client())
    result = await main.health_check()
    assert result["components"]["workflow_engine"] == expected
    assert result["status"] == ("HEALTHY" if expected == "green" else "UNHEALTHY")
