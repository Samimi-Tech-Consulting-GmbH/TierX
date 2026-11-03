import asyncio
import base64
import os
import re
import socket
import ipaddress
from datetime import datetime, timezone
from urllib.parse import urlsplit

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from pymongo import ReturnDocument
from tierx_runtime import env_value
from tierx_workflows.llm import infer

from app.api.dependencies.auth import require_platform_admin
from app.api.v2.workflows import enabled
from app.db.mongodb import DatabaseManager

router = APIRouter(
    prefix="/admin/llm-profiles",
    tags=["V2 LLM profiles"],
    dependencies=[Depends(enabled), Depends(require_platform_admin)],
)


class Profile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile_code: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    provider: str
    base_url: str = Field(max_length=2048)
    model: str = Field(min_length=1, max_length=256)
    tenant_ids: list[str] = Field(max_length=1000)
    allow_external_data: bool = False
    enabled: bool = True
    tool_mode: str = "disabled"
    temperature: float = Field(0, ge=0, le=2)
    max_tokens: int = Field(2048, ge=32, le=8192)
    timeout_seconds: int = Field(120, ge=1, le=300)
    api_key: str | None = Field(None, max_length=4096)
    expected_revision: int = Field(0, ge=0)


def collection():
    db = DatabaseManager.get_tenant_database("soc_mind_platform")
    db.v2_llm_profiles.create_index("profile_code", unique=True)
    db.v2_llm_profile_revisions.create_index(
        [("profile_code", 1), ("revision", 1)], unique=True
    )
    return db.v2_llm_profiles


def key():
    encoded = env_value("webhook_secret_encryption_key") or ""
    try:
        raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    except ValueError:
        raw = b""
    if len(raw) != 32:
        raise HTTPException(503, "Installation encryption key unavailable")
    return raw


def safe(row):
    return {k: v for k, v in row.items() if k not in {"_id", "credentials"}}


def decrypt(row):
    secret = row.get("credentials")
    if not secret:
        return None
    return (
        AESGCM(key())
        .decrypt(
            bytes.fromhex(secret["nonce"]),
            bytes.fromhex(secret["ciphertext"]),
            ("tierx:llm-profile:v1:" + row["profile_code"]).encode(),
        )
        .decode()
    )


@router.get("")
def profiles():
    return {"items": [safe(row) for row in collection().find({})]}


@router.put("/{profile_code}")
def save(profile_code: str, body: Profile, user=Depends(require_platform_admin)):
    if (
        body.profile_code != profile_code
        or body.provider not in {"ollama", "openai_compatible"}
        or body.tool_mode not in {"disabled", "native", "json_emulated"}
    ):
        raise HTTPException(422, "Invalid profile identity/provider/protocol")
    parts = urlsplit(body.base_url)
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
    ):
        raise HTTPException(422, "Invalid endpoint URL")
    if body.provider == "ollama" and parts.path not in {"", "/"}:
        raise HTTPException(422, "Ollama requires an origin URL")
    if parts.scheme == "https" and not body.allow_external_data:
        raise HTTPException(
            422, "HTTPS inference requires explicit external-data consent"
        )
    if parts.scheme == "http" and body.allow_external_data:
        raise HTTPException(422, "External inference requires HTTPS")
    if parts.scheme == "http" and parts.hostname not in {
        "ollama",
        "host.docker.internal",
        "localhost",
        "127.0.0.1",
        "::1",
    }:
        try:
            addresses = socket.getaddrinfo(
                parts.hostname, parts.port or 80, type=socket.SOCK_STREAM
            )
        except (socket.gaierror, ValueError) as exc:
            raise HTTPException(
                422, "Local inference endpoint could not be resolved"
            ) from exc
        if not addresses or any(
            ipaddress.ip_address(entry[4][0]).is_global for entry in addresses
        ):
            raise HTTPException(
                422, "Public inference endpoints require HTTPS and explicit consent"
            )
    col = collection()
    old = col.find_one({"profile_code": profile_code})
    if (old or {}).get("revision", 0) != body.expected_revision:
        raise HTTPException(409, "Profile changed")
    row = body.model_dump(exclude={"api_key", "expected_revision"})
    row.update(
        revision=body.expected_revision + 1,
        tested=False,
        updated_at=datetime.now(timezone.utc),
        updated_by=user.user_id,
    )
    if body.api_key:
        nonce = os.urandom(12)
        row["credentials"] = {
            "nonce": nonce.hex(),
            "ciphertext": AESGCM(key())
            .encrypt(
                nonce,
                body.api_key.encode(),
                ("tierx:llm-profile:v1:" + profile_code).encode(),
            )
            .hex(),
        }
    elif old and old.get("credentials"):
        row["credentials"] = old["credentials"]
    if old:
        updated = col.replace_one(
            {"profile_code": profile_code, "revision": body.expected_revision}, row
        )
        if not updated.modified_count:
            raise HTTPException(409, "Profile changed")
    else:
        try:
            col.insert_one(dict(row))
        except __import__("pymongo").errors.DuplicateKeyError as exc:
            raise HTTPException(409, "Profile already exists") from exc
    return safe(row)


