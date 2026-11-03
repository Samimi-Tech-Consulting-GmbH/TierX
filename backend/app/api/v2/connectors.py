"""Platform-owned connector definitions and explicitly approved tool schemas."""

import os
from datetime import datetime, timezone
from typing import Literal

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from pymongo.errors import DuplicateKeyError
from tierx_workflows.connectors import (
    ConnectorClient,
    ConnectorError,
    destination,
    validate_schema,
)

from app.api.dependencies.auth import require_platform_admin
from app.api.v2.llm_profiles import key
from app.api.v2.workflows import enabled
from app.db.mongodb import DatabaseManager

router = APIRouter(
    prefix="/admin/connectors",
    tags=["Workflow connectors"],
    dependencies=[Depends(enabled), Depends(require_platform_admin)],
)


class Tool(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    description: str = Field(max_length=1024)
    input_schema: dict
    output_schema: dict
    retry_safe: bool = False


class Connector(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["rest", "mcp"]
    name: str = Field(min_length=1, max_length=128)
    url: str = Field(max_length=2048)
    tenant_ids: list[str] = Field(max_length=1000)
    enabled: bool = True
    timeout_seconds: int = Field(30, ge=1, le=1800)
    tools: list[Tool] = Field(default_factory=list, max_length=100)
    credential: str | None = Field(None, max_length=4096)
    expected_revision: int = Field(0, ge=0)


def database():
    db = DatabaseManager.get_tenant_database("soc_mind_platform")
    db.v2_connectors.create_index("connector_code", unique=True)
    db.v2_connector_revisions.create_index(
        [("connector_code", 1), ("revision", 1)], unique=True
    )
    return db


def safe(row):
    return {k: v for k, v in row.items() if k not in {"_id", "credentials"}}


def decrypt(row):
    value = row.get("credentials")
    if not value:
        return None
    return (
        AESGCM(key())
        .decrypt(
            bytes.fromhex(value["nonce"]),
            bytes.fromhex(value["ciphertext"]),
            ("tierx:connector:v1:" + row["connector_code"]).encode(),
        )
        .decode()
    )


@router.get("")
def listing():
    return {"items": [safe(row) for row in database().v2_connectors.find({})]}


@router.put("/{code}")
async def save(code: str, body: Connector, user=Depends(require_platform_admin)):
    import re

    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", code):
        raise HTTPException(422, "Invalid connector code")
    try:
        await destination(body.url)
        for tool in body.tools:
            validate_schema(tool.input_schema)
            validate_schema(tool.output_schema)
    except Exception as exc:
        raise HTTPException(422, "Invalid connector destination or schema") from exc
    if len({tool.name for tool in body.tools}) != len(body.tools):
        raise HTTPException(422, "Tool names must be unique")
    db = database()
    old = db.v2_connectors.find_one({"connector_code": code})
    if (old or {}).get("revision", 0) != body.expected_revision:
        raise HTTPException(409, "Connector changed")
    row = body.model_dump(exclude={"credential", "expected_revision"})
    row.update(
        connector_code=code,
        revision=body.expected_revision + 1,
        updated_by=user.user_id,
        updated_at=datetime.now(timezone.utc),
    )
    if body.credential is not None:
        if body.credential:
            nonce = os.urandom(12)
            row["credentials"] = {
                "nonce": nonce.hex(),
                "ciphertext": AESGCM(key())
                .encrypt(
                    nonce,
                    body.credential.encode(),
                    ("tierx:connector:v1:" + code).encode(),
                )
                .hex(),
            }
    elif old and old.get("credentials"):
        row["credentials"] = old["credentials"]
    try:
        if old:
            changed = db.v2_connectors.replace_one(
                {"connector_code": code, "revision": body.expected_revision}, row
            )
            if not changed.matched_count:
                raise HTTPException(409, "Connector changed")
        else:
            db.v2_connectors.insert_one(dict(row))
    except DuplicateKeyError as exc:
        raise HTTPException(409, "Connector changed") from exc
    db.v2_connector_revisions.update_one(
        {"connector_code": code, "revision": row["revision"]},
        {"$setOnInsert": safe(row)},
        upsert=True,
    )
    return safe(row)


@router.post("/{code}/discover")
async def discover(code: str):
    row = database().v2_connectors.find_one({"connector_code": code, "enabled": True})
    if not row:
        raise HTTPException(404, "Connector not found")
    if row["kind"] != "mcp":
        raise HTTPException(422, "Discovery requires MCP")
    try:
        tools = await ConnectorClient(row, decrypt(row)).discover()
        return {
            "tools": tools,
            "approved": False,
            "message": "Select and save approved tool schemas explicitly.",
        }
    except ConnectorError as exc:
        raise HTTPException(502, str(exc)) from exc
