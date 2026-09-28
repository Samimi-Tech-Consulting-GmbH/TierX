from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, List, Optional
from uuid import uuid4

import yaml
from pymongo import ASCENDING, DESCENDING
from pydantic import ValidationError

from app.db.mongodb import DatabaseManager
from app.models.alert_type_schema import AlertTypeSchema
from app.core.errors import DuplicateResourceError, ResourceNotFoundError
from app.schemas.alert_type_schema import (
    AlertTypeSchemaDocument,
    AlertTypeSchemaListResponse,
    AlertTypeSchemaYamlPayload,
)
from app.services.playbook_service import PlaybookService
from app.services.tenant_service import TenantService

logger = logging.getLogger(__name__)

STRIPPED_FROM_YAML_KEYS = frozenset(
    {
        "schema_id",
        "tenant_id",
        "playbook_id",
        "is_active",
        "created_by",
        "created_at",
        "updated_at",
        "status",
    }
)


class AlertTypeSchemaValidationError(Exception):
    def __init__(self, errors: List[dict[str, Any]]):
        self.errors = errors
        super().__init__("Alert-type schema validation failed")


class _DuplicateKeyAwareLoader(yaml.SafeLoader):
    """SafeLoader that rejects duplicate keys in any mapping.

    The default ``yaml.safe_load`` silently overwrites a key when it appears
    twice in the same mapping, which would otherwise let an alert-type schema
    YAML define ``host.hostname`` (or any other field) multiple times in
    ``field_mapping`` and silently drop all but the last value.
    """


def _strict_construct_mapping(
    loader: _DuplicateKeyAwareLoader, node: yaml.MappingNode, deep: bool = False
) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                None,
                None,
                f"duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_DuplicateKeyAwareLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _strict_construct_mapping,
)


def _parse_alert_type_schema_yaml(yaml_text: str) -> dict[str, Any]:
    try:
        data = yaml.load(yaml_text, Loader=_DuplicateKeyAwareLoader)
    except yaml.constructor.ConstructorError as e:
        line_hint = ""
        if e.problem_mark is not None:
            line_hint = f" (line {e.problem_mark.line + 1})"
        raise AlertTypeSchemaValidationError(
            [
                {
                    "loc": [],
                    "msg": f"Duplicate key in YAML{line_hint}: {e.problem}",
                    "type": "duplicate_key",
                }
            ]
        ) from e
    except yaml.YAMLError as e:
        raise AlertTypeSchemaValidationError(
            [{"loc": [], "msg": f"Invalid YAML: {e}", "type": "yaml_error"}]
        ) from e
    if data is None:
        raise AlertTypeSchemaValidationError(
            [{"loc": [], "msg": "YAML document is empty", "type": "empty_yaml"}]
        )
    if not isinstance(data, dict):
        raise AlertTypeSchemaValidationError(
            [{"loc": [], "msg": "YAML root must be a mapping/object", "type": "type_error"}]
        )
    return data


def _format_pydantic_errors(e: ValidationError) -> List[dict[str, Any]]:
    formatted = []
    for err in e.errors():
        formatted.append(
            {
                "loc": [str(x) for x in err["loc"]],
                "msg": err["msg"],
                "type": err["type"],
            }
        )
    return formatted


