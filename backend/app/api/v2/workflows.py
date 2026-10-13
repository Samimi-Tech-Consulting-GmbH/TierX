"""Experimental tenant-scoped workflows; never writes V1 alert collections."""

import os
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from pymongo import ReturnDocument
from bson.codec_options import CodecOptions
from tierx_runtime import boolean, env_value
from tierx_workflows import (
    GraphError,
    NODE_TYPES,
    checksum,
    default_graph,
    validate_graph,
)
from tierx_workflows.examples import examples

from app.api.dependencies.auth import (
    get_current_user,
    require_tenant_admin,
    verify_tenant_access,
)
from app.db.mongodb import DatabaseManager
from app.models.tenant import Tenant


def enabled():
    if not boolean(env_value("ingestion_v2_enabled") or False):
        raise HTTPException(404, "Ingestion V2 is disabled")


router = APIRouter(
    prefix="/tenants/{tenant_id}",
    tags=["Ingestion V2"],
    dependencies=[Depends(enabled)],
)


def now():
    return datetime.now(timezone.utc)


def db_for(tenant_id):
    tenant = Tenant.objects(tenant_id=tenant_id).first()
    if not tenant or str(tenant.status) not in {"ACTIVE", "TenantStatus.ACTIVE"}:
        raise HTTPException(404, "Active tenant required")
    db = DatabaseManager.get_tenant_database(tenant.db_name).with_options(
        codec_options=CodecOptions(tz_aware=True)
    )
    for name, keys in [
        ("v2_flows", "flow_id"),
        ("v2_runs", "run_id"),
        ("v2_jobs", "job_id"),
        ("v2_alerts", "alert_id"),
        ("v2_clusters", "cluster_id"),
    ]:
        db[name].create_index(keys, unique=True)
    db.v2_revisions.create_index([("flow_id", 1), ("revision", 1)], unique=True)
    db.v2_bindings.create_index("binding_key", unique=True)
    db.v2_jobs.create_index([("state", 1), ("lease_expires_at", 1)])
    return db


def found(collection, query):
    row = collection.find_one(query, {"_id": 0})
    if not row:
        raise HTTPException(404, "Resource not found")
    return row


def check(graph):
    try:
        return validate_graph(graph)
    except (GraphError, TypeError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc


class Draft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=128)
    graph: dict
    expected_version: int | None = Field(None, ge=1)


class GraphBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    graph: dict


class Binding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    flow_id: str
    revision: int = Field(ge=1)
    source_system: str | None = None
    alert_type: str | None = None


class AlertInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    alert_type: str = Field(min_length=1, max_length=256)
    source_system: str = Field(min_length=1, max_length=64)
    raw_payload: dict
    timestamp: str | None = None
    flow_id: str | None = None
    draft_version: int | None = Field(None, ge=1)


def resources(db, graph, tenant_id):
    """Resolve and pin resources; cross-tenant IDs cannot resolve."""
    result = {"schemas": {}, "playbooks": {}, "actions": {}, "profiles": {}}
    platform = DatabaseManager.get_tenant_database("soc_mind_platform")
    for node in graph["nodes"]:
        cfg, kind = node.get("config", {}), node["type"]
        if cfg.get("schema_id"):
            query = {"schema_id": cfg["schema_id"], "deleted_at": None}
            if cfg.get("schema_version"):
                query["version"] = cfg["schema_version"]
            row = db.alert_type_schemas.find_one(
                query, {"_id": 0}, sort=[("version", -1)]
            )
            if not row:
                raise HTTPException(422, f"Unresolved schema on {node['id']}")
            result["schemas"][node["id"]] = row
        if cfg.get("playbook_id"):
            query = {"playbook_id": cfg["playbook_id"], "deleted_at": None}
            if cfg.get("version"):
                query["version"] = cfg["version"]
            result["playbooks"][node["id"]] = found(db.playbooks, query)
        codes = (
            [cfg["action_code"]]
            if kind == "enrichment_action" and cfg.get("action_code")
            else []
        )
        codes += [
            tool[7:]
            for tool in cfg.get("tools", [])
            if isinstance(tool, str) and tool.startswith("action:")
        ]
        for code in codes:
            action = found(
                platform.enrichment_actions,
                {"action_code": code, "enabled": True, "deleted_at": None},
            )
            if action.get(
                "tenant_scope"
            ) != "ALL_TENANTS" and tenant_id not in action.get("tenant_ids", []):
                raise HTTPException(403, "Action is not authorized for this tenant")
            result["actions"][code] = {
                k: v
                for k, v in action.items()
                if k not in {"ciphertext", "nonce", "secret"}
            }
        if kind in {"llm_analysis", "llm_tools"}:
            profile = found(
                platform.v2_llm_profiles,
                {"profile_code": cfg["profile_code"], "enabled": True},
            )
            if tenant_id not in profile["tenant_ids"] or not profile.get("tested"):
                raise HTTPException(422, "LLM profile must be authorized and tested")
            if kind == "llm_tools" and profile.get("tool_mode") == "disabled":
                raise HTTPException(422, "Profile does not support tool calling")
            result["profiles"][cfg["profile_code"]] = {
                k: v
                for k, v in profile.items()
                if k not in {"credentials", "test_error"}
            }
    return result


