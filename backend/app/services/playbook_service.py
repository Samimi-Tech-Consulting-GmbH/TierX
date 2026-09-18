from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, List, Optional
from uuid import uuid4

import yaml
from pymongo import ASCENDING, DESCENDING
from pydantic import ValidationError

from app.models.playbook import Playbook
from app.db.mongodb import DatabaseManager
from app.schemas.playbook import (
    PlaybookDefinitionPayload,
    PlaybookDocument,
    PlaybookListItem,
    PlaybookReplace,
    PlaybookVersionSummary,
    PlaybookStats,
)
from app.core.errors import ResourceNotFoundError
from app.services.tenant_service import TenantService

logger = logging.getLogger(__name__)

# Server-owned or form-owned; never taken from YAML alone.
STRIPPED_FROM_YAML_KEYS = frozenset(
    {
        "playbook_id",
        "tenant_id",
        "playbook_name",
        "version",
        "name",  # legacy / mistake
        "created_by",
        "created_at",
        "updated_at",
    }
)


class PlaybookValidationError(Exception):
    def __init__(self, errors: List[dict[str, Any]]):
        self.errors = errors
        super().__init__("Playbook validation failed")


def parse_yaml_document(raw: str) -> dict[str, Any]:
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        raise PlaybookValidationError(
            [{"loc": [], "msg": f"Invalid YAML: {e}", "type": "yaml_error"}]
        ) from e
    if data is None:
        raise PlaybookValidationError(
            [{"loc": [], "msg": "YAML document is empty", "type": "empty_yaml"}]
        )
    if not isinstance(data, dict):
        raise PlaybookValidationError(
            [
                {
                    "loc": [],
                    "msg": "YAML root must be a mapping/object",
                    "type": "type_error",
                }
            ]
        )
    return data


def validate_playbook_definition(data: dict[str, Any]) -> PlaybookDefinitionPayload:
    try:
        return PlaybookDefinitionPayload.model_validate(data)
    except ValidationError as e:
        formatted = []
        for err in e.errors():
            formatted.append(
                {
                    "loc": [str(x) for x in err["loc"]],
                    "msg": err["msg"],
                    "type": err["type"],
                }
            )
        raise PlaybookValidationError(formatted) from e