class AlertTypeSchemaService:
    COLLECTION = AlertTypeSchema._meta["collection"]

    @staticmethod
    def _tenant_database(tenant_id: str):
        tenant = TenantService.get_tenant_by_id(tenant_id)
        return DatabaseManager.get_tenant_database(str(tenant.db_name))

    @classmethod
    def _collection(cls, tenant_id: str):
        return cls._tenant_database(tenant_id)[cls.COLLECTION]

    @classmethod
    def reconcile_indexes_for_db_alias(cls, alias: str) -> None:
        # Kept for existing maintenance callers while CRUD uses raw collections.
        from mongoengine import connection

        cls._reconcile_collection_indexes(
            connection.get_db(alias)[cls.COLLECTION]
        )

    @staticmethod
    def _reconcile_collection_indexes(collection) -> None:
        collection.create_index(
            [("schema_id", ASCENDING)], unique=True, name="schema_id_1"
        )
        collection.create_index(
            [("alert_type", ASCENDING), ("version", ASCENDING)],
            unique=True,
            name="alert_type_1_version_1",
        )
        collection.create_index(
            [("tenant_id", ASCENDING)], name="tenant_id_1"
        )
        collection.create_index(
            [("updated_at", DESCENDING), ("schema_id", ASCENDING)],
            name="updated_at_-1_schema_id_1",
        )
        collection.create_index(
            [("is_active", ASCENDING), ("updated_at", DESCENDING)],
            name="is_active_1_updated_at_-1",
        )

    @classmethod
    def reconcile_indexes_for_tenant(cls, tenant_id: str) -> None:
        cls._reconcile_collection_indexes(cls._collection(tenant_id))

    @staticmethod
    def _to_document(raw: dict[str, Any]) -> AlertTypeSchemaDocument:
        raw = dict(raw)
        if "_id" in raw:
            raw["_id"] = str(raw["_id"])
        return AlertTypeSchemaDocument(**raw)

    @classmethod
    def definition_from_yaml_text(cls, yaml_text: str) -> AlertTypeSchemaYamlPayload:
        data = _parse_alert_type_schema_yaml(yaml_text.strip())
        for key in STRIPPED_FROM_YAML_KEYS:
            data.pop(key, None)
        try:
            return AlertTypeSchemaYamlPayload.model_validate(data)
        except ValidationError as e:
            raise AlertTypeSchemaValidationError(_format_pydantic_errors(e)) from e

    @staticmethod
    def _playbook_exists(tenant_id: str, playbook_id: str) -> bool:
        return PlaybookService.playbook_exists(tenant_id, playbook_id)

    @classmethod
    def create_from_yaml(
        cls,
        tenant_id: str,
        yaml_text: str,
        created_by: str,
        playbook_id: Optional[str],
    ) -> AlertTypeSchemaDocument:
        cls.reconcile_indexes_for_tenant(tenant_id)

        definition = cls.definition_from_yaml_text(yaml_text)
        pid = playbook_id.strip() if playbook_id else None
        if pid is not None and pid == "":
            pid = None
        if pid and not cls._playbook_exists(tenant_id, pid):
            raise AlertTypeSchemaValidationError(
                [
                    {
                        "loc": ["playbook_id"],
                        "msg": "No playbook with this id exists for the tenant",
                        "type": "value_error",
                    }
                ]
            )

        collection = cls._collection(tenant_id)
        if collection.find_one(
            {"alert_type": definition.alert_type, "version": definition.version}
        ):
            raise DuplicateResourceError(
                f"Schema version {definition.version!r} already exists for alert type "
                f"{definition.alert_type!r}"
            )

        now = datetime.now(timezone.utc)
        schema_uuid = str(uuid4())
        row = {
            "schema_id": schema_uuid,
            "tenant_id": tenant_id,
            "alert_type": definition.alert_type,
            "version": definition.version,
            "description": definition.description,
            "fields": [dict(f) for f in definition.fields],
            "critical_fields": list(definition.critical_fields),
            "field_mapping": dict(definition.field_mapping),
            "playbook_id": pid,
            "is_active": False,
            "severity": definition.severity,
            "created_by": created_by,
            "created_at": now,
            "updated_at": now,
        }
        result = collection.insert_one(row)
        row["_id"] = result.inserted_id
        logger.info(
            "Created alert-type schema %s (%s v%s) tenant=%s draft",
            schema_uuid,
            definition.alert_type,
            definition.version,
            tenant_id,
        )
        return cls._to_document(row)

    @classmethod
    def list_schemas(
        cls,
        tenant_id: str,
        *,
        skip: int = 0,
        limit: int = 100,
        is_active: Optional[bool] = None,
        alert_type: Optional[str] = None,
        alert_type_search: Optional[str] = None,
    ) -> AlertTypeSchemaListResponse:
        collection = cls._collection(tenant_id)
        query: dict[str, Any] = {"tenant_id": tenant_id}
        if is_active is not None:
            query["is_active"] = is_active
        if alert_type is not None:
            query["alert_type"] = alert_type
        q = (alert_type_search or "").strip()[:512]
        if q:
            pattern = re.compile(re.escape(q), re.IGNORECASE)
            query["$or"] = [
                {"alert_type": pattern},
                {"schema_id": pattern},
            ]
        total = collection.count_documents(query)
        if q:
            rows = list(
                collection.aggregate(
                    [
                        {"$match": query},
                        {
                            "$addFields": {
                                "_exact_rank": {
                                    "$cond": [
                                        {"$eq": ["$schema_id", q]},
                                        0,
                                        1,
                                    ]
                                }
                            }
                        },
                        {
                            "$sort": {
                                "_exact_rank": ASCENDING,
                                "updated_at": DESCENDING,
                                "schema_id": ASCENDING,
                            }
                        },
                        {"$skip": skip},
                        {"$limit": limit},
                        {"$project": {"_exact_rank": 0}},
                    ]
                )
            )
        else:
            rows = list(
                collection.find(query)
                .sort([("updated_at", DESCENDING), ("schema_id", ASCENDING)])
                .skip(skip)
                .limit(limit)
            )
        items = [cls._to_document(r) for r in rows]
        return AlertTypeSchemaListResponse(
            items=items, total=total, skip=skip, limit=limit
        )

    @classmethod
    def get_active_for_alert_type(
        cls, tenant_id: str, alert_type: str
    ) -> AlertTypeSchemaDocument:
        doc = cls._collection(tenant_id).find_one(
            {"tenant_id": tenant_id, "alert_type": alert_type, "is_active": True}
        )
        if not doc:
            raise ResourceNotFoundError(
                f"No active schema for alert type {alert_type!r}"
            )
        return cls._to_document(doc)

    @classmethod
    def list_history(
        cls, tenant_id: str, alert_type: str
    ) -> List[AlertTypeSchemaDocument]:
        collection = cls._collection(tenant_id)
        query = {"tenant_id": tenant_id, "alert_type": alert_type}
        if not collection.find_one(query):
            raise ResourceNotFoundError(
                f"No schema versions for alert type {alert_type!r}"
            )
        rows = collection.find(query).sort("created_at", DESCENDING)
        return [cls._to_document(r) for r in rows]

    @classmethod
    def get_schema_by_id(
        cls, tenant_id: str, schema_id: str
    ) -> AlertTypeSchemaDocument:
        doc = cls._collection(tenant_id).find_one(
            {"tenant_id": tenant_id, "schema_id": schema_id}
        )
        if not doc:
            raise ResourceNotFoundError("Schema version not found")
        return cls._to_document(doc)

    @classmethod
    def activate(
        cls, tenant_id: str, alert_type: str, schema_id: str, updated_by: str
    ) -> AlertTypeSchemaDocument:
        cls.reconcile_indexes_for_tenant(tenant_id)
        now = datetime.now(timezone.utc)

        collection = cls._collection(tenant_id)
        target_query = {
            "tenant_id": tenant_id,
            "alert_type": alert_type,
            "schema_id": schema_id,
        }
        target = collection.find_one(target_query)
        if not target:
            raise ResourceNotFoundError("Schema version not found")

        mapping = target.get("field_mapping") or {}
        missing = sorted({
            field for field in target.get("critical_fields", [])
            if not str(mapping.get(field) or "").strip()
        })
        if missing:
            raise AlertTypeSchemaValidationError([
                {
                    "loc": ["field_mapping", field],
                    "msg": f"Critical field {field!r} requires a source mapping before activation",
                    "type": "value_error",
                }
                for field in missing
            ])

        collection.update_many(
            {"tenant_id": tenant_id, "alert_type": alert_type},
            {"$set": {"is_active": False, "updated_at": now}},
        )
        collection.update_one(
            target_query,
            {"$set": {"is_active": True, "updated_at": now}},
        )
        refreshed = collection.find_one(target_query)
        if not refreshed:
            raise ResourceNotFoundError("Schema not found after activate")
        logger.info(
            "Activated alert-type schema %s for %s (tenant=%s) by=%s",
            schema_id,
            alert_type,
            tenant_id,
            updated_by,
        )
        return cls._to_document(refreshed)