@router.get("/workflow-catalog")
def catalog(tenant_id=Depends(verify_tenant_access), user=Depends(get_current_user)):
    db_for(tenant_id)
    return {
        "format_version": "1.0",
        "node_types": sorted(NODE_TYPES),
        "default_graph": default_graph(),
        "examples": examples(),
    }


@router.get("/flows")
def list_flows(tenant_id=Depends(verify_tenant_access), user=Depends(get_current_user)):
    return {
        "items": list(
            db_for(tenant_id).v2_flows.find({}, {"_id": 0}).sort("updated_at", -1)
        )
    }


@router.post("/flows", status_code=201)
def create_flow(
    body: Draft,
    tenant_id=Depends(verify_tenant_access),
    user=Depends(require_tenant_admin),
):
    graph = check(body.graph)
    row = {
        "flow_id": str(uuid4()),
        "tenant_id": tenant_id,
        "name": body.name,
        "graph": graph,
        "draft_version": 1,
        "updated_at": now(),
        "updated_by": user.user_id,
    }
    db_for(tenant_id).v2_flows.insert_one(dict(row))
    return row


@router.put("/flows/{flow_id}")
def save_flow(
    flow_id: str,
    body: Draft,
    tenant_id=Depends(verify_tenant_access),
    user=Depends(require_tenant_admin),
):
    if body.expected_version is None:
        raise HTTPException(422, "expected_version required")
    row = db_for(tenant_id).v2_flows.find_one_and_update(
        {"flow_id": flow_id, "draft_version": body.expected_version},
        {
            "$set": {
                "name": body.name,
                "graph": check(body.graph),
                "updated_at": now(),
                "updated_by": user.user_id,
            },
            "$inc": {"draft_version": 1},
        },
        return_document=ReturnDocument.AFTER,
        projection={"_id": 0},
    )
    if not row:
        raise HTTPException(409, "Draft changed; reload before saving")
    return row


@router.post("/flows/validate")
def validate(
    body: GraphBody,
    tenant_id=Depends(verify_tenant_access),
    user=Depends(require_tenant_admin),
):
    graph = check(body.graph)
    pinned = resources(db_for(tenant_id), graph, tenant_id)
    return {
        "valid": True,
        "checksum": checksum(graph),
        "resources": {kind: sorted(items) for kind, items in pinned.items()},
    }


@router.post("/flows/import", status_code=201)
def import_flow(
    body: Draft,
    tenant_id=Depends(verify_tenant_access),
    user=Depends(require_tenant_admin),
):
    return create_flow(body, tenant_id, user)


@router.get("/flows/{flow_id}/export")
def export_flow(
    flow_id: str,
    tenant_id=Depends(verify_tenant_access),
    user=Depends(require_tenant_admin),
):
    row = found(db_for(tenant_id).v2_flows, {"flow_id": flow_id})
    return {"name": row["name"], "graph": row["graph"]}


