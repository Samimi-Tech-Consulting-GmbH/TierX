from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import ipaddress
import json
import socket
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, uuid5

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings


TERMINAL_STATUSES = {"SUCCEEDED", "FAILED", "SKIPPED"}


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    ).encode("utf-8")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def decrypt_secret(tenant_id: str, record: dict[str, Any]) -> str:
    namespace = record.get("aad_namespace") or "soc-mind"
    aad = (
        f"{namespace}:webhook:v1:{tenant_id}:{record['scope_type']}:"
        f"{record['scope_id']}:{record['key_id']}"
    ).encode()
    clear = AESGCM(_decode(settings.webhook_secret_encryption_key)).decrypt(
        _decode(record["nonce"]), _decode(record["ciphertext"]), aad
    )
    return clear.decode()


async def validate_public_https_url(url: str) -> str:
    parts = urlsplit(url)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
    ):
        raise ValueError("WEBHOOK_DESTINATION_REJECTED")
    try:
        addresses = await asyncio.to_thread(
            socket.getaddrinfo,
            parts.hostname,
            parts.port or 443,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise ValueError("WEBHOOK_DNS_FAILURE") from exc
    resolved = {entry[4][0].split("%", 1)[0] for entry in addresses}
    if not resolved or any(
        not ipaddress.ip_address(addr).is_global for addr in resolved
    ):
        raise ValueError("WEBHOOK_DESTINATION_REJECTED")
    return url


class PlaybookContextWebhookClient:
    def __init__(self, tenant_db: Any):
        self.db = tenant_db

    async def _credential(self, tenant_id: str, playbook_id: str):
        collection = self.db["webhook_signing_credentials"]
        record = await collection.find_one(
            {"scope_type": "PLAYBOOK", "scope_id": playbook_id}, {"_id": 0}
        )
        if record is None:
            record = await collection.find_one(
                {"scope_type": "TENANT", "scope_id": tenant_id}, {"_id": 0}
            )
        if record is None:
            return None
        return {**record, "secret": decrypt_secret(tenant_id, record)}

    @staticmethod
    def delivery_id(
        tenant_id: str,
        alert_id: str,
        playbook_id: str,
        version: int,
        webhook_id: str | None = None,
    ) -> str:
        # Keep persisted delivery IDs stable across product renames.
        identity = f"soc-mind:webhook:v1:{tenant_id}:{alert_id}:{playbook_id}:{version}"
        if webhook_id is not None:
            identity += f":{webhook_id}"
        return str(
            uuid5(
                NAMESPACE_URL,
                identity,
            )
        )

    async def execute_many(
        self,
        *,
        tenant_id: str,
        alert: dict[str, Any],
        playbook: dict[str, Any],
        existing: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        """Execute enabled providers independently and preserve configured order."""
        if not settings.playbook_context_webhooks_enabled:
            return []
        providers = list(playbook.get("context_webhooks") or [])
        maximum = max(1, min(10, settings.playbook_webhook_max_count))
        if len(providers) > maximum:
            providers = providers[:maximum]
        configured = list(enumerate(providers))
        if not configured:
            return []

        playbook_id = str(playbook["playbook_id"])
        playbook_version = int(playbook.get("version") or 1)
        existing_by_id = {
            str(result.get("webhook_id")): result
            for result in (existing or [])
            if result.get("webhook_id")
        }
        credential = None
        if any(provider.get("enabled") for _, provider in configured):
            try:
                credential = await self._credential(tenant_id, playbook_id)
            except Exception:
                credential = None
        semaphore = asyncio.Semaphore(
            max(1, min(settings.playbook_webhook_max_concurrency, len(configured)))
        )

        async def run(order: int, provider: dict[str, Any]) -> dict[str, Any]:
            webhook_id = str(provider["webhook_id"])
            if not provider.get("enabled"):
                return {
                    "delivery_id": self.delivery_id(
                        tenant_id,
                        str(alert["alert_id"]),
                        playbook_id,
                        playbook_version,
                        webhook_id,
                    ),
                    "playbook_id": playbook_id,
                    "playbook_version": playbook_version,
                    "webhook_id": webhook_id,
                    "webhook_name": str(provider["name"]),
                    "config_order": order,
                    "status": "SKIPPED",
                    "error_type": "WEBHOOK_DISABLED",
                    "duration_ms": 0.0,
                    "completed_at": datetime.now(timezone.utc),
                }
            async with semaphore:
                return await self._execute_provider(
                    tenant_id=tenant_id,
                    alert=alert,
                    playbook=playbook,
                    config=provider,
                    webhook_id=webhook_id,
                    webhook_name=str(provider["name"]),
                    config_order=order,
                    existing=existing_by_id.get(webhook_id),
                    credential=credential,
                )

        return list(
            await asyncio.gather(*(run(order, provider) for order, provider in configured))
        )

    async def execute(
        self,
        *,
        tenant_id: str,
        alert: dict[str, Any],
        playbook: dict[str, Any],
        existing: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        config = playbook.get("context_webhook") or {}
        if not settings.playbook_context_webhooks_enabled or not config.get("enabled"):
            return None
        playbook_id = str(playbook["playbook_id"])
        try:
            credential = await self._credential(tenant_id, playbook_id)
        except Exception:
            credential = None
        return await self._execute_provider(
            tenant_id=tenant_id,
            alert=alert,
            playbook=playbook,
            config=config,
            webhook_id=None,
            webhook_name=None,
            config_order=0,
            existing=existing,
            credential=credential,
        )

    async def _execute_provider(
        self,
        *,
        tenant_id: str,
        alert: dict[str, Any],
        playbook: dict[str, Any],
        config: dict[str, Any],
        webhook_id: str | None,
        webhook_name: str | None,
        config_order: int,
        existing: dict[str, Any] | None,
        credential: dict[str, Any] | None,
    ) -> dict[str, Any]:
        playbook_id = str(playbook["playbook_id"])
        version = int(playbook.get("version") or 1)
        delivery_id = self.delivery_id(
            tenant_id,
            str(alert["alert_id"]),
            playbook_id,
            version,
            webhook_id,
        )
        if (
            existing
            and existing.get("delivery_id") == delivery_id
            and existing.get("status") in TERMINAL_STATUSES
        ):
            return existing

        started = time.monotonic()
        base = {
            "delivery_id": delivery_id,
            "playbook_id": playbook_id,
            "playbook_version": version,
            "config_order": config_order,
        }
        if webhook_id is not None:
            base["webhook_id"] = webhook_id
            base["webhook_name"] = webhook_name

        def completed(**values: Any) -> dict[str, Any]:
            return {**base, "completed_at": datetime.now(timezone.utc), **values}

        try:
            if credential is None:
                return completed(
                    status="SKIPPED",
                    error_type="WEBHOOK_SIGNING_SECRET_MISSING",
                    duration_ms=round((time.monotonic() - started) * 1000, 3),
                )
            url = await validate_public_https_url(str(config["url"]))
            sent_at = datetime.now(timezone.utc)
            body = {
                "spec_version": "1.0",
                "delivery_id": delivery_id,
                "sent_at": sent_at.isoformat().replace("+00:00", "Z"),
                "tenant_id": tenant_id,
                "alert": {
                    "alert_id": alert["alert_id"],
                    "alert_type": alert["alert_type"],
                    "source_system": alert["source_system"],
                    "fingerprint": alert["fingerprint"],
                    "normalized_payload": alert.get("normalized_payload") or {},
                },
                "playbook": {"playbook_id": playbook_id, "version": version},
                "release": {
                    "version": settings.app_release_version,
                    "sha": settings.app_release_sha,
                },
            }
            raw = canonical_json(body)
            if len(raw) > settings.playbook_webhook_max_request_bytes:
                raise ValueError("WEBHOOK_REQUEST_TOO_LARGE")
            timestamp = str(int(sent_at.timestamp()))
            signed = timestamp.encode() + b"." + delivery_id.encode() + b"." + raw
            signature = hmac.new(
                credential["secret"].encode(), signed, hashlib.sha256
            ).hexdigest()
            headers = {
                "Content-Type": "application/json",
                "X-TierX-Webhook-Version": "1",
                "X-TierX-Delivery-ID": delivery_id,
                "X-TierX-Timestamp": timestamp,
                "X-TierX-Key-ID": credential["key_id"],
                "X-TierX-Signature": f"v1={signature}",
                "X-SOC-Mind-Webhook-Version": "1",
                "X-SOC-Mind-Delivery-ID": delivery_id,
                "X-SOC-Mind-Timestamp": timestamp,
                "X-SOC-Mind-Key-ID": credential["key_id"],
                "X-SOC-Mind-Signature": f"v1={signature}",
            }
            timeout = min(10, max(1, int(config.get("timeout_seconds") or 5)))
            async with httpx.AsyncClient(
                timeout=timeout, follow_redirects=False, trust_env=False
            ) as client:
                async with client.stream(
                    "POST", url, content=raw, headers=headers
                ) as response:
                    if response.status_code != 200:
                        raise ValueError("WEBHOOK_HTTP_ERROR")
                    chunks: list[bytes] = []
                    received = 0
                    async for chunk in response.aiter_bytes():
                        received += len(chunk)
                        if received > settings.playbook_webhook_max_response_bytes:
                            raise ValueError("WEBHOOK_RESPONSE_TOO_LARGE")
                        chunks.append(chunk)
                    content = b"".join(chunks)
            try:
                result = json.loads(content)
            except Exception as exc:
                raise ValueError("WEBHOOK_RESPONSE_INVALID_JSON") from exc
            footer = result.get("prompt_footer") if isinstance(result, dict) else None
            if not isinstance(footer, str) or not footer.strip():
                raise ValueError("WEBHOOK_RESPONSE_INVALID_SCHEMA")
            footer_bytes = footer.encode("utf-8")
            if len(footer_bytes) > settings.playbook_webhook_max_response_bytes:
                raise ValueError("WEBHOOK_RESPONSE_TOO_LARGE")
            return completed(
                status="SUCCEEDED",
                effective_credential_scope=credential["scope_type"],
                key_id=credential["key_id"],
                duration_ms=round((time.monotonic() - started) * 1000, 3),
                response_sha256=hashlib.sha256(footer_bytes).hexdigest(),
                response_size_bytes=len(footer_bytes),
                prompt_footer=footer,
            )
        except httpx.TimeoutException:
            error_type = "WEBHOOK_TIMEOUT"
        except httpx.RequestError:
            error_type = "WEBHOOK_REQUEST_FAILED"
        except ValueError as exc:
            error_type = (
                str(exc) if str(exc).startswith("WEBHOOK_") else "WEBHOOK_FAILURE"
            )
        except Exception:
            error_type = "WEBHOOK_FAILURE"
        return completed(
            status="FAILED",
            error_type=error_type,
            duration_ms=round((time.monotonic() - started) * 1000, 3),
        )
