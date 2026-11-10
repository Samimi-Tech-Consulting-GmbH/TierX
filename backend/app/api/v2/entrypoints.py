"""Explicit workflow ingestion: stable URLs, hashed credentials, immutable runs."""
import hashlib
import hmac
from copy import deepcopy
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid4, uuid5

from fastapi import APIRouter, Depends, Header, HTTPException
from pymongo.errors import DuplicateKeyError
from pydantic import BaseModel, Field
from tierx_runtime import env_value
from tierx_workflows.graph import canonical, value_at
from tierx_workflows.definitions import GraphError

from app.api.v2.definitions import platform, published
from app.api.v2.workflows import AlertInput, db_for, engine_enabled as enabled
from app.models.tenant import Tenant
from app.api.v1.jira_integrations import require_jira_integration
from app.schemas.jira_integration import JiraSubmissionCreate, JiraCommentReceipt

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


def enqueue(code, tenant_id, body, *, identity, idempotency_key=None, source_reference=None, expected_revision=None):
    db, revision = active(code, tenant_id)
    if expected_revision is not None and expected_revision != revision["revision"]:
        raise HTTPException(409, "Workflow changed during submission; retry")
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
            "trace_url": f"/dashboard/{tenant_id}/workflows/runs/{run_id}"}


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


def jira_entry(code, tenant_id, integration):
    enabled()
    entry = platform().workflow_entries.find_one({"code": code, "tenant_id": tenant_id, "enabled": True,
        "jira_connection_ids": integration["integration_id"]})
    if not entry:
        raise HTTPException(403, "Jira connection is not authorized for this workflow")
    return active(code, tenant_id)


def jira_record(code, tenant_id, submission_id, integration):
    jira_entry(code, tenant_id, integration)
    row = platform().workflow_jira_submissions.find_one({"submission_id": submission_id,
        "workflow_code": code, "tenant_id": tenant_id, "integration_id": integration["integration_id"]}, {"_id": 0})
    if not row:
        raise HTTPException(404, "Submission not found")
    run = db_for(tenant_id).v2_runs.find_one({"run_id": row["run_id"]})
    state = row["state"]
    delivery = platform().workflow_jira_deliveries.find_one({"submission_id": submission_id, "state": "PENDING"}, sort=[("created_at", 1), ("_id", 1)])
    if delivery:
        state = "DELIVERY_REQUESTED"
        row["analysis"], row["delivery_id"] = delivery["analysis"], str(delivery["_id"])
        row["comments"] = {key: value for key, value in row.get("comments", {}).items() if key != "FINAL"}
    elif row.get("alert_id"):
        alert = db_for(tenant_id).alerts.find_one({"alert_id": row["alert_id"]}, {"alert_analysis": 1})
        row["analysis"] = (alert or {}).get("alert_analysis")
    if state not in {"DELIVERY_REQUESTED", "DELIVERED", "FAILED"} and run:
        if run["state"] in {"FAILED", "CANCELLED"}:
            state = "FAILED"
            row["failure"] = {"failed_stage": "WORKFLOW", "error_type": (run.get("error") or {}).get("type", run["state"])}
        elif run["state"] in {"SUCCEEDED", "SUCCEEDED_WITH_WARNINGS"}:
            state = "COMPLETED"
    return {**{key: row.get(key) for key in ["submission_id", "alert_id", "run_id", "issue_key", "issue_updated_at",
                "comments", "source_system", "alert_type", "failure", "delivery_id"]},
        "state": state, "result": row.get("analysis"),
        "trace_path": f"/dashboard/{tenant_id}/workflows/runs/{row['run_id']}",
        "alert_path": f"/dashboard/{tenant_id}/alerts/{row['alert_id']}"}


@router.get("/{code}/tenants/{tenant_id}/jira/connection")
def jira_connection(code: str, tenant_id: str, integration=Depends(require_jira_integration)):
    _, revision = jira_entry(code, tenant_id, integration)
    return {"jira_cloud_id": integration["jira_cloud_id"], "name": integration["name"],
            "workflow_code": code, "revision": revision["revision"], "tenant_id": tenant_id}


