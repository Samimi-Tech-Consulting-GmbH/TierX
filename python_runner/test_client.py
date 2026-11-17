"""Transport error classification must not confuse transient outages with rejection."""
import httpx
import asyncio
import pytest
from tierx_workflows import python_client
from tierx_workflows.python_tools import PythonToolError


@pytest.mark.parametrize("posting", [True, False])
@pytest.mark.parametrize("status,body,expected", [
    (503, {"error": "PYTHON_STORAGE_UNAVAILABLE"}, "PYTHON_RUNNER_UNAVAILABLE"),
    (502, {"error": "proxy restart"}, "PYTHON_RUNNER_UNAVAILABLE"),
    (401, {}, "PYTHON_RUNNER_AUTH_REJECTED"),
    (404, {}, "PYTHON_EXECUTION_UNCERTAIN"),
    (422, {"error": "invalid"}, "PYTHON_RUNNER_REJECTED"),
    (429, {"error": "PYTHON_QUEUE_FULL"}, "PYTHON_QUEUE_FULL"),
])
def test_error_status_classification(monkeypatch, posting, status, body, expected):
    monkeypatch.setenv("TIERX_PYTHON_BROKER_URL", "http://broker.example")
    monkeypatch.setenv("TIERX_PYTHON_BROKER_TOKEN", "synthetic-test-token")
    original = httpx.AsyncClient
    monkeypatch.setattr(python_client.httpx, "AsyncClient", lambda **kwargs: original(
        **kwargs, transport=httpx.MockTransport(lambda request: httpx.Response(status, json=body))))
    with pytest.raises(PythonToolError, match=expected):
        asyncio.run(python_client.broker_request("a" * 64, request={"input": {}} if posting else None))


@pytest.mark.parametrize("status,expected", [(400, "PYTHON_RUNNER_PROTOCOL_ERROR"), (429, "PYTHON_QUEUE_FULL"),
    (502, "PYTHON_RUNNER_UNAVAILABLE"), (200, "PYTHON_RUNNER_PROTOCOL_ERROR")])
def test_non_json_responses_cannot_cause_permanent_polling(monkeypatch, status, expected):
    monkeypatch.setenv("TIERX_PYTHON_BROKER_URL", "http://broker.example")
    monkeypatch.setenv("TIERX_PYTHON_BROKER_TOKEN", "synthetic-test-token")
    original = httpx.AsyncClient
    monkeypatch.setattr(python_client.httpx, "AsyncClient", lambda **kwargs: original(
        **kwargs, transport=httpx.MockTransport(lambda request: httpx.Response(status, text="upstream response"))))
    with pytest.raises(PythonToolError, match=expected):
        asyncio.run(python_client.broker_request("a" * 64))