@router.post("/flows/{flow_id}/publish")
def publish(
    flow_id: str,
    tenant_id=Depends(verify_tenant_access),
    user=Depends(require_tenant_admin),
):
    db = db_for(tenant_id)
    draft = found(db.v2_flows, {"flow_id": flow_id})
    graph = check(draft["graph"])
    pinned = resources(db, graph, tenant_id)
    # Draft version is an immutable revision identity; concurrent publication is idempotent.
    row = {
        "flow_id": flow_id,
        "revision": draft["draft_version"],
        "tenant_id": tenant_id,
        "graph": graph,
        "resources": pinned,
        "checksum": checksum(graph),
        "published_at": now(),
        "published_by": user.user_id,
    }
    db.v2_revisions.update_one(
        {"flow_id": flow_id, "revision": row["revision"]},
        {"$setOnInsert": row},
        upsert=True,
    )
    response = found(db.v2_revisions, {"flow_id": flow_id, "revision": row["revision"]})
    response.pop("resources", None)
    return response


@router.get("/flows/{flow_id}/revisions")
def revisions(
    flow_id: str,
    tenant_id=Depends(verify_tenant_access),
    user=Depends(get_current_user),
):
    db = db_for(tenant_id)
    found(db.v2_flows, {"flow_id": flow_id})
    return {
        "items": list(
            db.v2_revisions.find({"flow_id": flow_id}, {"_id": 0, "resources": 0}).sort(
                "revision", -1
            )
        )
    }


@router.put("/flow-bindings")
def bind(
    body: Binding,
    tenant_id=Depends(verify_tenant_access),
    user=Depends(require_tenant_admin),
):
    if bool(body.source_system) != bool(body.alert_type):
        raise HTTPException(422, "Override requires source and alert type")
    db = db_for(tenant_id)
    found(db.v2_revisions, {"flow_id": body.flow_id, "revision": body.revision})
    key = (
        checksum([body.source_system, body.alert_type])
        if body.source_system
        else "default"
    )
    row = {**body.model_dump(), "binding_key": key, "updated_at": now()}
    db.v2_bindings.update_one({"binding_key": key}, {"$set": row}, upsert=True)
    return row


@router.get("/flow-bindings")
def bindings(tenant_id=Depends(verify_tenant_access), user=Depends(get_current_user)):
    return {"items": list(db_for(tenant_id).v2_bindings.find({}, {"_id": 0}))}


@router.get("/llm-profiles")
def allowed_profiles(
    tenant_id=Depends(verify_tenant_access), user=Depends(get_current_user)
):
    db_for(tenant_id)
    platform = DatabaseManager.get_tenant_database("soc_mind_platform")
    return {
        "items": list(
            platform.v2_llm_profiles.find(
                {"tenant_ids": tenant_id, "enabled": True},
                {
                    "_id": 0,
                    "profile_code": 1,
                    "revision": 1,
                    "provider": 1,
                    "model": 1,
                    "tool_mode": 1,
                    "tested": 1,
                    "allow_external_data": 1,
                },
            )
        )
    }


@router.get("/clusters/{cluster_id}")
def get_cluster(
    cluster_id: str,
    tenant_id=Depends(verify_tenant_access),
    user=Depends(get_current_user),
):
    db = db_for(tenant_id)
    cluster = found(db.v2_clusters, {"cluster_id": cluster_id})
    members = list(
        db.v2_alerts.find(
            {"cluster_id": cluster_id},
            {"_id": 0, "raw_payload": 0, "playbook_snapshot": 0},
        ).sort("created_at", 1)
    )
    requests = list(
        db.v2_cluster_requests.find(
            {"message.cluster_id": cluster_id}, {"_id": 0}
        ).sort("requested_analysis_version", 1)
    )
    return {"cluster": cluster, "members": members, "requests": requests}


