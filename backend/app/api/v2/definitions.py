"""Platform-owned reusable definitions; runtime resources remain tenant-local."""
import hashlib
import secrets
from copy import deepcopy
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
from tierx_workflows.definitions import compile_bundle, validate_definition
from tierx_workflows.graph import GraphError, NODE_TYPES, checksum

from app.api.dependencies.auth import require_platform_admin
from app.api.v2.workflows import db_for, engine_enabled, resources
from app.db.mongodb import DatabaseManager

router = APIRouter(prefix="/admin/workflow-definitions", tags=["Workflow studio"],
                   dependencies=[Depends(engine_enabled), Depends(require_platform_admin)])


def now():
    return datetime.now(timezone.utc)


def platform():
    db = DatabaseManager.get_tenant_database("soc_mind_platform")
    db.workflow_definitions.create_index([("kind", 1), ("code", 1)], unique=True)
    db.workflow_definition_revisions.create_index([("kind", 1), ("code", 1), ("revision", 1)], unique=True)
    db.workflow_entries.create_index([("code", 1), ("tenant_id", 1)], unique=True)
    return db


class Definition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=4096)
    tenant_ids: list[str] = Field(max_length=1000)
    enabled: bool = True
    configuration: dict
    expected_version: int = Field(default=0, ge=0)


def published(kind, code, revision=None):
    db = platform()
    current = db.workflow_definitions.find_one({"kind": kind, "code": code, "enabled": True, "deleted_at": None})
    if not current:
        raise GraphError(f"Unavailable {kind} definition: {code}")
    row = db.workflow_definition_revisions.find_one(
        {"kind": kind, "code": code, "revision": revision or current.get("active_revision")}, {"_id": 0})
    if not row:
        raise GraphError(f"Publish referenced {kind} before use: {code}")
    # Revocation is immediate, but immutable graph/configuration revisions stay pinned.
    row["tenant_ids"], row["enabled"] = current["tenant_ids"], current["enabled"]
    return row


@router.get("")
def listing(kind: Literal["workflow", "playbook", "agent"] | None = None):
    from tierx_workflows.templates import templates
    query = {"deleted_at": None, **({"kind": kind} if kind else {})}
    return {"items": list(platform().workflow_definitions.find(query, {"_id": 0}).sort([("kind", 1), ("code", 1)])),
            "node_types": sorted(NODE_TYPES), "templates": templates()}


