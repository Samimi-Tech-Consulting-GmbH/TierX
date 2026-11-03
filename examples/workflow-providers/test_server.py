import importlib.util
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "example_context_server", Path(__file__).with_name("server.py")
)
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


@pytest.fixture
def endpoint(monkeypatch, tmp_path):
    monkeypatch.setenv("EXAMPLE_PROVIDER_TOKEN", "synthetic-test-token")
    monkeypatch.setenv("EXAMPLE_DB", str(tmp_path / "deliveries.sqlite"))
    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()
    thread.join()
    httpd.server_close()


def post(endpoint, path, payload, token="synthetic-test-token"):
    request = urllib.request.Request(
        endpoint + path,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=3) as response:
        return json.load(response)


def test_rest_real_http_and_idempotent_delivery(endpoint):
    body = {
        "tool": "asset_context",
        "arguments": {"value": "DB01"},
        "delivery_id": "one",
    }
    assert post(endpoint, "/rest", body)["outcome"] == "CRITICAL_ASSET"
    assert post(endpoint, "/rest", body) == post(endpoint, "/rest", body)
    with pytest.raises(urllib.error.HTTPError) as error:
        post(endpoint, "/rest", {**body, "arguments": {"value": "other"}})
    assert error.value.code == 409


def test_mcp_real_http_discovery_and_unknown_evidence(endpoint):
    result = post(endpoint, "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert len(result["result"]["tools"]) == 5
    call = post(
        endpoint,
        "/mcp",
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "indicator_reputation",
                "arguments": {"value": "unknown.example"},
            },
        },
    )
    assert call["result"]["structuredContent"]["outcome"] == "UNKNOWN"


def test_authentication_and_failure_scenarios(endpoint):
    for path, token, code in [
        ("/rest", "wrong", 401),
        ("/fail", "synthetic-test-token", 503),
    ]:
        with pytest.raises(urllib.error.HTTPError) as error:
            post(endpoint, path, {}, token)
        assert error.value.code == code
    assert post(endpoint, "/malformed", {}) == {"unexpected": True}