@router.post("/{code}/tenants/{tenant_id}/jira/submissions", status_code=202)
def jira_submit(code: str, tenant_id: str, body: JiraSubmissionCreate, integration=Depends(require_jira_integration)):
    _, revision = jira_entry(code, tenant_id, integration)
    if body.jira_cloud_id != integration["jira_cloud_id"] or str(body.jira_site_url).rstrip("/") != str(integration.get("jira_site_url", "")).rstrip("/"):
        raise HTTPException(403, "Jira site does not match connection")
    cfg = next(node["config"] for node in revision["graph"]["nodes"] if node["type"] == "entry")
    if cfg.get("input_mode") != "raw":
        raise HTTPException(409, "Jira requires a workflow configured for raw source alerts")
    digest = hashlib.sha256(canonical(body.raw_alert)).hexdigest()
    submission_id = hashlib.sha256(canonical([integration["integration_id"], code, tenant_id,
        body.issue_id, digest, revision["revision"]])).hexdigest()
    provenance = {"type": "JIRA", "submission_id": submission_id, "integration_id": integration["integration_id"],
        "cloud_id": body.jira_cloud_id, "site_url": str(body.jira_site_url).rstrip("/"),
        "issue_id": body.issue_id, "issue_key": body.issue_key, "project_key": body.project_key,
        "content_source": body.raw_alert_source.kind, "content_sha256": digest}
    # Store the submission before queueing so a fast notify node always has a destination.
    collection = platform().workflow_jira_submissions
    collection.create_index("submission_id", unique=True)
    collection.update_one({"submission_id": submission_id}, {"$setOnInsert": {
        **provenance, "workflow_code": code, "tenant_id": tenant_id, "state": "PROCESSING", "comments": {},
        "issue_updated_at": body.issue_updated_at, "created_at": datetime.now(timezone.utc)}}, upsert=True)
    accepted = enqueue(code, tenant_id, body.raw_alert, identity="jira:" + integration["integration_id"],
        idempotency_key=submission_id, source_reference=provenance, expected_revision=revision["revision"])
    collection.update_one({"submission_id": submission_id}, {"$set": {
        "alert_id": accepted["alert_id"], "run_id": accepted["run_id"],
        "source_system": cfg["source_system"], "alert_type": cfg["alert_type"]}})
    return jira_record(code, tenant_id, submission_id, integration)


@router.get("/{code}/tenants/{tenant_id}/jira/submissions/{submission_id}")
def jira_status(code: str, tenant_id: str, submission_id: str, integration=Depends(require_jira_integration)):
    return jira_record(code, tenant_id, submission_id, integration)


class WorkflowJiraReceipt(JiraCommentReceipt):
    delivery_id: str | None = Field(default=None, max_length=64)


@router.post("/{code}/tenants/{tenant_id}/jira/submissions/{submission_id}/comments")
def jira_receipt(code: str, tenant_id: str, submission_id: str, body: WorkflowJiraReceipt, integration=Depends(require_jira_integration)):
    row = jira_record(code, tenant_id, submission_id, integration)
    kind = body.kind.value
    if kind == "FINAL" and row["state"] not in {"DELIVERY_REQUESTED", "DELIVERED"}:
        raise HTTPException(409, "No explicit workflow notification is pending")
    if kind == "FINAL":
        if not body.delivery_id:
            raise HTTPException(422, "Explicit notification delivery ID required")
        changed = platform().workflow_jira_deliveries.update_one({"_id": body.delivery_id,
            "submission_id": submission_id, "integration_id": integration["integration_id"]},
            {"$set": {"state": "DELIVERED", "jira_comment_id": body.jira_comment_id}})
        if not changed.matched_count:
            raise HTTPException(404, "Notification delivery not found")
    else:
        platform().workflow_jira_submissions.update_one({"submission_id": submission_id}, {"$set": {f"comments.{kind}": body.jira_comment_id}})
    return jira_record(code, tenant_id, submission_id, integration)
