from __future__ import annotations

import base64
import os
import secrets
from datetime import datetime, timezone
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pymongo import ASCENDING

from app.core.errors import ResourceNotFoundError
from app.db.mongodb import DatabaseManager
from app.schemas.webhook_signing import WebhookSecretCreated, WebhookSecretMetadata
from app.services.tenant_service import TenantService


class WebhookSigningService:
    COLLECTION = "webhook_signing_credentials"

    @staticmethod
    def enabled() -> bool:
        return os.getenv("PLAYBOOK_CONTEXT_WEBHOOKS_ENABLED", "false").lower() in {
            "1", "true", "yes", "on"
        }

    @staticmethod
    def encryption_key() -> bytes:
        raw = os.getenv("WEBHOOK_SECRET_ENCRYPTION_KEY", "").strip()
        if not raw:
            raise RuntimeError("WEBHOOK_SECRET_ENCRYPTION_KEY is required")
        try:
            key = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
        except Exception as exc:
            raise RuntimeError("WEBHOOK_SECRET_ENCRYPTION_KEY must be base64url") from exc
        if len(key) != 32:
            raise RuntimeError("WEBHOOK_SECRET_ENCRYPTION_KEY must decode to 32 bytes")
        return key

    @classmethod
    def validate_configuration(cls) -> None:
        if cls.enabled():
            cls.encryption_key()

    @staticmethod
    def _database(tenant_id: str):
        tenant = TenantService.get_tenant_by_id(tenant_id)
        return DatabaseManager.get_tenant_database(str(tenant.db_name))

    @classmethod
    def _collection(cls, tenant_id: str):
        return cls._database(tenant_id)[cls.COLLECTION]

    @classmethod
    def ensure_indexes(cls, tenant_id: str) -> None:
        collection = cls._collection(tenant_id)
        collection.create_index(
            [("scope_type", ASCENDING), ("scope_id", ASCENDING)], unique=True
        )
        collection.create_index([("key_id", ASCENDING)], unique=True)

    @staticmethod
    def _aad(tenant_id: str, scope: str, scope_id: str, key_id: str, namespace: str = "tierx") -> bytes:
        return f"{namespace}:webhook:v1:{tenant_id}:{scope}:{scope_id}:{key_id}".encode()

    @classmethod
    def _encrypt(
        cls, tenant_id: str, scope: str, scope_id: str, key_id: str, secret: str
    ) -> tuple[str, str]:
        nonce = os.urandom(12)
        ciphertext = AESGCM(cls.encryption_key()).encrypt(
            nonce, secret.encode(), cls._aad(tenant_id, scope, scope_id, key_id)
        )
        return (
            base64.urlsafe_b64encode(nonce).decode().rstrip("="),
            base64.urlsafe_b64encode(ciphertext).decode().rstrip("="),
        )

    @classmethod
    def decrypt(cls, tenant_id: str, record: dict[str, Any]) -> str:
        nonce = base64.urlsafe_b64decode(record["nonce"] + "=" * (-len(record["nonce"]) % 4))
        ciphertext = base64.urlsafe_b64decode(
            record["ciphertext"] + "=" * (-len(record["ciphertext"]) % 4)
        )
        clear = AESGCM(cls.encryption_key()).decrypt(
            nonce,
            ciphertext,
            cls._aad(
                tenant_id,
                record["scope_type"],
                record["scope_id"],
                record["key_id"],
                record.get("aad_namespace") or "soc-mind",
            ),
        )
        return clear.decode()

    @staticmethod
    def _scope_id(tenant_id: str, scope: str, playbook_id: str | None) -> str:
        if scope == "TENANT":
            return tenant_id
        if not playbook_id:
            raise ValueError("playbook_id is required for PLAYBOOK credentials")
        return playbook_id

    @classmethod
    def _find(cls, tenant_id: str, scope: str, playbook_id: str | None = None):
        scope_id = cls._scope_id(tenant_id, scope, playbook_id)
        return cls._collection(tenant_id).find_one(
            {"scope_type": scope, "scope_id": scope_id}, {"_id": 0}
        )

    @classmethod
    def _metadata(
        cls, tenant_id: str, scope: str, playbook_id: str | None = None
    ) -> WebhookSecretMetadata:
        record = cls._find(tenant_id, scope, playbook_id)
        fallback = cls._find(tenant_id, "TENANT") if scope == "PLAYBOOK" else record
        effective = "PLAYBOOK" if record else ("TENANT" if fallback else "NONE")
        return WebhookSecretMetadata(
            configured=record is not None,
            scope=scope if record else "NONE",
            key_id=record.get("key_id") if record else None,
            created_at=record.get("created_at") if record else None,
            updated_at=record.get("updated_at") if record else None,
            tenant_fallback_configured=fallback is not None,
            effective_scope=effective,
        )

    @classmethod
    def get_metadata(
        cls, tenant_id: str, scope: str, playbook_id: str | None = None
    ) -> WebhookSecretMetadata:
        if scope == "PLAYBOOK":
            from app.services.playbook_service import PlaybookService

            PlaybookService.get_playbook(tenant_id, str(playbook_id))
        return cls._metadata(tenant_id, scope, playbook_id)

    @classmethod
    def rotate(
        cls,
        tenant_id: str,
        scope: str,
        actor: str,
        playbook_id: str | None = None,
    ) -> WebhookSecretCreated:
        if scope == "PLAYBOOK":
            from app.services.playbook_service import PlaybookService

            PlaybookService.get_playbook(tenant_id, str(playbook_id))
        cls.ensure_indexes(tenant_id)
        scope_id = cls._scope_id(tenant_id, scope, playbook_id)
        key_id = "whk_" + secrets.token_hex(12)
        secret = "whsec_" + base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip("=")
        nonce, ciphertext = cls._encrypt(tenant_id, scope, scope_id, key_id, secret)
        now = datetime.now(timezone.utc)
        cls._collection(tenant_id).update_one(
            {"scope_type": scope, "scope_id": scope_id},
            {
                "$set": {
                    "tenant_id": tenant_id,
                    "scope_type": scope,
                    "scope_id": scope_id,
                    "key_id": key_id,
                    "nonce": nonce,
                    "ciphertext": ciphertext,
                    "aad_namespace": "tierx",
                    "created_by": actor,
                    "updated_at": now,
                },
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )
        metadata = cls._metadata(tenant_id, scope, playbook_id)
        return WebhookSecretCreated(**metadata.model_dump(), secret=secret)

    @classmethod
    def delete(
        cls, tenant_id: str, scope: str, playbook_id: str | None = None
    ) -> WebhookSecretMetadata:
        scope_id = cls._scope_id(tenant_id, scope, playbook_id)
        result = cls._collection(tenant_id).delete_one(
            {"scope_type": scope, "scope_id": scope_id}
        )
        if result.deleted_count == 0:
            raise ResourceNotFoundError("Webhook signing secret is not configured")
        return cls._metadata(tenant_id, scope, playbook_id)

    @classmethod
    def resolve(cls, tenant_id: str, playbook_id: str) -> dict[str, Any] | None:
        record = cls._find(tenant_id, "PLAYBOOK", playbook_id)
        if record is None:
            record = cls._find(tenant_id, "TENANT")
        if record is None:
            return None
        return {
            **record,
            "secret": cls.decrypt(tenant_id, record),
            "effective_scope": record["scope_type"],
        }

    @classmethod
    def resolve_by_key_id(
        cls, tenant_id: str, playbook_id: str, key_id: str
    ) -> dict[str, Any] | None:
        record = cls._collection(tenant_id).find_one({"key_id": key_id}, {"_id": 0})
        if not record:
            return None
        if record["scope_type"] == "TENANT" and record["scope_id"] != tenant_id:
            return None
        if record["scope_type"] == "PLAYBOOK" and record["scope_id"] != playbook_id:
            return None
        return {**record, "secret": cls.decrypt(tenant_id, record)}
