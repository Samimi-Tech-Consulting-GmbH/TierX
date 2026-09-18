import base64
import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings
from app.services.playbook_context_webhook import (
    PlaybookContextWebhookClient,
    validate_public_https_url,
)


def test_delivery_ids_preserve_persisted_namespace():
    assert PlaybookContextWebhookClient.delivery_id("tenant", "alert", "pb", 2) == "255761a1-f9db-53ab-9d18-56175f0b028c"
    assert PlaybookContextWebhookClient.delivery_id("tenant", "alert", "pb", 2, "first") == "55ccd627-45b8-5fc9-8cd5-08dcd472b9d5"


class Collection:
    def __init__(self, records):
        self.records = records

    async def find_one(self, query, projection=None):
        return next(
            (
                record
                for record in self.records
                if all(record.get(key) == value for key, value in query.items())
            ),
            None,
        )


def encrypted_record(master_key, secret, scope="TENANT", scope_id="tenant-1"):
    key_id = "whk_test"
    nonce = b"n" * 12
    aad = f"soc-mind:webhook:v1:tenant-1:{scope}:{scope_id}:{key_id}".encode()
    ciphertext = AESGCM(master_key).encrypt(nonce, secret.encode(), aad)
    return {
        "scope_type": scope,
        "scope_id": scope_id,
        "key_id": key_id,
        "nonce": base64.urlsafe_b64encode(nonce).decode().rstrip("="),
        "ciphertext": base64.urlsafe_b64encode(ciphertext).decode().rstrip("="),
    }


@pytest.fixture
def webhook_setup(monkeypatch):
    key = b"k" * 32
    monkeypatch.setattr(settings, "playbook_context_webhooks_enabled", True)
    monkeypatch.setattr(
        settings,
        "webhook_secret_encryption_key",
        base64.urlsafe_b64encode(key).decode().rstrip("="),
    )
    monkeypatch.setattr(
        "app.services.playbook_context_webhook.validate_public_https_url",
        lambda url: _async_value(url),
    )
    return key


async def _async_value(value):
    return value


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "http://customer.example/context",
        "https://user:pass@customer.example/context",
        "https://customer.example/context?secret=no",
        "https://customer.example/context#fragment",
    ],
)
async def test_destination_shape_rejects_unsafe_urls(url):
    with pytest.raises(ValueError, match="WEBHOOK_DESTINATION_REJECTED"):
        await validate_public_https_url(url)


@pytest.mark.asyncio
async def test_destination_rejects_private_dns_resolution(monkeypatch):
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda *args, **kwargs: [
            (2, 1, 6, "", ("127.0.0.1", 443)),
            (2, 1, 6, "", ("10.0.0.7", 443)),
        ],
    )
    with pytest.raises(ValueError, match="WEBHOOK_DESTINATION_REJECTED"):
        await validate_public_https_url("https://customer.example/context")


def alert():
    return {
        "alert_id": "alert-1",
        "tenant_id": "tenant-1",
        "alert_type": "endpoint.malware",
        "source_system": "splunk",
        "fingerprint": "f" * 64,
        "normalized_payload": {"host.hostname": "workstation-1"},
        "raw_payload": {"authorization": "never-send"},
    }


def playbook():
    return {
        "playbook_id": "pb-1",
        "version": 2,
        "context_webhook": {
            "enabled": True,
            "url": "https://customer.example/context",
            "timeout_seconds": 5,
        },
    }


def multiple_playbook(count=2):
    return {
        "playbook_id": "pb-1",
        "version": 2,
        "context_webhooks": [
            {
                "webhook_id": f"provider-{index}",
                "name": f"Provider {index}",
                "enabled": True,
                "url": f"https://customer.example/{index}",
                "timeout_seconds": 5,
            }
            for index in range(count)
        ],
    }


@pytest.mark.asyncio
async def test_success_signs_normalized_only_and_persists_safe_metadata(
    monkeypatch, webhook_setup
):
    secret = "whsec_test"
    client = PlaybookContextWebhookClient(
        {
            "webhook_signing_credentials": Collection(
                [encrypted_record(webhook_setup, secret)]
            )
        }
    )
    captured = {}

    class FakeClient:
        def __init__(self, **kwargs):
            assert kwargs["follow_redirects"] is False
            assert kwargs["trust_env"] is False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        @asynccontextmanager
        async def stream(self, method, url, content, headers):
            captured.update(url=url, content=content, headers=headers)
            yield httpx.Response(
                200,
                json={"prompt_footer": "Use tenant evidence."},
                request=httpx.Request(method, url),
            )

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    result = await client.execute(
        tenant_id="tenant-1", alert=alert(), playbook=playbook(), existing=None
    )
    assert result["status"] == "SUCCEEDED"
    assert result["prompt_footer"] == "Use tenant evidence."
    assert b"raw_payload" not in captured["content"]
    assert b"authorization" not in captured["content"]
    assert captured["headers"]["X-TierX-Signature"].startswith("v1=")
    assert captured["headers"]["X-SOC-Mind-Signature"] == captured["headers"]["X-TierX-Signature"]
    assert "secret" not in str(result)


@pytest.mark.asyncio
async def test_terminal_replay_does_not_call_webhook(monkeypatch, webhook_setup):
    client = PlaybookContextWebhookClient(
        {"webhook_signing_credentials": Collection([])}
    )
    existing = {
        "status": "FAILED",
        "delivery_id": client.delivery_id("tenant-1", "alert-1", "pb-1", 2),
        "error_type": "WEBHOOK_TIMEOUT",
    }

    class MustNotRun:
        def __init__(self, **kwargs):
            raise AssertionError("replay issued another HTTP request")

    monkeypatch.setattr(httpx, "AsyncClient", MustNotRun)
    assert (
        await client.execute(
            tenant_id="tenant-1", alert=alert(), playbook=playbook(), existing=existing
        )
        == existing
    )


