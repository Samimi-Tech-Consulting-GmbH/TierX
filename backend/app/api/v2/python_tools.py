"""Platform-admin-only reusable Python tools; user code is never executed here."""
from datetime import datetime, timezone
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
from jsonschema.exceptions import SchemaError, ValidationError
from tierx_workflows.graph import checksum
from tierx_workflows.python_tools import validate_definition, input_snapshot, ALERT_SCHEMA, CLUSTER_SCHEMA, INPUT_SCHEMA
from tierx_workflows.python_client import broker_request, execution_definition, validate_with_broker
from app.api.dependencies.auth import require_platform_admin
from app.api.v2.workflows import db_for
from app.db.mongodb import DatabaseManager

router = APIRouter(prefix="/admin/python-tools", tags=["Python tools"], dependencies=[Depends(require_platform_admin)])


class Definition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=4096)
    source: str = Field(min_length=1, max_length=65536)
    tenant_ids: list[str] = Field(max_length=1000)
    enabled: bool = True
    output_mode: str = "json"
    output_schema: dict = Field(default_factory=lambda: {"type": "object"})
    timeout_seconds: int = Field(default=30, ge=1, le=1800)
    destinations: list[dict] = Field(default_factory=list, max_length=32)
    expected_version: int = Field(default=0, ge=0)


class TestInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: str
    alert: dict
    cluster: dict | None = None
    members: list[dict] = Field(default_factory=list, max_length=100)


def database():
    db = DatabaseManager.get_tenant_database("soc_mind_platform")
    db.workflow_python_tools.create_index("code", unique=True)
    db.workflow_python_tool_revisions.create_index([("code", 1), ("revision", 1)], unique=True)
    return db


@router.get("")
def listing():
    return {"items": list(database().workflow_python_tools.find({}, {"_id": 0})),
        "contract_version": "1.0", "alert_schema": ALERT_SCHEMA, "cluster_schema": CLUSTER_SCHEMA, "input_schema": INPUT_SCHEMA}


@router.put("/{code}")
def save(code: str, body: Definition, user=Depends(require_platform_admin)):
    try:
        value = validate_definition({"code": code, **body.model_dump(exclude={"expected_version"})}, syntax=False)
        for tenant in body.tenant_ids:
            db_for(tenant)
    except (ValueError, TypeError, SchemaError, ValidationError) as exc:
        raise HTTPException(422, "Invalid Python tool definition") from exc
    value.update(draft_version=body.expected_version + 1, updated_at=datetime.now(timezone.utc), updated_by=user.user_id)
    db = database()
    try:
        if body.expected_version == 0:
            db.workflow_python_tools.insert_one(dict(value))
        elif not db.workflow_python_tools.update_one({"code": code, "draft_version": body.expected_version}, {"$set": value}).matched_count:
            raise HTTPException(409, "Draft changed; reload before saving")
    except DuplicateKeyError as exc:
        raise HTTPException(409, "Tool code already exists") from exc
    return db.workflow_python_tools.find_one({"code": code}, {"_id": 0})


@router.post("/{code}/publish")
async def publish(code: str, user=Depends(require_platform_admin)):
    db = database()
    row = db.workflow_python_tools.find_one({"code": code}, {"_id": 0})
    if not row:
        raise HTTPException(404, "Python tool not found")
    try:
        validation = await validate_with_broker(execution_definition(row))
    except ValueError as exc:
        status = 503 if str(exc).startswith(("PYTHON_RUNNER_", "RUNNER_")) else 422
        raise HTTPException(status, str(exc)) from exc
    revision = row["draft_version"]
    record = {**execution_definition(row), "revision": revision, "checksum": checksum(execution_definition(row)),
              "published_at": datetime.now(timezone.utc), "published_by": user.user_id, "validated_runtime_digest": validation["runtime_digest"]}
    db.workflow_python_tool_revisions.update_one({"code": code, "revision": revision}, {"$setOnInsert": record}, upsert=True)
    if not db.workflow_python_tools.update_one({"code": code, "draft_version": revision}, {"$set": {"active_revision": revision}}).matched_count:
        raise HTTPException(409, "Draft changed during publication")
    return record


@router.get("/{code}/versions")
def versions(code: str):
    return {"items": list(database().workflow_python_tool_revisions.find({"code": code}, {"_id": 0}).sort("revision", -1))}


@router.post("/{code}/test", status_code=202)
async def test(code: str, body: TestInput):
    db_for(body.tenant_id)
    row = database().workflow_python_tools.find_one({"code": code, "enabled": True, "tenant_ids": body.tenant_id}, {"_id": 0})
    if not row:
        raise HTTPException(404, "Authorized Python tool not found")
    if body.alert.get("tenant_id") != body.tenant_id:
        raise HTTPException(422, "Test alert tenant mismatch")
    try:
        data = input_snapshot(body.alert, body.cluster, body.members)
    except (ValueError, TypeError, KeyError, ValidationError) as exc:
        raise HTTPException(422, "Invalid Python input snapshot") from exc
    try:
        identity = checksum([body.tenant_id, code, str(uuid4())])
        result = await broker_request(identity, request={"definition": execution_definition(row), "input": data})
        database().workflow_python_test_calls.insert_one({"call_id": identity, "code": code, "tenant_id": body.tenant_id})
        return {"call_id": identity, **result}
    except ValueError as exc:
        raise HTTPException(503, "Python runner unavailable") from exc


@router.get("/{code}/tests/{call_id}")
async def test_result(code: str, call_id: str):
    if not database().workflow_python_test_calls.find_one({"call_id": call_id, "code": code}):
        raise HTTPException(404, "Test call not found")
    try:
        return await broker_request(call_id)
    except ValueError as exc:
        raise HTTPException(503, "Python runner unavailable") from exc


@router.delete("/{code}/tests/{call_id}")
async def cancel_test(code: str, call_id: str):
    if not database().workflow_python_test_calls.find_one({"call_id": call_id, "code": code}):
        raise HTTPException(404, "Test call not found")
    try:
        return await broker_request(call_id, cancel=True)
    except ValueError as exc:
        raise HTTPException(503, "Python runner unavailable; deadline still applies") from exc
