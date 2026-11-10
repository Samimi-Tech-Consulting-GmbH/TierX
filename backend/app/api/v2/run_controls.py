"""Tenant-isolated execution inspection and explicit analyst feedback."""
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from pymongo import ReturnDocument

from app.api.dependencies.auth import get_current_user, require_platform_admin, verify_tenant_access
from app.api.v2.workflows import db_for, enabled, found

router = APIRouter(prefix="/tenants/{tenant_id}", tags=["Workflow execution"], dependencies=[Depends(enabled)])


class Feedback(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["APPROVE", "ESCALATE", "CORRECT"]
    verdict: Literal["TRUE_POSITIVE", "FALSE_POSITIVE", "INCONCLUSIVE"] | None = None
    severity: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"] | None = None
    playbook_code: str | None = Field(default=None, max_length=64)
    claim_corrections: str = Field(default="", max_length=8192)
    benign_rule_proposal: str = Field(default="", max_length=8192)
    analysis_id: str | None = Field(default=None, max_length=128)


class AnalystDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    verdict: Literal["TRUE_POSITIVE", "FALSE_POSITIVE", "BENIGN", "INCONCLUSIVE"]
    rationale: str = Field(min_length=1, max_length=8192)


@router.put("/alerts/{alert_id}/decision")
def set_alert_decision(alert_id: str, body: AnalystDecision, tenant_id=Depends(verify_tenant_access), user=Depends(get_current_user)):
    db = db_for(tenant_id)
    found(db.alerts, {"alert_id": alert_id})
    row = {**body.model_dump(), "decision_id": str(uuid4()), "tenant_id": tenant_id, "alert_id": alert_id,
           "created_by": user.user_id, "created_at": datetime.now(timezone.utc)}
    db.workflow_analyst_decisions.insert_one(dict(row))
    db.alerts.update_one({"alert_id": alert_id}, {"$set": {"verdict": body.verdict, "analyst_decision": row}})
    return row


@router.post("/runs/{run_id}/cancel")
def cancel(run_id: str, tenant_id=Depends(verify_tenant_access), user=Depends(require_platform_admin)):
    db = db_for(tenant_id)
    run = found(db.v2_runs, {"run_id": run_id})
    root = run.get("root_run_id", run_id)
    now = datetime.now(timezone.utc)
    claimed = db.v2_runs.find_one_and_update(
        {"run_id": root, "state": {"$in": ["PENDING", "RUNNING"]}},
        {"$set": {"state": "CANCELLED", "completed_at": now, "cancelled_by": user.user_id}},
        return_document=ReturnDocument.AFTER,
    )
    if not claimed:
        raise HTTPException(409, "Root run is already terminal; cancellation was not applied")
    query = {"$or": [{"run_id": root}, {"root_run_id": root}], "state": {"$in": ["PENDING", "RUNNING"]}}
    identities = [root, *[row["run_id"] for row in db.v2_runs.find(query, {"run_id": 1})]]
    db.v2_runs.update_many(query, {"$set": {"state": "CANCELLED", "completed_at": now, "cancelled_by": user.user_id}})
    db.v2_jobs.update_many({"run_id": {"$in": identities}, "state": {"$in": ["PENDING", "WAITING", "RUNNING"]}},
        {"$set": {"state": "CANCELLED", "routed": True, "completed_at": now}})
    db.alerts.update_one({"alert_id": run["alert_id"], "run_id": root}, {"$set": {"workflow_state": "CANCELLED"}})
    db.alerts.update_one({"alert_id": run["alert_id"], "run_id": root, "analysis_status": {"$ne": "SUCCEEDED"}},
        {"$set": {"analysis_status": "FAILED", "status": "ERROR", "analysis_error": {"type": "CANCELLED"}, "updated_at": now}})
    return {"root_run_id": root, "state": "CANCELLED", "warning": "Already dispatched external requests cannot be recalled."}


@router.get("/alerts/{alert_id}/workflow-analyses")
def analyses(alert_id: str, skip: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=100),
             tenant_id=Depends(verify_tenant_access), user=Depends(get_current_user)):
    db = db_for(tenant_id)
    found(db.alerts, {"alert_id": alert_id})
    query = {"alert_id": alert_id, "persistence_state": {"$ne": "DISCARDED"}}
    return {"items": list(db.v2_alert_analyses.find(query, {"_id": 0}).sort([("created_at", -1), ("analysis_id", 1)]).skip(skip).limit(limit)),
        "total": db.v2_alert_analyses.count_documents(query), "skip": skip, "limit": limit}


@router.get("/alerts/{alert_id}/feedback")
def feedback_list(alert_id: str, tenant_id=Depends(verify_tenant_access), user=Depends(get_current_user)):
    db = db_for(tenant_id)
    found(db.alerts, {"alert_id": alert_id})
    return {"items": list(db.workflow_feedback.find({"alert_id": alert_id}, {"_id": 0}).sort("created_at", -1).limit(100))}


@router.post("/alerts/{alert_id}/feedback", status_code=201)
def feedback_save(alert_id: str, body: Feedback, tenant_id=Depends(verify_tenant_access), user=Depends(get_current_user)):
    db = db_for(tenant_id)
    found(db.alerts, {"alert_id": alert_id})
    if body.analysis_id and not db.v2_alert_analyses.find_one({"alert_id": alert_id, "analysis_id": body.analysis_id,
            "persistence_state": {"$ne": "DISCARDED"}}):
        raise HTTPException(422, "Analysis does not belong to this alert")
    row = {**body.model_dump(), "feedback_id": str(uuid4()), "tenant_id": tenant_id, "alert_id": alert_id,
           "created_by": user.user_id, "created_at": datetime.now(timezone.utc), "approval_state": "RECORDED"}
    db.workflow_feedback.create_index([("alert_id", 1), ("created_at", -1)])
    db.workflow_feedback.insert_one(dict(row))
    # Feedback is evidence, not an automatic model update or approved benign rule.
    return row