@router.post("/{profile_code}/test")
async def test(profile_code: str):
    col = collection()
    row = col.find_one({"profile_code": profile_code})
    if not row:
        raise HTTPException(404, "Profile not found")
    schema = {
        "type": "object",
        "properties": {"ready": {"type": "boolean"}},
        "required": ["ready"],
        "additionalProperties": False,
    }
    try:
        result = await infer(
            row,
            [{"role": "user", "content": 'Return {"ready":true}'}],
            api_key=decrypt(row),
            schema=schema,
        )
        if result["result"] != {"ready": True}:
            raise ValueError("Invalid preflight")
        if row["tool_mode"] == "native":
            tool = {
                "type": "function",
                "function": {
                    "name": "echo",
                    "description": "Capability test only",
                    "parameters": {
                        "type": "object",
                        "properties": {"value": {"type": "string"}},
                        "required": ["value"],
                        "additionalProperties": False,
                    },
                },
            }
            result = await infer(
                row,
                [
                    {
                        "role": "user",
                        "content": "Call echo with value test. Do not answer without calling it.",
                    }
                ],
                api_key=decrypt(row),
                tools=[tool],
            )
            if (
                result["kind"] != "tool_calls"
                or result["calls"][0]["name"] != "echo"
                or result["calls"][0]["arguments"] != {"value": "test"}
            ):
                raise ValueError("Tool preflight failed")
        elif row["tool_mode"] == "json_emulated":
            echo = {
                "type": "object",
                "properties": {
                    "name": {"enum": ["echo"]},
                    "arguments": {
                        "type": "object",
                        "properties": {"value": {"enum": ["test"]}},
                        "required": ["value"],
                        "additionalProperties": False,
                    },
                },
                "required": ["name", "arguments"],
                "additionalProperties": False,
            }
            protocol = {
                "type": "object",
                "properties": {
                    "kind": {"enum": ["tool_calls"]},
                    "calls": {"type": "array", "items": echo},
                },
                "required": ["kind", "calls"],
                "additionalProperties": False,
            }
            result = await infer(
                row,
                [
                    {
                        "role": "user",
                        "content": 'Propose echo(value="test") using JSON: {"kind":"tool_calls","calls":[{"name":"echo","arguments":{"value":"test"}}]}. Do not execute anything.',
                    }
                ],
                api_key=decrypt(row),
                schema=protocol,
            )
            if result["result"] != {
                "kind": "tool_calls",
                "calls": [{"name": "echo", "arguments": {"value": "test"}}],
            }:
                raise ValueError("Emulated tool preflight failed")
        changed = col.update_one(
            {"profile_code": profile_code, "revision": row["revision"]},
            {"$set": {"tested": True}},
        )
        if not changed.matched_count:
            raise HTTPException(409, "Profile changed during test")
        row["tested"] = True
        row.pop("_id", None)
        DatabaseManager.get_tenant_database(
            "soc_mind_platform"
        ).v2_llm_profile_revisions.update_one(
            {"profile_code": profile_code, "revision": row["revision"]},
            {"$setOnInsert": row},
            upsert=True,
        )
        return {"ok": True, "profile": safe(row)}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            422, "Provider structured-output/tool capability test failed"
        ) from exc