@pytest.mark.asyncio
async def test_missing_secret_and_http_failure_are_terminal_non_throwing(
    monkeypatch, webhook_setup
):
    missing = PlaybookContextWebhookClient(
        {"webhook_signing_credentials": Collection([])}
    )
    result = await missing.execute(
        tenant_id="tenant-1", alert=alert(), playbook=playbook(), existing=None
    )
    assert result["status"] == "SKIPPED"

    configured = PlaybookContextWebhookClient(
        {
            "webhook_signing_credentials": Collection(
                [encrypted_record(webhook_setup, "whsec_test")]
            )
        }
    )

    class BadClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        @asynccontextmanager
        async def stream(self, method, url, **kwargs):
            yield httpx.Response(
                503,
                content=b"internal details must not persist",
                request=httpx.Request(method, url),
            )

    monkeypatch.setattr(httpx, "AsyncClient", BadClient)
    result = await configured.execute(
        tenant_id="tenant-1", alert=alert(), playbook=playbook(), existing=None
    )
    assert result["status"] == "FAILED"
    assert result["error_type"] == "WEBHOOK_HTTP_ERROR"
    assert "internal details" not in str(result)


@pytest.mark.asyncio
async def test_multiple_providers_run_in_parallel_preserve_order_and_isolate_failure(
    monkeypatch, webhook_setup
):
    monkeypatch.setattr(settings, "playbook_webhook_max_concurrency", 5)
    client = PlaybookContextWebhookClient(
        {
            "webhook_signing_credentials": Collection(
                [encrypted_record(webhook_setup, "whsec_test")]
            )
        }
    )
    active = 0
    max_active = 0
    captured = []

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        @asynccontextmanager
        async def stream(self, method, url, content, headers):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            captured.append((url, content, headers))
            await asyncio.sleep(0.02)
            active -= 1
            if url.endswith("/1"):
                yield httpx.Response(
                    503,
                    content=b"safe failure",
                    request=httpx.Request(method, url),
                )
            else:
                yield httpx.Response(
                    200,
                    json={"prompt_footer": f"Context from {url}"},
                    request=httpx.Request(method, url),
                )

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    results = await client.execute_many(
        tenant_id="tenant-1",
        alert=alert(),
        playbook=multiple_playbook(),
        existing=None,
    )

    assert max_active == 2
    assert [result["webhook_id"] for result in results] == [
        "provider-0",
        "provider-1",
    ]
    assert [result["config_order"] for result in results] == [0, 1]
    assert [result["status"] for result in results] == ["SUCCEEDED", "FAILED"]
    assert results[0]["delivery_id"] != results[1]["delivery_id"]
    assert all(b"raw_payload" not in content for _, content, _ in captured)
    assert len({headers["X-TierX-Key-ID"] for _, _, headers in captured}) == 1


@pytest.mark.asyncio
async def test_multiple_provider_concurrency_bound_and_independent_replay(
    monkeypatch, webhook_setup
):
    monkeypatch.setattr(settings, "playbook_webhook_max_concurrency", 5)
    client = PlaybookContextWebhookClient(
        {
            "webhook_signing_credentials": Collection(
                [encrypted_record(webhook_setup, "whsec_test")]
            )
        }
    )
    active = 0
    max_active = 0
    called_urls = []

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        @asynccontextmanager
        async def stream(self, method, url, **kwargs):
            nonlocal active, max_active
            called_urls.append(url)
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0.01)
            active -= 1
            yield httpx.Response(
                200,
                json={"prompt_footer": url},
                request=httpx.Request(method, url),
            )

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    configured = multiple_playbook(7)
    replayed = {
        "webhook_id": "provider-0",
        "webhook_name": "Provider 0",
        "config_order": 0,
        "status": "SUCCEEDED",
        "delivery_id": client.delivery_id(
            "tenant-1", "alert-1", "pb-1", 2, "provider-0"
        ),
        "playbook_id": "pb-1",
        "playbook_version": 2,
        "prompt_footer": "persisted",
    }
    results = await client.execute_many(
        tenant_id="tenant-1",
        alert=alert(),
        playbook=configured,
        existing=[replayed],
    )

    assert results[0] == replayed
    assert len(called_urls) == 6
    assert max_active == 5


@pytest.mark.asyncio
async def test_disabled_provider_is_audited_without_an_http_request(
    monkeypatch, webhook_setup
):
    client = PlaybookContextWebhookClient(
        {
            "webhook_signing_credentials": Collection(
                [encrypted_record(webhook_setup, "whsec_test")]
            )
        }
    )
    configured = multiple_playbook(2)
    configured["context_webhooks"][1]["enabled"] = False

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        @asynccontextmanager
        async def stream(self, method, url, **kwargs):
            assert url.endswith("/0")
            yield httpx.Response(
                200,
                json={"prompt_footer": "enabled"},
                request=httpx.Request(method, url),
            )

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    results = await client.execute_many(
        tenant_id="tenant-1",
        alert=alert(),
        playbook=configured,
        existing=None,
    )

    assert [result["status"] for result in results] == ["SUCCEEDED", "SKIPPED"]
    assert results[1]["error_type"] == "WEBHOOK_DISABLED"
