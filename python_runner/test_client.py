"""Transport error classification must not confuse transient outages with rejection."""
import httpx
import pytest
from tierx_workflows import python_client
from tierx_workflows.python_tools import PythonToolError


@pytest.mark.asyncio
@pytest.mark.parametrize("posting", [True, False])
@pytest.mark.parametrize("status,body,expected", [
    (503, {"error": "PYTHON_STORAGE_UNAVAILABLE"}, "PYTHON_RUNNER_UNAVAILABLE"),
    (502, {"error": "proxy restart"}, "PYTHON_RUNNER_UNAVAILABLE"),
    (401, {}, "PYTHON_RUNNER_AUTH_REJECTED"),
    (404, {}, "PYTHON_EXECUTION_UNCERTAIN"),
    (422, {"error": "invalid"}, "PYTHON_RUNNER_REJECTED"),
    (429, {"error": "PYTHON_QUEUE_FULL"}, "PYTHON_QUEUE_FULL"),
])
async def test_error_status_classification(monkeypatch, posting, status, body, expected):
    monkeypatch.setenv("TIERX_PYTHON_BROKER_URL", "http://broker.example")
    monkeypatch.setenv("TIERX_PYTHON_BROKER_TOKEN", "synthetic-test-token")
    original = httpx.AsyncClient
    monkeypatch.setattr(python_client.httpx, "AsyncClient", lambda **kwargs: original(
        **kwargs, transport=httpx.MockTransport(lambda request: httpx.Response(status, json=body))))
    with pytest.raises(PythonToolError, match=expected):
        await python_client.broker_request("a" * 64, request={"input": {}} if posting else None)
