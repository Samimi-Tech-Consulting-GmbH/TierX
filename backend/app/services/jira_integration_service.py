from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import gridfs
import httpx
import mongoengine as me
from fastapi import HTTPException, status
from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.core.errors import ResourceNotFoundError
from app.core.brand_compat import dual_headers
from app.db.mongodb import DatabaseManager
from app.models.tenant import Tenant
from app.services.alert_type_schema_service import AlertTypeSchemaService
from app.schemas.jira_integration import (
    MAX_JIRA_ATTACHMENT_BYTES,
    JiraAttachmentUploadResponse,
    JiraCommentKind,
    JiraCommentReceipt,
    JiraConnectionInfo,
    JiraIntegrationCreate,
    JiraIntegrationCreated,
    JiraIntegrationDocument,
    JiraIntegrationState,
    JiraProjectRouteCreate,
    JiraProjectRouteDocument,
    JiraProjectRouteUpdate,
    JiraSubmissionCreate,
    JiraSubmissionResponse,
    JiraSubmissionFailure,
    JiraSubmissionState,
)

INTEGRATIONS_COLLECTION = "jira_integrations"
ROUTES_COLLECTION = "jira_project_routes"
SUBMISSIONS_COLLECTION = "jira_integration_submissions"
QUARANTINE_BUCKET = "jira_quarantine"
INGESTION_PROXY_URL = os.getenv(
    "INGESTION_PROXY_URL", "http://ingestion-proxy:8000"
).rstrip("/")
ATTACHMENT_RETENTION_DAYS = int(os.getenv("JIRA_ATTACHMENT_RETENTION_DAYS", "7"))
QUARANTINE_CLEANUP_SECONDS = int(
    os.getenv("JIRA_QUARANTINE_CLEANUP_SECONDS", "3600")
)
INGESTION_RETRY_SECONDS = max(
    5, int(os.getenv("JIRA_INGESTION_RETRY_SECONDS", "30"))
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _secret_digest(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _clean_error(value: Any, *, limit: int = 2000) -> str:
    text = str(value or "Unexpected integration error")
    for marker in ("authorization", "bearer ", "password", "secret", "token"):
        if marker in text.lower():
            return "Upstream request failed; sensitive detail was suppressed."
    return text[:limit]


class JiraIntegrationService:
    @staticmethod
    def _platform_db():
        return me.connection.get_db("default")

    @staticmethod
    def _tenant(tenant_id: str) -> Tenant:
        tenant = Tenant.objects(tenant_id=tenant_id).first()
        if not tenant:
            raise ResourceNotFoundError(f"Tenant with ID {tenant_id} not found")
        return tenant

    @classmethod
    def _tenant_db(cls, tenant_id: str):
        tenant = cls._tenant(tenant_id)
        return DatabaseManager.get_tenant_database(tenant.db_name)

    @classmethod
    def _active_schema(cls, tenant_id: str, alert_type: str):
        raw = cls._tenant_db(tenant_id)[AlertTypeSchemaService.COLLECTION].find_one(
            {"tenant_id": tenant_id, "alert_type": alert_type, "is_active": True}
        )
        if not raw:
            raise ResourceNotFoundError(
                f"No active schema for alert type {alert_type!r}"
            )
        return AlertTypeSchemaService._to_document(raw)

    @classmethod
    def ensure_indexes(cls) -> None:
        db = cls._platform_db()
        integrations = db[INTEGRATIONS_COLLECTION]
        integrations.create_index("integration_id", unique=True)
        integrations.create_index([("jira_cloud_id", ASCENDING), ("state", ASCENDING)])
        integrations.create_index(
            "jira_cloud_id",
            name="jira_active_cloud_unique",
            unique=True,
            partialFilterExpression={"state": JiraIntegrationState.ACTIVE.value},
        )
        routes = db[ROUTES_COLLECTION]
        routes.create_index("route_id", unique=True)
        old_route_index = routes.index_information().get(
            "jira_route_connection_project_unique"
        )
        if old_route_index:
            routes.drop_index("jira_route_connection_project_unique")
        for route in routes.find(
            {"deleted_at": {"$exists": False}},
            {"integration_id": 1, "project_key": 1},
        ):
            routes.update_one(
                {"_id": route["_id"]},
                {
                    "$set": {
                        "route_identity": (
                            f"{route['integration_id']}:{route['project_key']}"
                        )
                    }
                },
            )
        routes.create_index(
            "route_identity",
            name="jira_route_identity_unique",
            unique=True,
            sparse=True,
        )
        routes.create_index(
            [("tenant_id", ASCENDING), ("enabled", ASCENDING), ("updated_at", DESCENDING)]
        )
        submissions = db[SUBMISSIONS_COLLECTION]
        submissions.create_index("submission_id", unique=True)
        submissions.create_index("alert_id", unique=True)
        # The original feature branch used a global unique idempotency key.
        # Replace that index with tenant-scoped issue revision uniqueness so a
        # Jira issue can be submitted independently to different tenants.
        for index in submissions.list_indexes():
            if (
                index.get("name") == "idempotency_key_1"
                and index.get("unique")
                and list(index.get("key", {}).items()) == [("idempotency_key", 1)]
            ):
                submissions.drop_index(index["name"])
                break
        for old_name in ("jira_submission_issue_revision_unique",):
            if old_name in submissions.index_information():
                submissions.drop_index(old_name)
        submissions.create_index(
            [
                ("integration_id", ASCENDING),
                ("route_id", ASCENDING),
                ("issue_id", ASCENDING),
                ("raw_alert_digest", ASCENDING),
                ("route_revision", ASCENDING),
                ("schema_id", ASCENDING),
                ("schema_version", ASCENDING),
            ],
            name="jira_submission_raw_alert_unique",
            unique=True,
            partialFilterExpression={"raw_alert_digest": {"$type": "string"}},
        )
        submissions.create_index(
            [
                ("tenant_id", ASCENDING),
                ("jira_cloud_id", ASCENDING),
                ("issue_id", ASCENDING),
                ("embedded_alert_digest", ASCENDING),
            ],
            name="jira_submission_embedded_alert_unique",
            unique=True,
            partialFilterExpression={"embedded_alert_digest": {"$type": "string"}},
        )
        submissions.create_index(
            [("tenant_id", ASCENDING), ("idempotency_key", ASCENDING)],
            name="jira_submission_tenant_idempotency",
        )
        submissions.create_index(
            [("integration_id", ASCENDING), ("created_at", DESCENDING)]
        )
        cls._mark_legacy_connections()

    @classmethod
    def _mark_legacy_connections(cls) -> None:
        """Make tenant-bound connection records readable as site connections.

        No credential material changes and the existing integration ID/secret
        remain valid. A platform admin must add project routes before raw-alert
        ingestion is accepted.
        """
        db = cls._platform_db()
        integrations = db[INTEGRATIONS_COLLECTION]
        integrations.update_many(
            {"connection_kind": {"$exists": False}},
            {
                "$set": {
                    "connection_kind": "SITE",
                    "migration_state": "ROUTE_REQUIRED",
                }
            },
        )
        for connection in integrations.find(
            {"jira_site_url": {"$exists": False}}, {"integration_id": 1}
        ):
            previous = db[SUBMISSIONS_COLLECTION].find_one(
                {
                    "integration_id": connection["integration_id"],
                    "jira_site_url": {"$type": "string"},
                },
                sort=[("created_at", DESCENDING)],
            )
            if previous and previous.get("jira_site_url"):
                integrations.update_one(
                    {"_id": connection["_id"]},
                    {"$set": {"jira_site_url": previous["jira_site_url"]}},
                )

    @staticmethod
    def _integration_document(raw: dict[str, Any]) -> JiraIntegrationDocument:
        route_count = JiraIntegrationService._platform_db()[ROUTES_COLLECTION].count_documents(
            {"integration_id": raw["integration_id"], "deleted_at": {"$exists": False}}
        )
        return JiraIntegrationDocument(
            integration_id=raw["integration_id"],
            name=raw["name"],
            jira_cloud_id=raw["jira_cloud_id"],
            jira_site_url=raw.get("jira_site_url"),
            state=raw["state"],
            secret_prefix=raw["secret_prefix"],
            route_count=route_count,
            created_at=raw["created_at"],
            updated_at=raw["updated_at"],
            created_by=raw["created_by"],
            last_used_at=raw.get("last_used_at"),
            last_submission_at=raw.get("last_submission_at"),
            legacy_tenant_id=raw.get("tenant_id"),
        )

    @classmethod
    def create_integration(
        cls, body: JiraIntegrationCreate, created_by: str
    ) -> JiraIntegrationCreated:
        if cls._platform_db()[INTEGRATIONS_COLLECTION].find_one(
            {"jira_cloud_id": body.jira_cloud_id.strip(), "state": JiraIntegrationState.ACTIVE.value}
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An active Jira site connection already exists for this cloud ID.",
            )
        now = _now()
        secret = f"socjira_{secrets.token_urlsafe(32)}"
        document = {
            "integration_id": str(uuid4()),
            "name": body.name.strip(),
            "jira_cloud_id": body.jira_cloud_id.strip(),
            "jira_site_url": str(body.jira_site_url).rstrip("/"),
            "connection_kind": "SITE",
            "state": JiraIntegrationState.ACTIVE.value,
            "secret_hash": _secret_digest(secret),
            "secret_prefix": secret[:14],
            "created_at": now,
            "updated_at": now,
            "created_by": created_by,
        }
        cls._platform_db()[INTEGRATIONS_COLLECTION].insert_one(document)
        return JiraIntegrationCreated(
            **cls._integration_document(document).model_dump(), secret=secret
        )

    @classmethod
    def list_integrations(cls) -> list[JiraIntegrationDocument]:
        cursor = cls._platform_db()[INTEGRATIONS_COLLECTION].find(
            {}, {"_id": 0, "secret_hash": 0}
        ).sort("created_at", DESCENDING)
        return [cls._integration_document(item) for item in cursor]

    @classmethod
    def get_integration(cls, integration_id: str) -> JiraIntegrationDocument:
        document = cls._platform_db()[INTEGRATIONS_COLLECTION].find_one(
            {"integration_id": integration_id}, {"secret_hash": 0}
        )
        if not document:
            raise ResourceNotFoundError("Jira site connection not found")
        return cls._integration_document(document)

    @classmethod
    def rotate_secret(cls, integration_id: str) -> JiraIntegrationCreated:
        secret = f"socjira_{secrets.token_urlsafe(32)}"
        document = cls._platform_db()[INTEGRATIONS_COLLECTION].find_one_and_update(
            {"integration_id": integration_id, "state": JiraIntegrationState.ACTIVE.value},
            {
                "$set": {
                    "secret_hash": _secret_digest(secret),
                    "secret_prefix": secret[:14],
                    "updated_at": _now(),
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        if not document:
            raise ResourceNotFoundError("Active Jira integration not found")
        return JiraIntegrationCreated(
            **cls._integration_document(document).model_dump(), secret=secret
        )

    @classmethod
    def revoke(cls, integration_id: str) -> JiraIntegrationDocument:
        document = cls._platform_db()[INTEGRATIONS_COLLECTION].find_one_and_update(
            {"integration_id": integration_id},
            {
                "$set": {
                    "state": JiraIntegrationState.REVOKED.value,
                    "updated_at": _now(),
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        if not document:
            raise ResourceNotFoundError("Jira integration not found")
        return cls._integration_document(document)

    @classmethod
    def authenticate(cls, integration_id: str, secret: str) -> dict[str, Any]:
        integration = cls._platform_db()[INTEGRATIONS_COLLECTION].find_one(
            {"integration_id": integration_id, "state": JiraIntegrationState.ACTIVE.value}
        )
        supplied = _secret_digest(secret)
        expected = str((integration or {}).get("secret_hash") or "0" * 64)
        if not integration or not secrets.compare_digest(supplied, expected):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid Jira integration credential.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        cls._platform_db()[INTEGRATIONS_COLLECTION].update_one(
            {"_id": integration["_id"]}, {"$set": {"last_used_at": _now()}}
        )
        return integration

    @classmethod
    def connection_info(cls, integration: dict[str, Any]) -> JiraConnectionInfo:
        return JiraConnectionInfo(
            integration_id=integration["integration_id"],
            jira_cloud_id=integration["jira_cloud_id"],
            jira_site_url=integration.get("jira_site_url"),
            name=integration["name"],
            route_count=cls._platform_db()[ROUTES_COLLECTION].count_documents(
                {
                    "integration_id": integration["integration_id"],
                    "deleted_at": {"$exists": False},
                }
            ),
            state=integration["state"],
        )

    @classmethod
    def _validated_route_fields(
        cls, body: JiraProjectRouteCreate | JiraProjectRouteUpdate
    ) -> tuple[Tenant, Any, str]:
        tenant = cls._tenant(body.tenant_id)
        if tenant.status != "ACTIVE":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Jira project routes require an ACTIVE tenant.",
            )
        allowed = {str(item).upper() for item in tenant.allowed_source_systems}
        if body.source_system.upper() not in allowed:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Source system {body.source_system!r} is not allowed for tenant "
                    f"{body.tenant_id!r}."
                ),
            )
        schema = cls._active_schema(body.tenant_id, body.alert_type)
        timestamp_path = str(schema.field_mapping.get("event.created") or "").strip()
        if not timestamp_path:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "The active alert-type schema must map event.created so Jira "
                    "can preserve the original source timestamp."
                ),
            )
        return tenant, schema, timestamp_path

    @classmethod
    def _route_document(cls, raw: dict[str, Any]) -> JiraProjectRouteDocument:
        tenant = cls._tenant(raw["tenant_id"])
        try:
            schema = cls._active_schema(raw["tenant_id"], raw["alert_type"])
            schema_id = schema.schema_id
            schema_version = schema.version
            timestamp_path = str(
                schema.field_mapping.get("event.created") or ""
            ).strip()
        except ResourceNotFoundError:
            schema_id = raw.get("validated_schema_id")
            schema_version = raw.get("validated_schema_version")
            timestamp_path = raw.get("event_timestamp_path")
        return JiraProjectRouteDocument(
            route_id=raw["route_id"],
            integration_id=raw["integration_id"],
            project_key=raw["project_key"],
            tenant_id=raw["tenant_id"],
            tenant_name=tenant.display_name,
            source_system=raw["source_system"],
            alert_type=raw["alert_type"],
            enabled=bool(raw.get("enabled")),
            revision=int(raw.get("revision", 1)),
            effective_schema_id=schema_id,
            effective_schema_version=schema_version,
            event_timestamp_path=timestamp_path,
            created_at=raw["created_at"],
            updated_at=raw["updated_at"],
            created_by=raw["created_by"],
            updated_by=raw["updated_by"],
            last_used_at=raw.get("last_used_at"),
            last_error=raw.get("last_error"),
        )

    @classmethod
    def list_routes(cls, integration_id: str) -> list[JiraProjectRouteDocument]:
        cls.get_integration(integration_id)
        rows = cls._platform_db()[ROUTES_COLLECTION].find(
            {"integration_id": integration_id, "deleted_at": {"$exists": False}}
        ).sort([("project_key", ASCENDING), ("created_at", ASCENDING)])
        return [cls._route_document(row) for row in rows]

    @classmethod
    def create_route(
        cls, integration_id: str, body: JiraProjectRouteCreate, actor: str
    ) -> JiraProjectRouteDocument:
        cls.get_integration(integration_id)
        _, schema, timestamp_path = cls._validated_route_fields(body)
        now = _now()
        row = {
            "route_id": str(uuid4()),
            "integration_id": integration_id,
            "project_key": body.project_key,
            "route_identity": f"{integration_id}:{body.project_key}",
            "tenant_id": body.tenant_id,
            "source_system": body.source_system,
            "alert_type": body.alert_type,
            "enabled": body.enabled,
            "revision": 1,
            "validated_schema_id": schema.schema_id,
            "validated_schema_version": schema.version,
            "event_timestamp_path": timestamp_path,
            "created_at": now,
            "updated_at": now,
            "created_by": actor,
            "updated_by": actor,
        }
        try:
            cls._platform_db()[ROUTES_COLLECTION].insert_one(row)
        except DuplicateKeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This Jira project already has a route for the site connection.",
            ) from exc
        return cls._route_document(row)

    @classmethod
    def update_route(
        cls,
        integration_id: str,
        route_id: str,
        body: JiraProjectRouteUpdate,
        actor: str,
    ) -> JiraProjectRouteDocument:
        cls.get_integration(integration_id)
        _, schema, timestamp_path = cls._validated_route_fields(body)
        try:
            row = cls._platform_db()[ROUTES_COLLECTION].find_one_and_update(
                {
                    "route_id": route_id,
                    "integration_id": integration_id,
                    "deleted_at": {"$exists": False},
                },
                {
                    "$set": {
                        "project_key": body.project_key,
                        "route_identity": f"{integration_id}:{body.project_key}",
                        "tenant_id": body.tenant_id,
                        "source_system": body.source_system,
                        "alert_type": body.alert_type,
                        "enabled": body.enabled,
                        "validated_schema_id": schema.schema_id,
                        "validated_schema_version": schema.version,
                        "event_timestamp_path": timestamp_path,
                        "updated_at": _now(),
                        "updated_by": actor,
                    },
                    "$inc": {"revision": 1},
                },
                return_document=ReturnDocument.AFTER,
            )
        except DuplicateKeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This Jira project already has a route for the site connection.",
            ) from exc
        if not row:
            raise ResourceNotFoundError("Jira project route not found")
        return cls._route_document(row)

    @classmethod
    def set_route_enabled(
        cls, integration_id: str, route_id: str, enabled: bool, actor: str
    ) -> JiraProjectRouteDocument:
        row = cls._platform_db()[ROUTES_COLLECTION].find_one_and_update(
            {
                "route_id": route_id,
                "integration_id": integration_id,
                "deleted_at": {"$exists": False},
            },
            {
                "$set": {"enabled": enabled, "updated_at": _now(), "updated_by": actor},
                "$inc": {"revision": 1},
            },
            return_document=ReturnDocument.AFTER,
        )
        if not row:
            raise ResourceNotFoundError("Jira project route not found")
        return cls._route_document(row)

    @classmethod
    def delete_route(cls, integration_id: str, route_id: str, actor: str) -> None:
        result = cls._platform_db()[ROUTES_COLLECTION].update_one(
            {
                "route_id": route_id,
                "integration_id": integration_id,
                "deleted_at": {"$exists": False},
            },
            {
                "$set": {
                    "enabled": False,
                    "deleted_at": _now(),
                    "updated_at": _now(),
                    "updated_by": actor,
                },
                "$unset": {"route_identity": ""},
                "$inc": {"revision": 1},
            },
        )
        if not result.modified_count:
            raise ResourceNotFoundError("Jira project route not found")

    @staticmethod
    def _raw_alert_digest(body: JiraSubmissionCreate) -> str:
        encoded = json.dumps(
            body.raw_alert,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _idempotency_key(
        integration: dict[str, Any],
        route: dict[str, Any],
        schema: Any,
        body: JiraSubmissionCreate,
    ) -> str:
        alert_digest = JiraIntegrationService._raw_alert_digest(body)
        source = "\0".join(
            [
                integration["integration_id"],
                route["route_id"],
                body.jira_cloud_id,
                body.issue_id,
                alert_digest,
                str(route.get("revision", 1)),
                schema.schema_id,
                schema.version,
            ]
        )
        return hashlib.sha256(source.encode("utf-8")).hexdigest()

    @staticmethod
    def _submission_identity_filter(
        integration: dict[str, Any],
        route: dict[str, Any],
        schema: Any,
        body: JiraSubmissionCreate,
    ) -> dict[str, Any]:
        return {
            "integration_id": integration["integration_id"],
            "route_id": route["route_id"],
            "jira_cloud_id": body.jira_cloud_id,
            "issue_id": body.issue_id,
            "raw_alert_digest": JiraIntegrationService._raw_alert_digest(body),
            "route_revision": int(route.get("revision", 1)),
            "schema_id": schema.schema_id,
            "schema_version": schema.version,
        }

    @staticmethod
    def _resolve_path(payload: dict[str, Any], path: str) -> Any:
        value: Any = payload
        for segment in path.split("."):
            if not isinstance(value, dict) or segment not in value:
                return None
            value = value[segment]
        return value

    @classmethod
    def _resolve_route(
        cls, integration: dict[str, Any], body: JiraSubmissionCreate
    ) -> tuple[dict[str, Any], Any, str]:
        if body.jira_cloud_id != integration["jira_cloud_id"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Jira cloud ID does not match this site connection.",
            )
        configured_site = str(integration.get("jira_site_url") or "").rstrip("/")
        requested_site = str(body.jira_site_url).rstrip("/")
        if configured_site and configured_site != requested_site:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Jira site URL does not match this site connection.",
            )
        route = cls._platform_db()[ROUTES_COLLECTION].find_one(
            {
                "integration_id": integration["integration_id"],
                "project_key": body.project_key,
                "enabled": True,
                "deleted_at": {"$exists": False},
            }
        )
        if not route:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Jira project {body.project_key!r} has no enabled TierX route. "
                    "A platform administrator must configure it in Integrations → Jira."
                ),
            )
        try:
            tenant = cls._tenant(route["tenant_id"])
            if tenant.status != "ACTIVE":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="The Jira project route tenant is not active.",
                )
            allowed = {str(item).upper() for item in tenant.allowed_source_systems}
            if str(route["source_system"]).upper() not in allowed:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="The Jira project route source system is no longer allowed.",
                )
            schema = cls._active_schema(route["tenant_id"], route["alert_type"])
            timestamp_path = str(
                schema.field_mapping.get("event.created") or ""
            ).strip()
            timestamp_value = cls._resolve_path(body.raw_alert, timestamp_path)
            if not isinstance(timestamp_value, str) or not timestamp_value.strip():
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        "Raw alert is missing the source event timestamp at "
                        f"{timestamp_path!r} required by schema {schema.schema_id} "
                        f"v{schema.version}."
                    ),
                )
            try:
                datetime.fromisoformat(timestamp_value.strip().replace("Z", "+00:00"))
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        f"Raw alert timestamp at {timestamp_path!r} is not valid "
                        "ISO-8601."
                    ),
                ) from exc
        except (HTTPException, ResourceNotFoundError) as exc:
            detail = getattr(exc, "detail", str(exc))
            cls._platform_db()[ROUTES_COLLECTION].update_one(
                {"_id": route["_id"]},
                {
                    "$set": {
                        "last_error": {
                            "at": _now(),
                            "type": type(exc).__name__,
                            "detail": _clean_error(detail, limit=500),
                        }
                    }
                },
            )
            raise
        return route, schema, timestamp_value.strip()

    @classmethod
    def create_submission(
        cls, integration: dict[str, Any], body: JiraSubmissionCreate
    ) -> JiraSubmissionResponse:
        route, schema, event_timestamp = cls._resolve_route(integration, body)
        key = cls._idempotency_key(integration, route, schema, body)
        raw_alert_digest = cls._raw_alert_digest(body)
        identity = cls._submission_identity_filter(integration, route, schema, body)
        collection = cls._platform_db()[SUBMISSIONS_COLLECTION]
        existing = collection.find_one(identity)
        if existing:
            return cls.submission_response(existing, idempotent_replay=True)

        now = _now()
        attachment_documents = [
            {
                **item.model_dump(mode="json"),
                "uploaded": False,
                "sha256": None,
                "gridfs_id": None,
            }
            for item in body.attachments
        ]
        document = {
            "submission_id": str(uuid4()),
            "alert_id": str(uuid4()),
            "integration_id": integration["integration_id"],
            "route_id": route["route_id"],
            "route_revision": int(route.get("revision", 1)),
            "tenant_id": route["tenant_id"],
            "source_system": route["source_system"],
            "alert_type": route["alert_type"],
            "schema_id": schema.schema_id,
            "schema_version": schema.version,
            "event_timestamp_path": str(schema.field_mapping["event.created"]),
            "event_timestamp": event_timestamp,
            "jira_cloud_id": body.jira_cloud_id,
            "jira_site_url": str(body.jira_site_url).rstrip("/"),
            "project_key": body.project_key,
            "issue_id": body.issue_id,
            "issue_key": body.issue_key,
            "issue_created_at": body.issue_created_at,
            "issue_updated_at": body.issue_updated_at,
            "submitted_by": body.submitted_by,
            "raw_alert": body.raw_alert,
            "raw_alert_source": body.raw_alert_source.model_dump(mode="json"),
            "raw_alert_digest": raw_alert_digest,
            "source_reference": {
                "type": "JIRA",
                "integration_id": integration["integration_id"],
                "route_id": route["route_id"],
                "jira_cloud_id": body.jira_cloud_id,
                "jira_site_url": str(body.jira_site_url).rstrip("/"),
                "project_key": body.project_key,
                "issue_id": body.issue_id,
                "issue_key": body.issue_key,
                "issue_url": f"{str(body.jira_site_url).rstrip('/')}/browse/{body.issue_key}",
                "content_source": body.raw_alert_source.model_dump(mode="json"),
                "content_sha256": raw_alert_digest,
            },
            "attachments": attachment_documents,
            "idempotency_key": key,
            "state": (
                JiraSubmissionState.UPLOADING.value
                if attachment_documents
                else JiraSubmissionState.ACCEPTED.value
            ),
            "comment_receipts": {},
            "created_at": now,
            "updated_at": now,
        }
        try:
            collection.insert_one(document)
        except DuplicateKeyError:
            existing = collection.find_one(identity)
            if not existing:
                raise
            return cls.submission_response(existing, idempotent_replay=True)
        cls._platform_db()[INTEGRATIONS_COLLECTION].update_one(
            {"_id": integration["_id"]},
            {"$set": {"last_submission_at": now, "updated_at": now}},
        )
        cls._platform_db()[ROUTES_COLLECTION].update_one(
            {"_id": route["_id"]},
            {"$set": {"last_used_at": now, "last_error": None}},
        )
        return cls.submission_response(document)

    @classmethod
    def _submission_for_integration(
        cls, integration: dict[str, Any], submission_id: str
    ) -> dict[str, Any]:
        document = cls._platform_db()[SUBMISSIONS_COLLECTION].find_one(
            {
                "submission_id": submission_id,
                "integration_id": integration["integration_id"],
            }
        )
        if not document:
            raise ResourceNotFoundError("Jira submission not found")
        return document

    @classmethod
    def upload_attachment(
        cls,
        integration: dict[str, Any],
        submission_id: str,
        attachment_id: str,
        content: bytes,
        supplied_sha256: str,
        content_type: str | None,
    ) -> JiraAttachmentUploadResponse:
        if len(content) > MAX_JIRA_ATTACHMENT_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Jira attachment exceeds the 5 MiB limit.",
            )
        document = cls._submission_for_integration(integration, submission_id)
        if document["state"] not in {
            JiraSubmissionState.UPLOADING.value,
            JiraSubmissionState.ACCEPTED.value,
        }:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Attachments cannot be changed after finalization.",
            )
        manifest = next(
            (
                item
                for item in document.get("attachments") or []
                if item["attachment_id"] == attachment_id
            ),
            None,
        )
        if not manifest:
            raise ResourceNotFoundError("Attachment is not in the submission manifest")
        if len(content) != int(manifest["size"]):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Attachment size does not match its manifest.",
            )
        digest = hashlib.sha256(content).hexdigest()
        if not secrets.compare_digest(digest, supplied_sha256.lower()):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Attachment SHA-256 checksum does not match.",
            )
        if manifest.get("uploaded") and manifest.get("sha256") == digest:
            return JiraAttachmentUploadResponse(
                submission_id=submission_id,
                attachment_id=attachment_id,
                size=len(content),
                sha256=digest,
            )

        tenant_db = cls._tenant_db(document["tenant_id"])
        quarantine = gridfs.GridFS(tenant_db, collection=QUARANTINE_BUCKET)
        old_id = manifest.get("gridfs_id")
        if old_id:
            try:
                quarantine.delete(old_id)
            except gridfs.errors.NoFile:
                pass
        expires_at = _now() + timedelta(days=ATTACHMENT_RETENTION_DAYS)
        gridfs_id = quarantine.put(
            content,
            filename=manifest["filename"],
            metadata={
                "submission_id": submission_id,
                "alert_id": document["alert_id"],
                "tenant_id": document["tenant_id"],
                "jira_attachment_id": attachment_id,
                "content_type": content_type or manifest.get("media_type"),
                "sha256": digest,
                "quarantine_status": "UNSCANNED",
                "expires_at": expires_at,
            },
        )
        collection = cls._platform_db()[SUBMISSIONS_COLLECTION]
        collection.update_one(
            {"_id": document["_id"], "attachments.attachment_id": attachment_id},
            {
                "$set": {
                    "attachments.$.uploaded": True,
                    "attachments.$.sha256": digest,
                    "attachments.$.gridfs_id": gridfs_id,
                    "attachments.$.expires_at": expires_at,
                    "updated_at": _now(),
                }
            },
        )
        refreshed = collection.find_one({"_id": document["_id"]})
        if all(item.get("uploaded") for item in refreshed.get("attachments") or []):
            collection.update_one(
                {"_id": document["_id"], "state": JiraSubmissionState.UPLOADING.value},
                {"$set": {"state": JiraSubmissionState.ACCEPTED.value, "updated_at": _now()}},
            )
        return JiraAttachmentUploadResponse(
            submission_id=submission_id,
            attachment_id=attachment_id,
            size=len(content),
            sha256=digest,
        )

    @classmethod
    def _ingestion_payload(cls, submission: dict[str, Any]) -> dict[str, Any]:
        if submission.get("raw_alert") is not None:
            return {
                "tenant_id": submission["tenant_id"],
                "source_system": submission["source_system"],
                "alert_type": submission["alert_type"],
                "timestamp": submission["event_timestamp"],
                "raw_payload": submission["raw_alert"],
                "source_reference": submission.get("source_reference"),
            }

        # Historical wrapper submissions remain replayable and readable, but
        # the public create contract no longer accepts this shape.
        embedded = submission.get("embedded_alert")
        if embedded:
            return {
                # The credential binding is authoritative. An optional tenant ID
                # inside the Jira-carried envelope is checked at submission time
                # and is never allowed to route data across tenants.
                "tenant_id": submission["tenant_id"],
                "source_system": embedded["source_system"],
                "alert_type": embedded["alert_type"],
                "timestamp": embedded["timestamp"],
                "raw_payload": embedded["raw_payload"],
            }

        # Historical submissions created by the first Forge revision remain
        # replayable. New Forge clients never enter this Jira-as-source path.
        attachments = []
        for item in submission.get("attachments") or []:
            attachments.append(
                {
                    key: item.get(key)
                    for key in (
                        "attachment_id",
                        "filename",
                        "size",
                        "media_type",
                        "created_at",
                        "author",
                        "sha256",
                    )
                }
                | {"quarantine_status": "UNSCANNED", "retention_days": ATTACHMENT_RETENTION_DAYS}
            )
        return {
            "tenant_id": submission["tenant_id"],
            "source_system": "JIRA",
            "alert_type": "jira.issue.security",
            "timestamp": submission["issue_updated_at"].isoformat(),
            "raw_payload": {
                "issue": submission["issue"],
                "comments": submission.get("comments_payload") or [],
                "changelog": submission.get("changelog") or [],
                "attachments": attachments,
                "submission": {
                    "submission_id": submission["submission_id"],
                    "jira_cloud_id": submission["jira_cloud_id"],
                    "jira_site_url": submission["jira_site_url"],
                    "submitted_by": submission["submitted_by"],
                },
            },
        }

    @classmethod
    async def finalize_submission(
        cls, integration: dict[str, Any], submission_id: str
    ) -> JiraSubmissionResponse:
        collection = cls._platform_db()[SUBMISSIONS_COLLECTION]
        submission = cls._submission_for_integration(integration, submission_id)
        if submission["state"] in {
            JiraSubmissionState.PROCESSING.value,
            JiraSubmissionState.CLUSTERED.value,
            JiraSubmissionState.ANALYZED.value,
        }:
            return cls.submission_response(submission, idempotent_replay=True)
        if submission["state"] == JiraSubmissionState.FAILED.value:
            return cls.submission_response(submission, idempotent_replay=True)
        if submission["state"] == JiraSubmissionState.FINALIZING.value:
            reconciled = cls._reconcile_ingestion_delivery(submission)
            if reconciled["state"] != JiraSubmissionState.FINALIZING.value:
                return cls.submission_response(reconciled, idempotent_replay=True)
            next_retry_at = (reconciled.get("ingestion_delivery") or {}).get(
                "next_retry_at"
            )
            if next_retry_at and _as_utc(next_retry_at) > _now():
                return cls.submission_response(reconciled, idempotent_replay=True)
            submission = reconciled
        missing = [
            item["attachment_id"]
            for item in submission.get("attachments") or []
            if not item.get("uploaded")
        ]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"message": "Attachments are still missing.", "attachment_ids": missing},
            )
        claim_filter: dict[str, Any] = {
            "_id": submission["_id"],
            "state": {
                "$in": [
                    JiraSubmissionState.UPLOADING.value,
                    JiraSubmissionState.ACCEPTED.value,
                    JiraSubmissionState.FINALIZING.value,
                ]
            },
        }
        if submission["state"] == JiraSubmissionState.FINALIZING.value:
            claim_filter["$or"] = [
                {"ingestion_delivery.next_retry_at": {"$exists": False}},
                {"ingestion_delivery.next_retry_at": {"$lte": _now()}},
            ]
        now = _now()
        claimed = collection.find_one_and_update(
            claim_filter,
            {
                "$set": {
                    "state": JiraSubmissionState.FINALIZING.value,
                    "ingestion_delivery.last_attempt_at": now,
                    "ingestion_delivery.next_retry_at": now
                    + timedelta(seconds=INGESTION_RETRY_SECONDS),
                    "updated_at": now,
                },
                "$inc": {"ingestion_delivery.attempt_count": 1},
            },
            return_document=ReturnDocument.AFTER,
        )
        if not claimed:
            return cls.submission_response(
                cls._submission_for_integration(integration, submission_id),
                idempotent_replay=True,
            )
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{INGESTION_PROXY_URL}/api/v1/alerts/ingest",
                    json=cls._ingestion_payload(claimed),
                    headers=dual_headers(
                        requested_alert_id=claimed["alert_id"],
                        integration=claimed["integration_id"],
                    ),
                )
            if not response.is_success:
                try:
                    rejection = response.json()
                except Exception:
                    rejection = {}
                detail = (
                    rejection.get("error_detail")
                    or rejection.get("detail")
                    or f"Ingestion rejected the Jira issue with HTTP {response.status_code}"
                )
                document = collection.find_one_and_update(
                    {
                        "_id": claimed["_id"],
                        "state": JiraSubmissionState.FINALIZING.value,
                    },
                    {
                        "$set": {
                            "state": JiraSubmissionState.FAILED.value,
                            "failure": {
                                "failed_stage": "INGESTION",
                                "error_type": "INGESTION_REJECTED",
                                "error_detail": _clean_error(detail),
                            },
                            "updated_at": _now(),
                        }
                    },
                    return_document=ReturnDocument.AFTER,
                )
                return cls.submission_response(document or claimed)
            payload = response.json()
            if payload.get("alert_id") != claimed["alert_id"]:
                raise RuntimeError("Ingestion returned an unexpected alert identifier")
        except Exception as exc:
            # A timeout or malformed success response can happen after the
            # ingestion proxy has accepted the reserved alert ID. Keep the
            # delivery retryable and first reconcile against durable pipeline
            # evidence; declaring it failed here would contradict the alert
            # that may already be processing.
            reconciled = cls._reconcile_ingestion_delivery(claimed)
            if reconciled["state"] != JiraSubmissionState.FINALIZING.value:
                return cls.submission_response(reconciled, idempotent_replay=True)
            collection.update_one(
                {
                    "_id": claimed["_id"],
                    "state": JiraSubmissionState.FINALIZING.value,
                },
                {
                    "$set": {
                        "ingestion_delivery.last_error_type": type(exc).__name__,
                        "ingestion_delivery.last_error_detail": _clean_error(exc),
                        "updated_at": _now(),
                    }
                },
            )
            return cls.submission_response(collection.find_one({"_id": claimed["_id"]}))

        document = collection.find_one_and_update(
            {
                "_id": claimed["_id"],
                "state": JiraSubmissionState.FINALIZING.value,
            },
            {
                "$set": {
                    "state": JiraSubmissionState.PROCESSING.value,
                    "ingested_at": _now(),
                    "updated_at": _now(),
                },
                "$unset": {
                    "ingestion_delivery.last_error_type": "",
                    "ingestion_delivery.last_error_detail": "",
                },
            },
            return_document=ReturnDocument.AFTER,
        )
        if not document:
            document = collection.find_one({"_id": claimed["_id"]})
        return cls.submission_response(document)

    @classmethod
    def _reconcile_ingestion_delivery(
        cls, submission: dict[str, Any]
    ) -> dict[str, Any]:
        """Resolve an ambiguous ingestion response from durable alert evidence."""
        if submission["state"] != JiraSubmissionState.FINALIZING.value:
            return submission

        db = cls._tenant_db(submission["tenant_id"])
        alert_id = submission["alert_id"]
        alert = db["alerts"].find_one({"alert_id": alert_id}, {"_id": 1})
        dead_letter = db["dead_letters"].find_one(
            {"alert_id": alert_id}, sort=[("received_at", DESCENDING)]
        )
        updates: dict[str, Any] | None = None
        if dead_letter:
            updates = {
                "state": JiraSubmissionState.FAILED.value,
                "failure": {
                    "failed_stage": _clean_error(
                        dead_letter.get("failed_stage") or "INGESTION"
                    ),
                    "error_type": _clean_error(
                        dead_letter.get("error_type") or "INGESTION_REJECTED"
                    ),
                    "error_detail": _clean_error(dead_letter.get("error_detail")),
                    "failed_fields": dead_letter.get("failed_fields") or [],
                },
            }
        elif alert:
            updates = {
                "state": JiraSubmissionState.PROCESSING.value,
                "ingested_at": submission.get("ingested_at") or _now(),
            }
        if not updates:
            return submission

        updates["updated_at"] = _now()
        document = cls._platform_db()[SUBMISSIONS_COLLECTION].find_one_and_update(
            {
                "_id": submission["_id"],
                "state": JiraSubmissionState.FINALIZING.value,
            },
            {"$set": updates},
            return_document=ReturnDocument.AFTER,
        )
        return document or cls._platform_db()[SUBMISSIONS_COLLECTION].find_one(
            {"_id": submission["_id"]}
        )

    @classmethod
    def _refresh_pipeline_state(cls, submission: dict[str, Any]) -> dict[str, Any]:
        if submission["state"] in {
            JiraSubmissionState.UPLOADING.value,
            JiraSubmissionState.ACCEPTED.value,
            JiraSubmissionState.FAILED.value,
        }:
            return submission
        if submission["state"] == JiraSubmissionState.FINALIZING.value:
            submission = cls._reconcile_ingestion_delivery(submission)
            if submission["state"] == JiraSubmissionState.FINALIZING.value:
                return submission
        db = cls._tenant_db(submission["tenant_id"])
        alert = db["alerts"].find_one({"alert_id": submission["alert_id"]}, {"_id": 0})
        state = JiraSubmissionState.PROCESSING.value
        updates: dict[str, Any] = {}
        if alert:
            cluster_id = alert.get("cluster_id")
            cluster = None
            if cluster_id:
                cluster = db["clusters"].find_one(
                    {"cluster_id": cluster_id}, {"_id": 0, "summary.history": 0}
                )
            if alert.get("analysis_status") == "FAILED":
                state = JiraSubmissionState.FAILED.value
                error = alert.get("analysis_error") or {}
                updates["failure"] = {
                    "failed_stage": "ANALYSIS",
                    "error_type": _clean_error(error.get("type") or "ANALYSIS_FAILED"),
                    "error_detail": _clean_error(error.get("detail") or error),
                }
            elif (cluster or {}).get("analysis_status") == "FAILED":
                state = JiraSubmissionState.FAILED.value
                error = (cluster or {}).get("analysis_error") or {}
                updates["failure"] = {
                    "failed_stage": "ANALYSIS",
                    "error_type": _clean_error(error.get("type") or "ANALYSIS_FAILED"),
                    "error_detail": _clean_error(error.get("detail") or error),
                }
            elif alert.get("status") == "ANALYZED":
                state = JiraSubmissionState.ANALYZED.value
                result = alert.get("alert_analysis")
                if cluster_id:
                    result = (cluster or {}).get("summary") or result
                updates["result"] = result or {}
            updates["cluster_id"] = cluster_id
        if state not in {
            JiraSubmissionState.ANALYZED.value,
            JiraSubmissionState.FAILED.value,
        }:
            dead_letter = db["dead_letters"].find_one(
                {"alert_id": submission["alert_id"]}, sort=[("received_at", DESCENDING)]
            )
            if dead_letter:
                state = JiraSubmissionState.FAILED.value
                updates["failure"] = {
                    "failed_stage": _clean_error(dead_letter.get("failed_stage") or "PIPELINE"),
                    "error_type": _clean_error(dead_letter.get("error_type") or "PIPELINE_FAILED"),
                    "error_detail": _clean_error(dead_letter.get("error_detail")),
                    "failed_fields": dead_letter.get("failed_fields") or [],
                }
            elif alert and alert.get("cluster_id"):
                state = JiraSubmissionState.CLUSTERED.value
        if state != submission["state"] or updates:
            updates.update({"state": state, "updated_at": _now()})
            cls._platform_db()[SUBMISSIONS_COLLECTION].update_one(
                {"_id": submission["_id"]}, {"$set": updates}
            )
            submission = {**submission, **updates}
        return submission

    @classmethod
    def get_submission(
        cls, integration: dict[str, Any], submission_id: str
    ) -> JiraSubmissionResponse:
        document = cls._submission_for_integration(integration, submission_id)
        return cls.submission_response(cls._refresh_pipeline_state(document))

    @classmethod
    def record_comment(
        cls,
        integration: dict[str, Any],
        submission_id: str,
        body: JiraCommentReceipt,
    ) -> JiraSubmissionResponse:
        document = cls._submission_for_integration(integration, submission_id)
        key = body.kind.value
        updated = cls._platform_db()[SUBMISSIONS_COLLECTION].find_one_and_update(
            {"_id": document["_id"]},
            {
                "$set": {
                    f"comment_receipts.{key}": body.jira_comment_id,
                    "updated_at": _now(),
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        return cls.submission_response(updated)

    @classmethod
    def fail_submission(
        cls,
        integration: dict[str, Any],
        submission_id: str,
        body: JiraSubmissionFailure,
    ) -> JiraSubmissionResponse:
        document = cls._submission_for_integration(integration, submission_id)
        mutable_states = {
            JiraSubmissionState.UPLOADING.value,
            JiraSubmissionState.ACCEPTED.value,
            JiraSubmissionState.FINALIZING.value,
        }
        if document["state"] not in mutable_states:
            return cls.submission_response(document, idempotent_replay=True)
        updated = cls._platform_db()[SUBMISSIONS_COLLECTION].find_one_and_update(
            {"_id": document["_id"], "state": {"$in": sorted(mutable_states)}},
            {
                "$set": {
                    "state": JiraSubmissionState.FAILED.value,
                    "failure": {
                        "failed_stage": _clean_error(body.failed_stage, limit=128),
                        "error_type": _clean_error(body.error_type, limit=255),
                        "error_detail": _clean_error(body.error_detail),
                    },
                    "updated_at": _now(),
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        if not updated:
            updated = cls._platform_db()[SUBMISSIONS_COLLECTION].find_one(
                {"_id": document["_id"]}
            )
            return cls.submission_response(updated, idempotent_replay=True)
        return cls.submission_response(updated)

    @classmethod
    def submission_response(
        cls, document: dict[str, Any], *, idempotent_replay: bool = False
    ) -> JiraSubmissionResponse:
        attachments = document.get("attachments") or []
        uploaded = sorted(
            item["attachment_id"] for item in attachments if item.get("uploaded")
        )
        required = sorted(item["attachment_id"] for item in attachments)
        tenant_id = document["tenant_id"]
        alert_id = document["alert_id"]
        cluster_id = document.get("cluster_id")
        return JiraSubmissionResponse(
            submission_id=document["submission_id"],
            alert_id=alert_id,
            tenant_id=tenant_id,
            jira_cloud_id=document["jira_cloud_id"],
            issue_id=document["issue_id"],
            issue_key=document["issue_key"],
            issue_updated_at=document["issue_updated_at"],
            state=document["state"],
            source_system=document.get("source_system")
            or (document.get("embedded_alert") or {}).get("source_system"),
            alert_type=document.get("alert_type")
            or (document.get("embedded_alert") or {}).get("alert_type"),
            route_id=document.get("route_id"),
            project_key=document.get("project_key"),
            raw_alert_source=document.get("raw_alert_source"),
            source_reference=document.get("source_reference"),
            embedded_alert_source=document.get("embedded_alert_source"),
            idempotent_replay=idempotent_replay,
            uploaded_attachment_ids=uploaded,
            required_attachment_ids=required,
            cluster_id=cluster_id,
            result=document.get("result"),
            failure=document.get("failure"),
            comments=document.get("comment_receipts") or {},
            trace_path=f"/dashboard/admin/debug/alerts/{alert_id}",
            alert_path=f"/dashboard/{tenant_id}/alerts/{alert_id}",
            cluster_path=(
                f"/dashboard/{tenant_id}/clusters/{cluster_id}" if cluster_id else None
            ),
            created_at=document["created_at"],
            updated_at=document["updated_at"],
        )

    @classmethod
    def cleanup_expired_quarantine(cls) -> int:
        deleted = 0
        for tenant in Tenant.objects.only("db_name"):
            db = DatabaseManager.get_tenant_database(tenant.db_name)
            quarantine = gridfs.GridFS(db, collection=QUARANTINE_BUCKET)
            cursor = db[f"{QUARANTINE_BUCKET}.files"].find(
                {"metadata.expires_at": {"$lte": _now()}}, {"_id": 1}
            )
            for document in cursor:
                try:
                    quarantine.delete(document["_id"])
                    deleted += 1
                except gridfs.errors.NoFile:
                    pass
        return deleted

    @classmethod
    async def cleanup_loop(cls) -> None:
        while True:
            try:
                cls.cleanup_expired_quarantine()
            except Exception:
                # Cleanup is best-effort and must never make the API unavailable.
                pass
            await asyncio.sleep(max(60, QUARANTINE_CLEANUP_SECONDS))
