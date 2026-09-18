import base64
import json
import logging
from datetime import datetime, timezone

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings
from app.services.enrichment_action import (
    EnrichmentActionCoordinator,
    canonical_json,
    decrypt_action_secret,
    deterministic_id,
    validate_public_https_url,
)


def test_canonical_json_and_delivery_ids_are_stable_per_action():
    assert canonical_json({"b": 2, "a": 1}) == b'{"a":1,"b":2}'
    first = deterministic_id("delivery", "tenant", "alert", "pb", 2, "first")
    assert first == "ebca34d6-ac0a-5e6a-8a70-0130700c1d08"
    assert first == deterministic_id("delivery", "tenant", "alert", "pb", 2, "first")
    assert first != deterministic_id("delivery", "tenant", "alert", "pb", 2, "second")


def test_action_secret_uses_action_specific_aad(monkeypatch):
    master = b"m" * 32
    nonce = b"n" * 12
    key_id = "eak_test"
    action_code = "observe"
    aad = f"soc-mind:enrichment-action:v1:{action_code}:{key_id}".encode()
    ciphertext = AESGCM(master).encrypt(nonce, b"easec_test", aad)
    encode = lambda value: base64.urlsafe_b64encode(value).decode().rstrip("=")
    monkeypatch.setattr(settings, "webhook_secret_encryption_key", encode(master))
    assert decrypt_action_secret(
        {
            "action_code": action_code,
            "key_id": key_id,
            "nonce": encode(nonce),
            "ciphertext": encode(ciphertext),
        }
    ) == "easec_test"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "http://provider.example/action",
        "https://user:pass@provider.example/action",
        "https://provider.example/action?credential=no",
        "https://provider.example/action#fragment",
    ],
)
async def test_destination_shape_is_rejected(url):
    with pytest.raises(ValueError, match="ACTION_DESTINATION_REJECTED"):
        await validate_public_https_url(url)


@pytest.mark.asyncio
async def test_private_dns_is_rejected(monkeypatch):
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("10.0.0.8", 443))],
    )
    with pytest.raises(ValueError, match="ACTION_DESTINATION_REJECTED"):
        await validate_public_https_url("https://provider.example/action")


@pytest.mark.asyncio
async def test_progress_trace_is_serializable_and_excludes_context(monkeypatch):
    produced = []

    async def produce(topic, event):
        produced.append((topic, event))

    monkeypatch.setattr(settings, "debug_trace_enabled", True)
    coordinator = EnrichmentActionCoordinator(produce, logging.getLogger("test"))
    batch = {
        "batch_id": "batch-1",
        "alert_id": "alert-1",
        "tenant_id": "tenant-1",
        "action_codes": ["observe"],
        "created_at": datetime.now(timezone.utc),
        "output_message": {
            "alert_type": "endpoint",
            "source_system": "SPLUNK",
        },
    }
    await coordinator._trace_event(
        "PROGRESS",
        batch,
        decisions={
            "actions": [
                {
                    "action_code": "observe",
                    "deadline_at": datetime.now(timezone.utc),
                    "status": "RUNNING",
                }
            ]
        },
    )
    encoded = json.dumps(produced[0][1])
    assert "deadline_at" in encoded
    assert "context_text" not in encoded
