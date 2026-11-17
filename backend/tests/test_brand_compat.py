import pytest
from fastapi import HTTPException
from starlette.requests import Request
from app.core.brand_compat import tierx_header, tierx_headers, env_value

def test_environment_resolution(monkeypatch):
    monkeypatch.delenv("TIERX_SAMPLE", raising=False)
    monkeypatch.delenv("SAMPLE", raising=False)
    assert env_value("SAMPLE", "default") == "default"
    monkeypatch.setenv("SAMPLE", "current")
    assert env_value("SAMPLE") == "current"
    monkeypatch.setenv("TIERX_SAMPLE", "canonical")
    assert env_value("SAMPLE") == "canonical"

def test_only_tierx_headers_are_read_and_emitted():
    request = Request({"type": "http", "headers": [(b"x-tierx-delivery-id", b"delivery")]})
    assert tierx_header(request, "delivery-id") == "delivery"
    assert tierx_headers(delivery_id="delivery") == {"X-TierX-Delivery-ID": "delivery"}
    with pytest.raises(HTTPException) as error:
        tierx_header(Request({"type": "http", "headers": []}), "delivery-id", required=True)
    assert error.value.status_code == 401
