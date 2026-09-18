from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import mongoengine as me
from fastapi import HTTPException, status
from pymongo import ASCENDING, ReturnDocument

from app.core.errors import ResourceNotFoundError
from app.db.mongodb import DatabaseManager
from app.models.tenant import Tenant
from app.schemas.analysis import (
    AnalysisRetryResponse,
    AnalysisRun,
    AnalysisRunPage,
    SystemPromptDocument,
)

RUNS_COLLECTION = "analysis_runs"
PROMPTS_COLLECTION = "prompt_templates"
SYSTEM_PROMPT_ID = "TIERX_ANALYSIS_DEFAULT"
LEGACY_SYSTEM_PROMPT_ID = "SOC_MIND_ANALYSIS_DEFAULT"
SYSTEM_PROMPT = (
    "Act as a SOC analyst. Use only the evidence in the supplied context and do "
    "not invent indicators or facts. Return only JSON matching the required "
    "schema. Summarize the activity, identify kill-chain stages supported by "
    "evidence, assign confidence HIGH, MEDIUM, or LOW, and recommend concrete "
    "next actions. State uncertainty when evidence is absent."
)


class AnalysisService:
    @staticmethod
    def _db(tenant_id: str):
        tenant = Tenant.objects(tenant_id=tenant_id).first()
        if not tenant:
            raise ResourceNotFoundError(f"Tenant with ID {tenant_id} not found")
        alias = DatabaseManager.get_tenant_db_alias(tenant.db_name)
        return me.connection.get_db(alias)

    @staticmethod
    def ensure_system_prompt() -> None:
        collection = me.connection.get_db("default")[PROMPTS_COLLECTION]
        collection.create_index(
            [("template_id", ASCENDING), ("version", ASCENDING)], unique=True
        )
        collection.create_index(
            [("template_id", ASCENDING), ("is_active", ASCENDING)]
        )
        now = datetime.now(timezone.utc)
        if not collection.find_one({"template_id": SYSTEM_PROMPT_ID}):
            legacy = collection.find_one(
                {"template_id": LEGACY_SYSTEM_PROMPT_ID, "is_active": True},
                {"_id": 0},
                sort=[("version", -1)],
            )
            if legacy:
                legacy.update(
                    template_id=SYSTEM_PROMPT_ID,
                    migrated_from_template_id=LEGACY_SYSTEM_PROMPT_ID,
                    created_by="tierx-prompt-migration",
                    updated_at=now,
                )
                collection.update_one(
                    {"template_id": SYSTEM_PROMPT_ID, "version": legacy["version"]},
                    {"$setOnInsert": legacy},
                    upsert=True,
                )
        if not collection.find_one({"template_id": SYSTEM_PROMPT_ID}):
            collection.update_one(
                {"template_id": SYSTEM_PROMPT_ID, "version": 1},
                {
                    "$setOnInsert": {
                        "template_id": SYSTEM_PROMPT_ID,
                        "version": 1,
                        "prompt": SYSTEM_PROMPT,
                        "is_active": True,
                        "created_by": "system-bootstrap",
                        "created_at": now,
                        "updated_at": now,
                    }
                },
                upsert=True,
            )

    @staticmethod
    def get_system_prompt() -> SystemPromptDocument:
        document = me.connection.get_db("default")[PROMPTS_COLLECTION].find_one(
            {"template_id": SYSTEM_PROMPT_ID, "is_active": True},
            {"_id": 0},
            sort=[("version", -1)],
        )
        if not document:
            raise ResourceNotFoundError("Active system analysis prompt not found")
        return SystemPromptDocument(**document)

    @staticmethod
    def update_system_prompt(
        prompt: str, created_by: str, expected_version: int | None
    ) -> SystemPromptDocument:
        collection = me.connection.get_db("default")[PROMPTS_COLLECTION]
        current = collection.find_one(
            {"template_id": SYSTEM_PROMPT_ID, "is_active": True},
            sort=[("version", -1)],
        )
        current_version = int(current.get("version", 0)) if current else 0
        if expected_version is not None and expected_version != current_version:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"System prompt version changed: expected {expected_version}, "
                    f"current is {current_version}"
                ),
            )
        now = datetime.now(timezone.utc)
        version = current_version + 1
        document = {
            "template_id": SYSTEM_PROMPT_ID,
            "version": version,
            "prompt": prompt.strip(),
            "is_active": True,
            "created_by": created_by,
            "created_at": now,
            "updated_at": now,
        }
        collection.insert_one(document)
        collection.update_many(
            {
                "template_id": SYSTEM_PROMPT_ID,
                "version": {"$ne": version},
                "is_active": True,
            },
            {"$set": {"is_active": False, "updated_at": now}},
        )
        return SystemPromptDocument(**document)

    @classmethod
    def list_runs(
        cls,
        tenant_id: str,
        scope_type: str,
        scope_id: str,
        *,
        skip: int,
        limit: int,
    ) -> AnalysisRunPage:
        query = {
            "analysis_scope_type": scope_type,
            "analysis_scope_id": scope_id,
        }
        collection = cls._db(tenant_id)[RUNS_COLLECTION]
        total = collection.count_documents(query)
        documents = list(
            collection.find(query, {"_id": 0})
            .sort(
                [
                    ("requested_analysis_version", -1),
                    ("retry_cycle", -1),
                    ("created_at", -1),
                ]
            )
            .skip(skip)
            .limit(limit)
        )
        return AnalysisRunPage(
            items=[AnalysisRun(**document) for document in documents],
            total=total,
        )

    @classmethod
    def retry(
        cls, tenant_id: str, scope_type: str, scope_id: str
    ) -> AnalysisRetryResponse:
        db = cls._db(tenant_id)
        target_collection = "alerts" if scope_type == "ALERT" else "clusters"
        target_key = "alert_id" if scope_type == "ALERT" else "cluster_id"
        target = db[target_collection].find_one(
            {target_key: scope_id},
            {"requested_analysis_version": 1, "cluster_id": 1},
        )
        if not target:
            raise ResourceNotFoundError(f"{scope_type.title()} analysis scope not found")
        if scope_type == "ALERT" and target.get("cluster_id"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Standalone alert analysis was superseded by a cluster.",
            )
        version = int(target.get("requested_analysis_version") or 0)
        if version < 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No analysis version has been requested for this scope.",
            )
        now = datetime.now(timezone.utc)
        run = db[RUNS_COLLECTION].find_one_and_update(
            {
                "analysis_scope_type": scope_type,
                "analysis_scope_id": scope_id,
                "requested_analysis_version": version,
                "state": "FAILED",
            },
            {
                "$inc": {"retry_cycle": 1},
                "$set": {
                    "state": "PENDING",
                    "attempts_in_cycle": 0,
                    "next_attempt_at": now,
                    "updated_at": now,
                },
                "$unset": {
                    "completed_at": "",
                    "lease_expires_at": "",
                    "last_error": "",
                },
            },
            return_document=ReturnDocument.AFTER,
        )
        if not run:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only the current FAILED analysis run can be retried.",
            )
        db[target_collection].update_one(
            {target_key: scope_id},
            {
                "$set": {
                    "analysis_status": "PENDING",
                    "analysis_error": None,
                    "updated_at": now,
                }
            },
        )
        return AnalysisRetryResponse(**run)
