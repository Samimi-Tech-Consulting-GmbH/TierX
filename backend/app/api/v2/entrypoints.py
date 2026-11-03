"""Explicit workflow ingestion: stable URLs, hashed credentials, immutable runs."""
import hashlib
import hmac
from copy import deepcopy
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid4, uuid5

from fastapi import APIRouter, Header, HTTPException
from pymongo.errors import DuplicateKeyError
from tierx_runtime import env_value
from tierx_workflows.graph import canonical, value_at
from tierx_workflows.definitions import GraphError

from app.api.v2.definitions import platform, published
from app.api.v2.workflows import AlertInput, db_for, enabled
from app.models.tenant import Tenant

router = APIRouter(prefix="/workflows", tags=["Workflow ingestion"])


def authorize(code, tenant_id, authorization):
    enabled()
    entry = platform().workflow_entries.find_one({"code": code, "tenant_id": tenant_id, "enabled": True})
    token = authorization[7:] if authorization.startswith("Bearer ") else ""
    actual = hashlib.sha256(token.encode()).hexdigest()
    if not token or not entry or not hmac.compare_digest(entry["token_hash"], actual):
        raise HTTPException(401, "Invalid workflow ingestion credential")
    return entry


def active(code, tenant_id):
    try:
        definition = published("workflow", code)
    except GraphError as exc:
        raise HTTPException(409, "Workflow is not published or enabled") from exc
    if tenant_id not in definition["tenant_ids"]:
        raise HTTPException(403, "Workflow is not assigned to tenant")
    db = db_for(tenant_id)
    revision = db.v2_revisions.find_one({"flow_id": f"workflow:{code}", "revision": definition["revision"]}, {"_id": 0})
    if not revision:
        raise HTTPException(409, "Workflow revision is unavailable for tenant")
    return db, revision


def envelope(revision, body):
    cfg = next(node["config"] for node in revision["graph"]["nodes"] if node["type"] == "entry")
    if cfg.get("input_mode", "envelope") == "raw":
        body = {"source_system": cfg["source_system"], "alert_type": cfg["alert_type"],
                "raw_payload": body, "timestamp": value_at(body, cfg["timestamp_path"])}
    try:
        value = AlertInput.model_validate(body)
        if value.flow_id or value.draft_version:
            raise ValueError("Caller cannot select workflow or revision")
        timestamp = datetime.fromisoformat(str(value.timestamp).replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            raise ValueError("Original event timestamp must include timezone")
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, "Valid alert and original event timestamp with timezone required") from exc
    payload = value.model_dump(exclude={"flow_id", "draft_version"})
    payload["timestamp"] = timestamp.astimezone(timezone.utc).isoformat()
    return payload


def enqueue(code, tenant_id, body, *, identity, idempotency_key=None, source_reference=None):
    db, revision = active(code, tenant_id)
    payload = envelope(revision, body)
    tenant = Tenant.objects(tenant_id=tenant_id).first()
    if payload["source_system"] not in tenant.allowed_source_systems:
        raise HTTPException(422, "Source system is not allowed for tenant")
    if len(canonical(payload)) > 256 * 1024:
        raise HTTPException(413, "Alert exceeds 256 KiB")
    if idempotency_key is not None and not 1 <= len(idempotency_key) <= 128:
        raise HTTPException(422, "Idempotency key must contain 1–128 characters")
    digest = hashlib.sha256(canonical(payload)).hexdigest()
    identity_key = hashlib.sha256(canonical([code, tenant_id, identity, idempotency_key])).hexdigest() if idempotency_key else str(uuid4())
    run_id, alert_id = str(uuid5(NAMESPACE_URL, "tierx:run:" + identity_key)), str(uuid5(NAMESPACE_URL, "tierx:alert:" + identity_key))
    snapshots = deepcopy(revision["resources"])
    snapshots["active_schema"] = db.alert_type_schemas.find_one(
        {"alert_type": payload["alert_type"], "is_active": True, "deleted_at": None}, {"_id": 0}, sort=[("version", -1)])
    snapshots["tenant_settings"] = dict(getattr(tenant, "settings", {}) or {})
    snapshots["system_prompt"] = platform().prompt_templates.find_one(
        {"template_id": "TIERX_ANALYSIS_DEFAULT", "is_active": True}, {"_id": 0}, sort=[("version", -1)])
    now = datetime.now(timezone.utc)
    row = {"run_id": run_id, "root_run_id": run_id, "alert_id": alert_id, "tenant_id": tenant_id,
           "flow_id": revision["flow_id"], "definition_code": code,
           "definition_ref": revision["bundle"]["root"], "revision": revision["revision"],
           "graph": revision["graph"], "resources": snapshots, "bundle": revision["bundle"],
           "cohort": "workflow-runtime", "input": payload,
           "source_reference": source_reference, "state": "PENDING", "created_at": now,
           "created_by": identity, "payload_sha256": digest, "depth": 0, "max_calls": 100,
           "release_version": env_value("app_release_version") or "development",
           "release_sha": env_value("app_release_sha") or "development"}
    try:
        db.v2_runs.insert_one(row)
    except DuplicateKeyError:
        previous = db.v2_runs.find_one({"run_id": run_id})
        if not previous or previous["payload_sha256"] != digest:
            raise HTTPException(409, "Idempotency key was already used for different input")
    return {"alert_id": alert_id, "run_id": run_id, "state": "PENDING",
            "trace_url": f"/dashboard/admin/workflows/runs/{tenant_id}/{run_id}"}


@router.get("/{code}/tenants/{tenant_id}/connection")
def connection(code: str, tenant_id: str, authorization: str = Header(default="")):
    authorize(code, tenant_id, authorization)
    _, row = active(code, tenant_id)
    return {"workflow_code": code, "tenant_id": tenant_id, "revision": row["revision"], "configured": True}


@router.post("/{code}/tenants/{tenant_id}/ingest", status_code=202)
def ingest(code: str, tenant_id: str, body: dict, authorization: str = Header(default=""),
           idempotency_key: str | None = Header(default=None)):
    entry = authorize(code, tenant_id, authorization)
    return enqueue(code, tenant_id, body, identity="workflow-entry:" + entry["token_hash"], idempotency_key=idempotency_key)
