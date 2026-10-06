"""Durable first-run installation and platform configuration."""
import asyncio
import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timezone
from uuid import uuid4

import httpx
from fastapi import HTTPException
from pymongo import ReturnDocument
from tierx_runtime import COLLECTION, IDENTITY, boolean, effective, env_value, installed, validate
from app.db.mongodb import DatabaseManager
from app.services.user_service import UserService

logger = logging.getLogger(__name__)


class PlatformConfigurationService:
    @staticmethod
    def db():
        return DatabaseManager.get_tenant_database("soc_mind_platform")

    @classmethod
    def document(cls):
        return cls.db()[COLLECTION].find_one({"_id": IDENTITY})

    @classmethod
    def initialize(cls):
        collection = cls.db()[COLLECTION]
        document = cls.document()
        if installed(document):
            effective(document.get("values"))
            return
        if document and document.get("pending_admin"):
            cls.finish_pending(document)
            return
        # Existing installations never reopen setup or reset their users.
        if cls.db().users.find_one({"role": "PLATFORM_ADMIN"}):
            values, _ = effective()
            collection.update_one({"_id": IDENTITY}, {"$set": {
                "state": "INSTALLED", "values": values, "revision": 1,
                "updated_at": datetime.now(timezone.utc), "updated_by": "existing-installation"
            }, "$unset": {"token_hash": ""}}, upsert=True)
            return
        # Preserve legacy environment-driven bootstrap behavior.
        bootstrap = boolean(env_value("bootstrap_configured") or False)
        legacy = bool(env_value("platform_admin_email") and env_value("platform_admin_password"))
        if bootstrap or legacy:
            required = ["platform_admin_email", "platform_admin_password"]
            if bootstrap:
                required += ["public_url", "ollama_url", "ollama_model"]
            missing = [f"TIERX_{key.upper()}" for key in required if not env_value(key)]
            if missing:
                raise RuntimeError("Incomplete environment bootstrap: " + ", ".join(missing))
            values, _ = effective()
            if values["llm_analysis_enabled"]:
                # Startup remains fail-closed; validation must finish before completion.
                with httpx.Client(timeout=300, follow_redirects=False) as client:
                    cls.check_ollama(client, values)
            cls.reserve(env_value("platform_admin_email"), env_value("platform_admin_password"), values)
            return
        token = env_value("installation_token") or secrets.token_urlsafe(32)
        digest = hashlib.sha256(token.encode()).hexdigest()
        result = collection.update_one({"_id": IDENTITY}, {"$setOnInsert": {
            "state": "PENDING", "token_hash": digest, "revision": 0
        }}, upsert=True)
        if env_value("installation_token"):
            collection.update_one({"_id": IDENTITY, "state": "PENDING"}, {"$set": {"token_hash": digest}})
        elif result.upserted_id and cls.enabled():
            logger.warning("TierX one-time installation token: %s", token)

    @staticmethod
    def enabled():
        return boolean(env_value("installation_enabled") or "true")

    @classmethod
    def authorize_setup(cls, token):
        doc = cls.document()
        if installed(doc) or not cls.enabled():
            raise HTTPException(404, "Installation is unavailable")
        supplied = hashlib.sha256((token or "").encode()).hexdigest()
        if not doc or not hmac.compare_digest(supplied, doc.get("token_hash", "")):
            raise HTTPException(403, "Invalid installation token")
        return doc

    @classmethod
    def reserve(cls, email, password, values):
        from pydantic import TypeAdapter, EmailStr
        email = str(TypeAdapter(EmailStr).validate_python(email))
        if not 12 <= len(password) or len(password.encode("utf-8")) > 72:
            raise ValueError("Initial administrator password must be at least 12 characters and at most 72 UTF-8 bytes")
        values = validate(values)
        if cls.db().users.find_one({"email": email}):
            raise HTTPException(409, "Administrator email is already in use")
        pending = {"user_id": str(uuid4()), "email": email,
                   "hashed_password": UserService.hash_password(password),
                   "role": "PLATFORM_ADMIN", "tenant_id": None, "is_active": True,
                   "created_at": datetime.now(timezone.utc), "created_by": "installation"}
        cls.db()[COLLECTION].update_one({"_id": IDENTITY}, {"$setOnInsert": {"state": "PENDING", "revision": 0}}, upsert=True)
        doc = cls.db()[COLLECTION].find_one_and_update(
            {"_id": IDENTITY, "state": "PENDING"},
            {"$set": {"state": "COMPLETING", "pending_admin": pending, "pending_values": values}},
            return_document=ReturnDocument.AFTER,
        )
        if not doc:
            raise HTTPException(409, "Installation is already completed or completing")
        cls.finish_pending(doc)

    @classmethod
    def finish_pending(cls, doc):
        # The reserved identity and password hash survive crashes; no second admin is created.
        admin = doc["pending_admin"]
        cls.db().users.update_one({"user_id": admin["user_id"]}, {"$setOnInsert": admin}, upsert=True)
        cls.db()[COLLECTION].update_one({"_id": IDENTITY, "state": "COMPLETING"}, {
            "$set": {"state": "INSTALLED", "values": doc["pending_values"], "revision": 1,
                     "updated_by": admin["email"], "updated_at": datetime.now(timezone.utc)},
            "$unset": {"pending_admin": "", "pending_values": "", "token_hash": ""},
        })

    @staticmethod
    def check_ollama(client, values):
        try:
            response = client.get(values["ollama_url"] + "/api/tags")
            if response.status_code != 200:
                raise ValueError("Ollama model lookup failed")
            models = response.json().get("models", [])
            selected = next((m for m in models if m.get("name") == values["ollama_model"]), None)
            if not selected:
                raise ValueError("Selected Ollama model is unavailable")
            expected = env_value("ollama_model_digest")
            if expected and selected.get("digest") != expected:
                raise ValueError("Ollama model digest does not match deployment configuration")
            schema = {"type": "object", "properties": {"ready": {"type": "boolean"}}, "required": ["ready"]}
            result = client.post(values["ollama_url"] + "/api/generate", json={
                "model": values["ollama_model"], "prompt": 'Return {"ready":true}',
                "format": schema, "stream": False, "options": {"temperature": 0, "num_predict": 32}
            })
            if result.status_code != 200:
                raise ValueError("Ollama structured inference failed")
            import json
            if json.loads(result.json()["response"]) != {"ready": True}:
                raise ValueError("Ollama structured inference returned invalid output")
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise HTTPException(422, "Ollama connectivity/model/structured inference validation failed") from exc
        return {"ok": True, "model": values["ollama_model"]}

    @classmethod
    async def test(cls, values):
        def run():
            with httpx.Client(timeout=300, follow_redirects=False) as client:
                return cls.check_ollama(client, values)
        return await asyncio.to_thread(run)

    @classmethod
    def read(cls):
        doc = cls.document() or {}
        values, locked = effective(doc.get("values"))
        services = list(cls.db().service_heartbeats.find(
            {"applied_revision": {"$exists": True}}, {"_id": 0, "service": 1, "applied_revision": 1,
            "configuration_error": 1, "seen_at": 1}))
        for service in services:
            seen = service.get("seen_at")
            if seen and seen.tzinfo is None:
                seen = seen.replace(tzinfo=timezone.utc)
            service["seen_at"] = seen
            service["stale"] = not seen or (datetime.now(timezone.utc) - seen).total_seconds() > 30
        return {"values": values, "locked_fields": locked, "revision": doc.get("revision", 0),
                "services": services, "environment_managed": ["mongodb", "kafka", "internal_urls", "encryption_keys"]}

    @classmethod
    async def update(cls, values, expected_revision, actor):
        doc = cls.document()
        if not installed(doc):
            raise HTTPException(409, "Installation is incomplete")
        if doc["revision"] != expected_revision:
            raise HTTPException(409, "Settings changed; reload before saving")
        saved = {**doc["values"], **values}
        if (doc["values"].get("llm_analysis_enabled") and saved.get("llm_analysis_enabled")
                and values.get("correlation_enabled") is False):
            raise ValueError("Analysis requires correlation; disable analysis before disabling correlation")
        current, locked = effective(doc["values"])
        for key in locked:
            if key in values and values[key] != current[key]:
                raise HTTPException(422, f"{key} is managed by environment configuration")
            # Preserve the saved shadow value; removing an override restores it.
            saved[key] = doc["values"][key]
        if saved.get("llm_analysis_enabled"):
            if "correlation_enabled" in locked and not current["correlation_enabled"]:
                raise HTTPException(422, "Correlation is disabled by environment configuration")
            saved["correlation_enabled"] = True
        resolved, _ = effective(saved)
        if resolved["llm_analysis_enabled"]:
            await cls.test(resolved)
        result = cls.db()[COLLECTION].update_one({"_id": IDENTITY, "revision": expected_revision, "state": "INSTALLED"}, {
            "$set": {"values": validate(saved), "updated_at": datetime.now(timezone.utc), "updated_by": actor},
            "$inc": {"revision": 1},
        })
        if not result.matched_count:
            raise HTTPException(409, "Settings changed; reload before saving")
        return cls.read()