class PlaybookService:
    """All playbook persistence uses the tenant's dedicated Mongo database."""

    COLLECTION = Playbook._meta["collection"]

    @staticmethod
    def _tenant_database(tenant_id: str):
        tenant = TenantService.get_tenant_by_id(tenant_id)
        return DatabaseManager.get_tenant_database(str(tenant.db_name))

    @classmethod
    def _collection(cls, tenant_id: str):
        return cls._tenant_database(tenant_id)[cls.COLLECTION]

    @classmethod
    def reconcile_indexes_for_db_alias(cls, alias: str) -> None:
        """
        Drops the pre-versioning unique index on ``playbook_id`` alone if it still
        exists, then ensures current Playbook indexes. Without this, saving a second
        version raises DuplicateKeyError (often HTTP 500) because Mongo rejects two
        documents with the same ``playbook_id``.
        """
        # Kept for callers that already hold a legacy tenant alias.  Resolve
        # the database name once, then use the raw collection without binding
        # the shared MongoEngine model to another database.
        from mongoengine import connection

        db = connection.get_db(alias)
        coll = db[cls.COLLECTION]
        cls._reconcile_collection_indexes(coll, alias)

    @classmethod
    def _reconcile_collection_indexes(cls, coll: Any, label: str) -> None:
        dropped = False
        for spec in list(coll.list_indexes()):
            name = spec.get("name")
            if not name or name == "_id":
                continue
            key = dict(spec.get("key", {}))
            if spec.get("unique") and key == {"playbook_id": 1}:
                try:
                    coll.drop_index(name)
                    dropped = True
                    logger.info(
                        "Dropped legacy unique index %r on tenant playbooks (%s)",
                        name,
                        label,
                    )
                except Exception as e:
                    logger.warning("Could not drop legacy index %r: %s", name, e)
        if dropped:
            logger.info(
                "Playbook versioning requires compound unique (playbook_id, version); "
                "indexes re-checked for alias=%s",
                label,
            )
        coll.create_index(
            [("playbook_id", ASCENDING), ("version", ASCENDING)],
            unique=True,
        )
        coll.create_index([("tenant_id", ASCENDING)])
        coll.create_index([("is_active", ASCENDING)])
        coll.create_index([("updated_at", DESCENDING), ("playbook_id", ASCENDING)])
        coll.create_index([("is_active", ASCENDING), ("updated_at", DESCENDING)])

    @classmethod
    def reconcile_indexes_for_tenant(cls, tenant_id: str) -> None:
        cls._reconcile_collection_indexes(cls._collection(tenant_id), tenant_id)

    @classmethod
    def playbook_exists(cls, tenant_id: str, playbook_id: str) -> bool:
        return (
            cls._collection(tenant_id).find_one(
                {"playbook_id": playbook_id}, {"_id": 1}
            )
            is not None
        )

    @staticmethod
    def _to_document(playbook: dict[str, Any]) -> PlaybookDocument:
        doc_dict = dict(playbook)
        if doc_dict.get("_id") is not None:
            doc_dict["_id"] = str(doc_dict["_id"])
        return PlaybookDocument(**doc_dict)

    @staticmethod
    def _definition_from_yaml_text(yaml_text: str) -> PlaybookDefinitionPayload:
        data = parse_yaml_document(yaml_text.strip())
        for key in STRIPPED_FROM_YAML_KEYS:
            data.pop(key, None)
        return validate_playbook_definition(data)

    @staticmethod
    def _validate_enrichment_actions(tenant_id: str, codes: list[str]) -> None:
        from app.services.enrichment_action_service import EnrichmentActionService

        try:
            EnrichmentActionService.validate_playbook_codes(tenant_id, codes)
        except ValueError as exc:
            raise PlaybookValidationError(
                [
                    {
                        "loc": ["enrichment_actions"],
                        "msg": str(exc),
                        "type": "value_error",
                    }
                ]
            ) from exc

    @classmethod
    def create_from_yaml(
        cls,
        tenant_id: str,
        playbook_name_form: str,
        yaml_text: str,
        created_by: str,
    ) -> PlaybookDocument:
        trimmed_name = playbook_name_form.strip()
        if not trimmed_name:
            raise PlaybookValidationError(
                [
                    {
                        "loc": ["name"],
                        "msg": "playbook_name is required",
                        "type": "value_error",
                    }
                ]
            )

        definition = cls._definition_from_yaml_text(yaml_text)
        cls._validate_enrichment_actions(tenant_id, definition.enrichment_actions)

        cls.reconcile_indexes_for_tenant(tenant_id)

        now = datetime.now(timezone.utc)
        playbook_id = str(uuid4())
        playbook = {
            "playbook_id": playbook_id,
            "version": 1,
            "tenant_id": tenant_id,
            "playbook_name": trimmed_name,
            "actions": [
                action.model_dump(mode="json") for action in definition.actions
            ],
            "prompt": definition.prompt,
            "description": definition.description,
            "alert_types": list(definition.alert_types),
            "is_active": definition.is_active,
            "is_system": definition.is_system,
            "context_webhook": (
                definition.context_webhook.model_dump(mode="json")
                if definition.context_webhook
                else None
            ),
            "context_webhooks": (
                [
                    provider.model_dump(mode="json")
                    for provider in definition.context_webhooks
                ]
                if definition.context_webhooks is not None
                else None
            ),
            "enrichment_actions": list(definition.enrichment_actions),
            "knowledge_base": definition.knowledge_base.model_dump(),
            "created_by": created_by,
            "created_at": now,
            "updated_at": now,
        }
        inserted = cls._collection(tenant_id).insert_one(playbook)
        playbook["_id"] = inserted.inserted_id

        logger.info(
            "Created playbook %s v1 in tenant DB %s",
            playbook_id,
            tenant_id,
        )
        return cls._to_document(playbook)

    @classmethod
    def list_playbooks(
        cls,
        tenant_id: str,
        *,
        skip: int = 0,
        limit: int = 100,
        is_active: Optional[bool] = None,
        alert_type: Optional[str] = None,
    ) -> List[PlaybookListItem]:
        pipeline: List[dict[str, Any]] = [
            {"$addFields": {"version": {"$ifNull": ["$version", 1]}}},
            {"$sort": {"playbook_id": 1, "version": -1}},
            {"$group": {"_id": "$playbook_id", "doc": {"$first": "$$ROOT"}}},
            {"$replaceRoot": {"newRoot": "$doc"}},
        ]
        if is_active is not None:
            pipeline.append({"$match": {"is_active": is_active}})
        if alert_type is not None:
            pipeline.append({"$match": {"alert_types": alert_type}})
        pipeline.extend(
            [
                {"$sort": {"updated_at": -1}},
                {"$skip": skip},
                {"$limit": limit},
            ]
        )

        rows: List[PlaybookListItem] = []
        for raw in cls._collection(tenant_id).aggregate(pipeline):
            rows.append(
                PlaybookListItem(
                    playbook_id=raw["playbook_id"],
                    version=int(raw["version"]),
                    tenant_id=raw["tenant_id"],
                    playbook_name=raw["playbook_name"],
                    alert_types=list(raw.get("alert_types") or []),
                    is_active=raw["is_active"],
                    is_system=raw["is_system"],
                    context_webhook=raw.get("context_webhook"),
                    context_webhooks=raw.get("context_webhooks"),
                    enrichment_actions=list(raw.get("enrichment_actions") or []),
                    knowledge_base=raw.get("knowledge_base")
                    or {"enabled": False, "top_k": 5},
                    created_at=raw["created_at"],
                    updated_at=raw["updated_at"],
                )
            )
        return rows

    @classmethod
    def stats_values(cls, tenant_id: str) -> dict[str, Any]:
        latest = [
            {"$addFields": {"version": {"$ifNull": ["$version", 1]}}},
            {"$sort": {"playbook_id": 1, "version": -1}},
            {"$group": {"_id": "$playbook_id", "doc": {"$first": "$$ROOT"}}},
            {"$replaceRoot": {"newRoot": "$doc"}},
            {
                "$project": {
                    "_id": 0,
                    "is_active": 1,
                    "is_system": 1,
                    "alert_types": 1,
                }
            },
        ]
        rows = list(cls._collection(tenant_id).aggregate(latest))
        covered = {
            str(alert_type)
            for row in rows
            for alert_type in (row.get("alert_types") or [])
            if str(alert_type).strip()
        }
        return {
            "total_playbooks": len(rows),
            "active_playbooks": sum(bool(row.get("is_active")) for row in rows),
            "system_playbooks": sum(bool(row.get("is_system")) for row in rows),
            "alert_types": covered,
        }

    @classmethod
    def stats(cls, tenant_id: str) -> PlaybookStats:
        values = cls.stats_values(tenant_id)
        return PlaybookStats(
            total_playbooks=values["total_playbooks"],
            active_playbooks=values["active_playbooks"],
            system_playbooks=values["system_playbooks"],
            covered_alert_types=len(values["alert_types"]),
        )

    @classmethod
    def get_playbook(cls, tenant_id: str, playbook_id: str) -> PlaybookDocument:
        playbook = cls._collection(tenant_id).find_one(
            {"playbook_id": playbook_id}, sort=[("version", DESCENDING)]
        )
        if not playbook:
            raise ResourceNotFoundError("Playbook not found")
        return cls._to_document(playbook)

    @classmethod
    def list_playbook_versions(
        cls, tenant_id: str, playbook_id: str
    ) -> List[PlaybookVersionSummary]:
        rows = list(
            cls._collection(tenant_id)
            .find({"playbook_id": playbook_id})
            .sort("version", DESCENDING)
        )
        if not rows:
            raise ResourceNotFoundError("Playbook not found")
        return [
            PlaybookVersionSummary(
                playbook_id=playbook["playbook_id"],
                version=int(playbook.get("version") or 1),
                playbook_name=playbook["playbook_name"],
                alert_types=list(playbook.get("alert_types") or []),
                is_active=playbook["is_active"],
                is_system=playbook["is_system"],
                context_webhook=playbook.get("context_webhook"),
                context_webhooks=playbook.get("context_webhooks"),
                enrichment_actions=list(playbook.get("enrichment_actions") or []),
                knowledge_base=playbook.get("knowledge_base")
                or {"enabled": False, "top_k": 5},
                created_by=playbook["created_by"],
                created_at=playbook["created_at"],
                updated_at=playbook["updated_at"],
            )
            for playbook in rows
        ]

    @classmethod
    def replace_playbook(
        cls,
        tenant_id: str,
        playbook_id: str,
        payload: PlaybookReplace,
        created_by: str,
    ) -> PlaybookDocument:
        cls.reconcile_indexes_for_tenant(tenant_id)

        now = datetime.now(timezone.utc)
        latest = cls._collection(tenant_id).find_one(
            {"playbook_id": playbook_id}, sort=[("version", DESCENDING)]
        )
        if not latest:
            raise ResourceNotFoundError("Playbook not found")
        cls._validate_enrichment_actions(tenant_id, payload.enrichment_actions)
        next_v = int(latest.get("version") or 1) + 1
        snapshot = {
            "playbook_id": latest["playbook_id"],
            "version": next_v,
            "tenant_id": latest["tenant_id"],
            "playbook_name": payload.playbook_name.strip(),
            "actions": [action.model_dump(mode="json") for action in payload.actions],
            "prompt": payload.prompt,
            "description": payload.description,
            "alert_types": list(payload.alert_types),
            "is_active": payload.is_active,
            "is_system": payload.is_system,
            "context_webhook": (
                payload.context_webhook.model_dump(mode="json")
                if payload.context_webhook
                else None
            ),
            "context_webhooks": (
                [
                    provider.model_dump(mode="json")
                    for provider in payload.context_webhooks
                ]
                if payload.context_webhooks is not None
                else None
            ),
            "enrichment_actions": list(payload.enrichment_actions),
            "knowledge_base": payload.knowledge_base.model_dump(),
            "created_by": created_by,
            "created_at": now,
            "updated_at": now,
        }
        inserted = cls._collection(tenant_id).insert_one(snapshot)
        snapshot["_id"] = inserted.inserted_id
        return cls._to_document(snapshot)

    @classmethod
    def append_revision_from_yaml(
        cls,
        tenant_id: str,
        playbook_id: str,
        playbook_name_form: str,
        yaml_text: str,
        created_by: str,
    ) -> PlaybookDocument:
        trimmed_name = playbook_name_form.strip()
        if not trimmed_name:
            raise PlaybookValidationError(
                [
                    {
                        "loc": ["name"],
                        "msg": "playbook_name is required",
                        "type": "value_error",
                    }
                ]
            )
        definition = cls._definition_from_yaml_text(yaml_text)
        cls._validate_enrichment_actions(tenant_id, definition.enrichment_actions)

        cls.reconcile_indexes_for_tenant(tenant_id)

        now = datetime.now(timezone.utc)
        latest = cls._collection(tenant_id).find_one(
            {"playbook_id": playbook_id}, sort=[("version", DESCENDING)]
        )
        if not latest:
            raise ResourceNotFoundError("Playbook not found")
        next_v = int(latest.get("version") or 1) + 1
        snapshot = {
            "playbook_id": latest["playbook_id"],
            "version": next_v,
            "tenant_id": latest["tenant_id"],
            "playbook_name": trimmed_name,
            "actions": [
                action.model_dump(mode="json") for action in definition.actions
            ],
            "prompt": definition.prompt,
            "description": definition.description,
            "alert_types": list(definition.alert_types),
            "is_active": definition.is_active,
            "is_system": definition.is_system,
            "context_webhook": (
                definition.context_webhook.model_dump(mode="json")
                if definition.context_webhook
                else None
            ),
            "context_webhooks": (
                [
                    provider.model_dump(mode="json")
                    for provider in definition.context_webhooks
                ]
                if definition.context_webhooks is not None
                else None
            ),
            "enrichment_actions": list(definition.enrichment_actions),
            "knowledge_base": definition.knowledge_base.model_dump(),
            "created_by": created_by,
            "created_at": now,
            "updated_at": now,
        }
        inserted = cls._collection(tenant_id).insert_one(snapshot)
        snapshot["_id"] = inserted.inserted_id

        logger.info(
            "Appended playbook %s v%s (YAML)",
            playbook_id,
            next_v,
        )
        return cls._to_document(snapshot)

    @classmethod
    def soft_delete(cls, tenant_id: str, playbook_id: str) -> PlaybookDocument:
        now = datetime.now(timezone.utc)
        collection = cls._collection(tenant_id)
        if collection.find_one({"playbook_id": playbook_id}, {"_id": 1}) is None:
            raise ResourceNotFoundError("Playbook not found")
        collection.update_many(
            {"playbook_id": playbook_id},
            {"$set": {"is_active": False, "updated_at": now}},
        )
        snapshot = collection.find_one(
            {"playbook_id": playbook_id}, sort=[("version", DESCENDING)]
        )
        if not snapshot:
            raise ResourceNotFoundError("Playbook not found")
        return cls._to_document(snapshot)