@router.put("/{kind}/{code}")
def save(kind: Literal["workflow", "playbook", "agent"], code: str, body: Definition,
         user=Depends(require_platform_admin)):
    from tierx_workflows.definitions import CODE
    if not CODE.fullmatch(code):
        raise HTTPException(422, "Invalid immutable definition code")
    try:
        config = validate_definition(kind, body.configuration)
        for tenant_id in set(body.tenant_ids):
            db_for(tenant_id)
    except (GraphError, TypeError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
    collection = platform().workflow_definitions
    row = {**body.model_dump(exclude={"expected_version"}), "configuration": config,
           "kind": kind, "code": code, "draft_version": body.expected_version + 1,
           "updated_at": now(), "updated_by": user.user_id}
    try:
        if body.expected_version == 0:
            collection.insert_one(deepcopy(row))
        else:
            changed = collection.update_one({"kind": kind, "code": code, "draft_version": body.expected_version,
                                             "deleted_at": None}, {"$set": row})
            if not changed.matched_count:
                raise HTTPException(409, "Definition changed; reload")
    except DuplicateKeyError as exc:
        raise HTTPException(409, "Definition already exists") from exc
    return collection.find_one({"kind": kind, "code": code}, {"_id": 0})


@router.get("/{kind}/{code}/revisions")
def revisions(kind: str, code: str):
    return {"items": list(platform().workflow_definition_revisions.find(
        {"kind": kind, "code": code}, {"_id": 0}).sort("revision", -1))}


@router.post("/{kind}/{code}/publish")
def publish(kind: str, code: str, user=Depends(require_platform_admin)):
    db = platform()
    draft = db.workflow_definitions.find_one({"kind": kind, "code": code, "deleted_at": None}, {"_id": 0})
    if not draft or not draft["enabled"]:
        raise HTTPException(404, "Enabled definition not found")
    draft_version = draft["draft_version"]
    counter = f"{kind}:{code}"
    db.workflow_publication_sequences.update_one({"_id": counter},
        {"$setOnInsert": {"value": draft.get("active_revision", 0)}}, upsert=True)
    revision = db.workflow_publication_sequences.find_one_and_update({"_id": counter},
        {"$inc": {"value": 1}}, return_document=ReturnDocument.AFTER)["value"]
    row = {**draft, "revision": revision, "published_at": now(), "published_by": user.user_id}
    compiled = {}
    try:
        for tenant_id in draft["tenant_ids"]:
            tenant = db_for(tenant_id)
            bundle = compile_bundle(row, published, tenant_id, lambda graph: resources(tenant, graph, tenant_id))
            compiled[tenant_id] = bundle
    except (GraphError, TypeError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
    # Immutable publication is idempotent; activation occurs only after every tenant validates.
    db.workflow_definition_revisions.update_one({"kind": kind, "code": code, "revision": revision},
                                               {"$setOnInsert": row}, upsert=True)
    for tenant_id, bundle in compiled.items():
        tenant = db_for(tenant_id)
        tenant.v2_revisions.update_one({"flow_id": f"{kind}:{code}", "revision": revision},
            {"$setOnInsert": {"flow_id": f"{kind}:{code}", "revision": revision,
                "definition_kind": kind, "definition_code": code, "tenant_id": tenant_id,
                "bundle": bundle, "graph": bundle["definitions"][bundle["root"]]["graph"],
                "resources": bundle["definitions"][bundle["root"]]["resources"],
                "published_at": now(), "checksum": checksum(bundle)}}, upsert=True)
    changed = db.workflow_definitions.update_one({"kind": kind, "code": code, "draft_version": draft_version,
                                                  "enabled": True, "deleted_at": None,
                                                  "$or": [{"active_revision": {"$exists": False}}, {"active_revision": {"$lt": revision}}]},
                                                 {"$set": {"active_revision": revision}})
    if not changed.matched_count:
        raise HTTPException(409, "Draft changed during publication; publish the current draft")
    return {"kind": kind, "code": code, "revision": revision, "activated": True}


@router.delete("/{kind}/{code}", status_code=204)
def delete(kind: str, code: str, user=Depends(require_platform_admin)):
    platform().workflow_definitions.update_one({"kind": kind, "code": code},
        {"$set": {"deleted_at": now(), "enabled": False, "updated_by": user.user_id}})


class EntryCredential(BaseModel):
    tenant_id: str
    jira_connection_ids: list[str] = Field(default_factory=list, max_length=100)


@router.post("/workflow/{code}/entry-credentials")
def entry_credentials(code: str, body: EntryCredential, user=Depends(require_platform_admin)):
    try:
        row = published("workflow", code)
    except GraphError as exc:
        raise HTTPException(422, str(exc)) from exc
    if body.tenant_id not in row["tenant_ids"]:
        raise HTTPException(403, "Workflow not assigned to tenant")
    db_for(body.tenant_id)
    for integration_id in set(body.jira_connection_ids):
        if not platform().jira_integrations.find_one({"integration_id": integration_id, "state": "ACTIVE"}):
            raise HTTPException(422, "Active Jira site connection required")
    token = secrets.token_urlsafe(32)
    platform().workflow_entries.update_one({"code": code, "tenant_id": body.tenant_id},
        {"$set": {"token_hash": hashlib.sha256(token.encode()).hexdigest(),
                  "jira_connection_ids": sorted(set(body.jira_connection_ids)), "enabled": True,
                  "updated_at": now(), "updated_by": user.user_id}}, upsert=True)
    return {"token": token, "path": f"/api/v2/workflows/{code}/tenants/{body.tenant_id}/ingest",
            "jira_path": f"/api/v2/workflows/{code}/tenants/{body.tenant_id}/jira/submissions"}


@router.delete("/workflow/{code}/entry-credentials/{tenant_id}", status_code=204)
def revoke_entry(code: str, tenant_id: str):
    platform().workflow_entries.update_one({"code": code, "tenant_id": tenant_id}, {"$set": {"enabled": False}})