@router.post("/ingest", status_code=202)
def ingest(
    body: AlertInput,
    tenant_id=Depends(verify_tenant_access),
    user=Depends(require_tenant_admin),
):
    db = db_for(tenant_id)
    tenant = Tenant.objects(tenant_id=tenant_id).first()
    if body.source_system not in tenant.allowed_source_systems:
        raise HTTPException(422, "Source system is not allowed for this tenant")
    if len(__import__("json").dumps(body.raw_payload).encode()) > 256 * 1024:
        raise HTTPException(413, "V2 test alert exceeds 256 KiB")
    if body.flow_id:
        draft = found(db.v2_flows, {"flow_id": body.flow_id})
        if body.draft_version != draft["draft_version"]:
            raise HTTPException(409, "Test draft changed")
        revision = {
            "graph": check(draft["graph"]),
            "revision": f"draft-{draft['draft_version']}",
            "flow_id": body.flow_id,
        }
        revision["resources"] = resources(db, revision["graph"], tenant_id)
    else:
        binding = db.v2_bindings.find_one(
            {"binding_key": checksum([body.source_system, body.alert_type])}
        ) or db.v2_bindings.find_one({"binding_key": "default"})
        if not binding:
            raise HTTPException(422, "No V2 workflow binding")
        revision = found(
            db.v2_revisions,
            {"flow_id": binding["flow_id"], "revision": binding["revision"]},
        )
    schema = db.alert_type_schemas.find_one(
        {"alert_type": body.alert_type, "is_active": True, "deleted_at": None},
        {"_id": 0},
        sort=[("version", -1)],
    )
    snapshots = dict(revision["resources"])
    snapshots["active_schema"] = schema
    snapshots["tenant_settings"] = dict(getattr(tenant, "settings", {}) or {})
    snapshots["system_prompt"] = DatabaseManager.get_tenant_database(
        "soc_mind_platform"
    ).prompt_templates.find_one(
        {"template_id": "TIERX_ANALYSIS_DEFAULT", "is_active": True},
        {"_id": 0},
        sort=[("version", -1)],
    )
    run_id, alert_id = str(uuid4()), str(uuid4())
    row = {
        "run_id": run_id,
        "alert_id": alert_id,
        "tenant_id": tenant_id,
        "flow_id": revision["flow_id"],
        "revision": revision["revision"],
        "graph": revision["graph"],
        "resources": snapshots,
        "cohort": checksum(
            [revision["flow_id"], revision["revision"], checksum(revision["graph"])]
        ),
        "input": {
            "alert_type": body.alert_type,
            "source_system": body.source_system,
            "raw_payload": body.raw_payload,
        },
        "state": "PENDING",
        "created_at": now(),
        "created_by": user.user_id,
        "release_version": env_value("app_release_version") or "development",
        "release_sha": env_value("app_release_sha") or "development",
    }
    db.v2_runs.insert_one(dict(row))
    return {"alert_id": alert_id, "run_id": run_id, "state": "PENDING"}


@router.get("/runs")
def runs(
    skip: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
    tenant_id=Depends(verify_tenant_access),
    user=Depends(get_current_user),
):
    db = db_for(tenant_id)
    projection = {"_id": 0, "input": 0, "resources": 0, "graph": 0}
    return {
        "items": list(
            db.v2_runs.find({}, projection)
            .sort([("created_at", -1), ("run_id", 1)])
            .skip(skip)
            .limit(limit)
        ),
        "total": db.v2_runs.count_documents({}),
        "skip": skip,
        "limit": limit,
    }


@router.get("/runs/{run_id}")
def run_detail(
    run_id: str, tenant_id=Depends(verify_tenant_access), user=Depends(get_current_user)
):
    db = db_for(tenant_id)
    run = found(db.v2_runs, {"run_id": run_id})
    run.pop("resources", None)
    run.pop("input", None)
    run["nodes"] = list(
        db.v2_jobs.find({"run_id": run_id}, {"_id": 0, "lease_owner": 0}).sort(
            "created_at", 1
        )
    )
    run["alert"] = db.v2_alerts.find_one(
        {"alert_id": run["alert_id"]},
        {"_id": 0, "raw_payload": 0, "playbook_snapshot": 0},
    )
    if run["alert"] and run["alert"].get("cluster_id"):
        run["cluster"] = db.v2_clusters.find_one(
            {"cluster_id": run["alert"]["cluster_id"]}, {"_id": 0}
        )
    return run
