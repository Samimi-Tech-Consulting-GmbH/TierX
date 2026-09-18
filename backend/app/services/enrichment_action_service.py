from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
from datetime import datetime, timezone
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pymongo import ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError

from app.core.errors import DuplicateResourceError, ResourceNotFoundError
from app.db.mongodb import DatabaseManager
from app.schemas.enrichment_action import (
    EnrichmentActionCreated,
    EnrichmentActionDocument,
    EnrichmentActionPage,
    EnrichmentActionTenantScope,
    EnrichmentActionUpdate,
    EnrichmentActionWrite,
)
from app.services.tenant_service import TenantService
from app.services.webhook_signing_service import WebhookSigningService


class EnrichmentActionService:
    COLLECTION = "enrichment_actions"

    @classmethod
    def _collection(cls):
        return DatabaseManager.get_tenant_database("soc_mind_platform")[cls.COLLECTION]

    @classmethod
    def ensure_indexes(cls) -> None:
        collection = cls._collection()
        collection.create_index([("action_code", ASCENDING)], unique=True)
        collection.create_index([("enabled", ASCENDING), ("updated_at", DESCENDING)])
        collection.create_index([("tenant_ids", ASCENDING), ("enabled", ASCENDING)])
        collection.create_index([("key_id", ASCENDING)], unique=True)

    @staticmethod
    def enabled() -> bool:
        return os.getenv("ENRICHMENT_ACTIONS_ENABLED", "false").lower() in {
            "1", "true", "yes", "on"
        }

    @classmethod
    def validate_configuration(cls) -> None:
        if cls.enabled():
            WebhookSigningService.encryption_key()

    @staticmethod
    def _aad(action_code: str, key_id: str, namespace: str = "tierx") -> bytes:
        return f"{namespace}:enrichment-action:v1:{action_code}:{key_id}".encode()

    @classmethod
    def _encrypt(cls, action_code: str, key_id: str, secret: str) -> tuple[str, str]:
        nonce = os.urandom(12)
        ciphertext = AESGCM(WebhookSigningService.encryption_key()).encrypt(
            nonce, secret.encode(), cls._aad(action_code, key_id)
        )
        encode = lambda value: base64.urlsafe_b64encode(value).decode().rstrip("=")
        return encode(nonce), encode(ciphertext)

    @staticmethod
    def _checksum(record: dict[str, Any]) -> str:
        safe = {
            key: record[key]
            for key in (
                "action_code", "name", "description", "url", "timeout_seconds",
                "enabled", "tenant_scope", "tenant_ids", "key_id",
            )
        }
        raw = json.dumps(safe, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(raw).hexdigest()

    @classmethod
    def _validate_tenants(cls, scope: EnrichmentActionTenantScope, ids: list[str]) -> None:
        if scope == EnrichmentActionTenantScope.ALL_TENANTS:
            return
        for tenant_id in ids:
            tenant = TenantService.get_tenant_by_id(tenant_id)
            if tenant.status == "DELETED":
                raise ValueError(f"Tenant is deleted: {tenant_id}")

    @staticmethod
    def _document(record: dict[str, Any]) -> EnrichmentActionDocument:
        safe = {
            key: value
            for key, value in record.items()
            if key not in {"_id", "nonce", "ciphertext", "aad_namespace"}
        }
        return EnrichmentActionDocument(**safe)

    @classmethod
    def create(cls, payload: EnrichmentActionWrite, actor: str) -> EnrichmentActionCreated:
        cls.ensure_indexes()
        cls._validate_tenants(payload.tenant_scope, payload.tenant_ids)
        if cls._collection().find_one({"action_code": payload.action_code}):
            raise DuplicateResourceError("Enrichment action code already exists")
        now = datetime.now(timezone.utc)
        key_id = "eak_" + secrets.token_hex(12)
        secret = "easec_" + base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip("=")
        nonce, ciphertext = cls._encrypt(payload.action_code, key_id, secret)
        record = {
            **payload.model_dump(mode="json"),
            "url": str(payload.url),
            "key_id": key_id,
            "nonce": nonce,
            "ciphertext": ciphertext,
            "aad_namespace": "tierx",
            "created_at": now,
            "updated_at": now,
            "created_by": actor,
            "updated_by": actor,
            "deleted_at": None,
            "last_used_at": None,
            "last_status": None,
            "last_duration_ms": None,
            "last_error_type": None,
        }
        record["configuration_checksum"] = cls._checksum(record)
        try:
            cls._collection().insert_one(record)
        except DuplicateKeyError as exc:
            raise DuplicateResourceError(
                "Enrichment action code already exists"
            ) from exc
        return EnrichmentActionCreated(**cls._document(record).model_dump(), secret=secret)

    @classmethod
    def list(cls, *, skip: int, limit: int, include_deleted: bool = False) -> EnrichmentActionPage:
        query = {} if include_deleted else {"deleted_at": None}
        collection = cls._collection()
        total = collection.count_documents(query)
        rows = list(collection.find(query).sort("updated_at", DESCENDING).skip(skip).limit(limit))
        return EnrichmentActionPage(
            items=[cls._document(row) for row in rows], total=total, skip=skip, limit=limit
        )

    @classmethod
    def get(cls, action_code: str, *, include_deleted: bool = False) -> EnrichmentActionDocument:
        query: dict[str, Any] = {"action_code": action_code}
        if not include_deleted:
            query["deleted_at"] = None
        record = cls._collection().find_one(query)
        if not record:
            raise ResourceNotFoundError("Enrichment action not found")
        return cls._document(record)

    @classmethod
    def update(cls, action_code: str, payload: EnrichmentActionUpdate, actor: str) -> EnrichmentActionDocument:
        current = cls._collection().find_one({"action_code": action_code, "deleted_at": None})
        if not current:
            raise ResourceNotFoundError("Enrichment action not found")
        cls._validate_tenants(payload.tenant_scope, payload.tenant_ids)
        values = {**payload.model_dump(mode="json"), "url": str(payload.url)}
        candidate = {**current, **values}
        values.update(
            configuration_checksum=cls._checksum(candidate),
            updated_at=datetime.now(timezone.utc),
            updated_by=actor,
        )
        cls._collection().update_one({"_id": current["_id"]}, {"$set": values})
        return cls.get(action_code)

    @classmethod
    def rotate(cls, action_code: str, actor: str) -> EnrichmentActionCreated:
        current = cls._collection().find_one({"action_code": action_code, "deleted_at": None})
        if not current:
            raise ResourceNotFoundError("Enrichment action not found")
        key_id = "eak_" + secrets.token_hex(12)
        secret = "easec_" + base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip("=")
        nonce, ciphertext = cls._encrypt(action_code, key_id, secret)
        candidate = {**current, "key_id": key_id}
        values = {
            "key_id": key_id,
            "nonce": nonce,
            "ciphertext": ciphertext,
            "aad_namespace": "tierx",
            "configuration_checksum": cls._checksum(candidate),
            "updated_at": datetime.now(timezone.utc),
            "updated_by": actor,
        }
        cls._collection().update_one({"_id": current["_id"]}, {"$set": values})
        return EnrichmentActionCreated(**cls.get(action_code).model_dump(), secret=secret)

    @classmethod
    def soft_delete(cls, action_code: str, actor: str) -> EnrichmentActionDocument:
        current = cls._collection().find_one({"action_code": action_code, "deleted_at": None})
        if not current:
            raise ResourceNotFoundError("Enrichment action not found")
        now = datetime.now(timezone.utc)
        candidate = {**current, "enabled": False}
        cls._collection().update_one(
            {"_id": current["_id"]},
            {"$set": {
                "enabled": False,
                "configuration_checksum": cls._checksum(candidate),
                "deleted_at": now,
                "updated_at": now,
                "updated_by": actor,
            }},
        )
        return cls._document(cls._collection().find_one({"_id": current["_id"]}))

    @classmethod
    def authorized_for_tenant(cls, tenant_id: str) -> list[EnrichmentActionDocument]:
        TenantService.get_tenant_by_id(tenant_id)
        query = {
            "enabled": True,
            "deleted_at": None,
            "$or": [
                {"tenant_scope": "ALL_TENANTS"},
                {"tenant_scope": "SELECTED_TENANTS", "tenant_ids": tenant_id},
            ],
        }
        return [cls._document(row) for row in cls._collection().find(query).sort("action_code", ASCENDING)]

    @classmethod
    def validate_playbook_codes(cls, tenant_id: str, codes: list[str]) -> None:
        if not codes:
            return
        allowed = {item.action_code for item in cls.authorized_for_tenant(tenant_id)}
        missing = [code for code in codes if code not in allowed]
        if missing:
            raise ValueError("Unauthorized or disabled enrichment action(s): " + ", ".join(missing))
