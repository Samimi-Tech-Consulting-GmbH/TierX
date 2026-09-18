import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.core.brand_compat import compatible_header, dual_headers, env_value


def _request(headers: list[tuple[bytes, bytes]]) -> Request:
    return Request({"type": "http", "headers": headers})


def test_environment_resolution_prefers_tierx_then_existing_then_legacy(monkeypatch):
    for key in ("TIERX_SAMPLE", "SAMPLE", "SOC_MIND_SAMPLE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("SOC_MIND_SAMPLE", "legacy")
    assert env_value("SAMPLE") == "legacy"
    monkeypatch.setenv("SAMPLE", "current")
    assert env_value("SAMPLE") == "current"
    monkeypatch.setenv("TIERX_SAMPLE", "canonical")
    assert env_value("SAMPLE") == "canonical"


def test_header_families_match_and_conflicts_are_rejected():
    request = _request([
        (b"x-tierx-delivery-id", b"same"),
        (b"x-soc-mind-delivery-id", b"same"),
    ])
    assert compatible_header(request, "delivery-id") == "same"
    conflict = _request([
        (b"x-tierx-delivery-id", b"one"),
        (b"x-soc-mind-delivery-id", b"two"),
    ])
    with pytest.raises(HTTPException) as error:
        compatible_header(conflict, "delivery-id")
    assert error.value.status_code == 400


def test_dual_headers_emit_identical_values():
    headers = dual_headers(delivery_id="delivery")
    assert headers["X-TierX-Delivery-ID"] == headers["X-SOC-Mind-Delivery-ID"]
