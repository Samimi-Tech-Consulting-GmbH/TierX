import re
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Tuple, Any
from uuid import uuid4
from bson import ObjectId
from bson.errors import InvalidId
import mongoengine as me
from mongoengine.queryset.visitor import Q

from app.schemas.tenant import (
    TenantCreate,
    TenantUpdate,
    TenantStatusUpdate,
    TenantDocument,
    TenantPage,
    TenantStatus,
    PipelineHealthSummary,
    TenantSelfServiceSettingsUpdate,
    DeadLetterRecord,
    DeadLetterPage,
    AlertDocument,
    AlertPage,
    AlertStats,
)
from app.models.tenant import Tenant
from app.core.errors import DuplicateResourceError, ResourceNotFoundError
from app.core.tenant_resolver import tenant_resolver
from app.db.mongodb import DatabaseManager
from app.core.alert_metrics import (
    aggregate_alert_stats,
    build_alert_query,
    severity_from_alert,
)


class TenantService:
    @staticmethod
    def _tenant_query(
        status: Optional[TenantStatus] = None,
        search: Optional[str] = None,
    ):
        query = Tenant.objects
        if status:
            query = query(status=status.value)
        if search:
            query = query(Q(name__icontains=search) | Q(display_name__icontains=search))
        return query

    @staticmethod
    def _tenant_document(tenant: Tenant) -> TenantDocument:
        doc_dict = tenant.to_mongo().to_dict()
        doc_dict["_id"] = str(doc_dict["_id"])
        return TenantDocument(**doc_dict)

    @staticmethod
    def _generate_db_name(slug: str) -> str:
        # replace any non-alphanumeric chars with underscores for safety
        safe_slug = re.sub(r"[^a-zA-Z0-9]", "_", slug).lower()
        return f"soc_mind_tenant_{safe_slug}"

    @classmethod
    def provision_tenant_database(cls, db_name: str):
        """
        Creates the required initial schema for the new tenant using pymongo
        accessed through the mongoengine connection wrapper.
        """
        alias = DatabaseManager.get_tenant_db_alias(db_name)
        db = me.connection.get_db(alias)

        # Create alerting collections & indexes
        alerts_col = db["alerts"]
        alerts_col.create_index("rule_id")
        alerts_col.create_index("created_at")
        alerts_col.create_index([("severity", 1), ("created_at", -1)])

        # Retain the legacy collection while provisioning the upload MVP's
        # metadata collection and dedicated GridFS bucket lazily.
        kb_col = db["knowledge_base"]
        kb_col.create_index("document_id", unique=True)
        kb_documents = db["kb_documents"]
        kb_documents.create_index("document_id", unique=True)
        kb_documents.create_index([("uploaded_at", -1), ("document_id", -1)])

        # Add basic onboarding tracking
        onboarding_col = db["onboarding_status"]
        if onboarding_col.count_documents({}) == 0:
            onboarding_col.insert_one(
                {
                    "base_schema_configured": True,
                    "base_schema_configured_at": datetime.now(timezone.utc),
                    "alert_type_registered": False,
                    "fp_rule_defined": False,
                    "kb_document_uploaded": False,
                    "import_completed": False,
                    "live_alert_received": False,
                }
            )

        from app.services.alert_type_schema_service import AlertTypeSchemaService
        from app.services.playbook_service import PlaybookService

        PlaybookService.reconcile_indexes_for_db_alias(alias)
        AlertTypeSchemaService.reconcile_indexes_for_db_alias(alias)

    @classmethod
    def initialize_schema(cls):
        """Ensure the core platform tenant schema indexes exist."""
        # MongoEngine ensures indexes automatically when models are loaded
        # but we can explicitly call it
        Tenant.ensure_indexes()

    @classmethod
    def create_tenant(cls, tenant_in: TenantCreate, created_by: str) -> TenantDocument:
        db_name = cls._generate_db_name(tenant_in.name)

        # Check for duplication
        if Tenant.objects(name=tenant_in.name).first():
            raise DuplicateResourceError("A tenant with this name already exists")

        new_tenant = Tenant(
            tenant_id=str(uuid4()),
            name=tenant_in.name,
            display_name=tenant_in.display_name,
            db_name=db_name,
            status=TenantStatus.ONBOARDING.value,
            allowed_source_systems=tenant_in.allowed_source_systems,
            contact_email=tenant_in.contact_email,
            settings=tenant_in.settings,
            created_by=created_by,
        )
        new_tenant.save()

        # Provision the database
        cls.provision_tenant_database(db_name)

        # Invalidate/set cache
        tenant_resolver.update_status(new_tenant.tenant_id, new_tenant.status)

        doc_dict = new_tenant.to_mongo().to_dict()
        doc_dict["_id"] = str(doc_dict["_id"])
        return TenantDocument(**doc_dict)

    @classmethod
    def get_tenants(
        cls,
        skip: int = 0,
        limit: int = 100,
        status: Optional[TenantStatus] = None,
        search: Optional[str] = None,
    ) -> List[TenantDocument]:
        query = cls._tenant_query(status=status, search=search)
        return [cls._tenant_document(t) for t in query.skip(skip).limit(limit)]

    @classmethod
    def get_tenant_page(
        cls,
        skip: int = 0,
        limit: int = 10,
        status: Optional[TenantStatus] = None,
        search: Optional[str] = None,
    ) -> TenantPage:
        query = cls._tenant_query(status=status, search=search)
        total = query.count()
        items = [cls._tenant_document(t) for t in query.skip(skip).limit(limit)]
        return TenantPage(items=items, total=total, skip=skip, limit=limit)

    @classmethod
    def get_tenant_by_id(cls, tenant_id: str) -> TenantDocument:
        tenant = Tenant.objects(tenant_id=tenant_id).first()
        if not tenant:
            raise ResourceNotFoundError(f"Tenant with ID {tenant_id} not found")

        doc_dict = tenant.to_mongo().to_dict()
        doc_dict["_id"] = str(doc_dict["_id"])
        return TenantDocument(**doc_dict)

    @classmethod
    def update_tenant(
        cls, tenant_id: str, tenant_update: TenantUpdate
    ) -> TenantDocument:
        tenant = Tenant.objects(tenant_id=tenant_id).first()
        if not tenant:
            raise ResourceNotFoundError(f"Tenant with ID {tenant_id} not found")

        update_data = tenant_update.model_dump(exclude_unset=True)
        for immutable in ["tenant_id", "db_name", "name", "_id"]:
            update_data.pop(immutable, None)

        if update_data:
            update_data["updated_at"] = datetime.now(timezone.utc)
            tenant.modify(**update_data)

        doc_dict = tenant.to_mongo().to_dict()
        doc_dict["_id"] = str(doc_dict["_id"])
        return TenantDocument(**doc_dict)

    @classmethod
    def update_tenant_status(
        cls, tenant_id: str, status_update: TenantStatusUpdate
    ) -> TenantDocument:
        tenant = Tenant.objects(tenant_id=tenant_id).first()
        if not tenant:
            raise ResourceNotFoundError(f"Tenant with ID {tenant_id} not found")

        current_status = tenant.status
        new_status = status_update.status.value

        valid_transitions = {
            TenantStatus.ONBOARDING.value: [
                TenantStatus.ACTIVE.value,
                TenantStatus.DELETED.value,
            ],
            TenantStatus.ACTIVE.value: [
                TenantStatus.SUSPENDED.value,
                TenantStatus.DELETED.value,
            ],
            TenantStatus.SUSPENDED.value: [
                TenantStatus.ACTIVE.value,
                TenantStatus.DELETED.value,
            ],
            TenantStatus.DELETED.value: [],
        }

        if new_status not in valid_transitions.get(current_status, []):
            raise ValueError(
                f"Invalid status transition from {current_status} to {new_status}"
            )

        tenant.modify(status=new_status, updated_at=datetime.now(timezone.utc))

        # Update Cache
        tenant_resolver.update_status(tenant_id, new_status)

        doc_dict = tenant.to_mongo().to_dict()
        doc_dict["_id"] = str(doc_dict["_id"])
        return TenantDocument(**doc_dict)

    @classmethod
    def get_onboarding_status(cls, tenant_id: str) -> dict:
        tenant = Tenant.objects(tenant_id=tenant_id).first()
        if not tenant:
            raise ResourceNotFoundError(f"Tenant with ID {tenant_id} not found")

        alias = DatabaseManager.get_tenant_db_alias(tenant.db_name)
        db = me.connection.get_db(alias)
        status_doc = db["onboarding_status"].find_one({}, {"_id": 0})
        if not status_doc:
            return {}
        return status_doc

    @classmethod
    def merge_self_service_settings(
        cls,
        tenant_id: str,
        patch: TenantSelfServiceSettingsUpdate,
    ) -> TenantDocument:
        tenant = Tenant.objects(tenant_id=tenant_id).first()
        if not tenant:
            raise ResourceNotFoundError(f"Tenant with ID {tenant_id} not found")

        data = patch.model_dump(exclude_unset=True)
        if not data:
            doc_dict = tenant.to_mongo().to_dict()
            doc_dict["_id"] = str(doc_dict["_id"])
            return TenantDocument(**doc_dict)

        settings = dict(tenant.settings or {})
        if "similarity_threshold" in data:
            settings["similarity_threshold"] = data["similarity_threshold"]
        if "worker_concurrency" in data:
            settings["worker_concurrency"] = data["worker_concurrency"]
        if "default_model" in data:
            settings["default_model"] = data["default_model"]
        for name in (
            "correlation_debounce_critical_ms",
            "correlation_debounce_high_ms",
            "correlation_debounce_medium_ms",
            "correlation_debounce_low_ms",
        ):
            if name in data:
                settings[name] = data[name]

        extra = {}
        if "contact_email" in data:
            extra["contact_email"] = data["contact_email"]

        tenant.modify(
            settings=settings,
            updated_at=datetime.now(timezone.utc),
            **extra,
        )
        doc_dict = tenant.to_mongo().to_dict()
        doc_dict["_id"] = str(doc_dict["_id"])
        return TenantDocument(**doc_dict)

    @classmethod
    def get_pipeline_health_summary(cls, tenant_id: str) -> PipelineHealthSummary:
        tenant = Tenant.objects(tenant_id=tenant_id).first()
        if not tenant:
            raise ResourceNotFoundError(f"Tenant with ID {tenant_id} not found")

        alias = DatabaseManager.get_tenant_db_alias(tenant.db_name)
        db = me.connection.get_db(alias)
        coll = db["alerts"]

        total_alerts = coll.count_documents({})
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        alerts_last_24h = coll.count_documents({"created_at": {"$gte": since}})

        escalated_count = coll.count_documents(
            {"status": {"$regex": r"^ESCALATED$", "$options": "i"}}
        )
        error_count = coll.count_documents(
            {"status": {"$regex": r"^ERROR$", "$options": "i"}}
        )
        dl_coll = db["dead_letters"]
        dead_letter_count = dl_coll.count_documents({})
        dead_letters_last_24h = dl_coll.count_documents(
            {"received_at": {"$gte": since}}
        )

        return PipelineHealthSummary(
            total_alerts=total_alerts,
            alerts_last_24h=alerts_last_24h,
            escalated_count=escalated_count,
            error_count=error_count,
            dead_letter_count=dead_letter_count,
            dead_letters_last_24h=dead_letters_last_24h,
        )

    @staticmethod
    def _dead_letter_from_mongo(raw: dict) -> DeadLetterRecord:
        ff = raw.get("failed_fields")
        if not isinstance(ff, list):
            ff = []
        return DeadLetterRecord(
            id=str(raw["_id"]),
            alert_id=raw.get("alert_id"),
            tenant_id=raw.get("tenant_id"),
            source_system=raw.get("source_system"),
            alert_type=raw.get("alert_type"),
            status=raw.get("status"),
            kafka_state=raw.get("kafka_state"),
            error_type=raw.get("error_type"),
            error_detail=raw.get("error_detail"),
            failed_stage=raw.get("failed_stage"),
            failed_fields=ff,
            raw_payload=raw.get("raw_payload"),
            received_at=raw.get("received_at"),
            dead_lettered_at=raw.get("dead_lettered_at"),
            analysis_run_id=raw.get("analysis_run_id"),
            analysis_scope_type=raw.get("analysis_scope_type"),
            analysis_scope_id=raw.get("analysis_scope_id"),
            requested_analysis_version=raw.get("requested_analysis_version"),
            retry_cycle=raw.get("retry_cycle"),
            source_alert=raw.get("source_alert"),
            fingerprint=raw.get("fingerprint"),
        )

    @classmethod
    def list_dead_letters(
        cls,
        tenant_id: str,
        skip: int = 0,
        limit: int = 50,
        since_hours: Optional[int] = None,
    ) -> DeadLetterPage:
        tenant = Tenant.objects(tenant_id=tenant_id).first()
        if not tenant:
            raise ResourceNotFoundError(f"Tenant with ID {tenant_id} not found")

        alias = DatabaseManager.get_tenant_db_alias(tenant.db_name)
        db = me.connection.get_db(alias)
        coll = db["dead_letters"]

        query: dict = {}
        if since_hours is not None:
            since = datetime.now(timezone.utc) - timedelta(hours=since_hours)
            query["received_at"] = {"$gte": since}

        total = coll.count_documents(query)
        cursor = (
            coll.find(query)
            .sort([("received_at", -1), ("_id", -1)])
            .skip(skip)
            .limit(limit)
        )
        items = [cls._dead_letter_from_mongo(doc) for doc in cursor]
        return DeadLetterPage(items=items, total=total)

    @classmethod
    def get_dead_letter(cls, tenant_id: str, dead_letter_id: str) -> DeadLetterRecord:
        tenant = Tenant.objects(tenant_id=tenant_id).first()
        if not tenant:
            raise ResourceNotFoundError(f"Tenant with ID {tenant_id} not found")

        try:
            oid = ObjectId(dead_letter_id)
        except InvalidId:
            raise ResourceNotFoundError("Dead-letter entry not found")

        alias = DatabaseManager.get_tenant_db_alias(tenant.db_name)
        db = me.connection.get_db(alias)
        doc = db["dead_letters"].find_one({"_id": oid})
        if not doc:
            raise ResourceNotFoundError("Dead-letter entry not found")
        return cls._dead_letter_from_mongo(doc)

    @staticmethod
    def _alert_from_mongo(raw: dict) -> AlertDocument:
        return AlertDocument(
            id=str(raw["_id"]),
            alert_id=raw.get("alert_id", ""),
            tenant_id=raw.get("tenant_id", ""),
            alert_type=raw.get("alert_type", ""),
            source_system=raw.get("source_system", ""),
            raw_payload=raw.get("raw_payload"),
            source_reference=raw.get("source_reference"),
            normalized_payload=raw.get("normalized_payload"),
            severity=severity_from_alert(raw),
            status=raw.get("status"),
            kafka_state=raw.get("kafka_state"),
            fingerprint=raw.get("fingerprint"),
            validated=raw.get("validated"),
            normalized=raw.get("normalized"),
            enriched=raw.get("enriched"),
            playbook_id=raw.get("playbook_id"),
            playbook_version=raw.get("playbook_version"),
            playbook_resolution=raw.get("playbook_resolution"),
            prompt_webhook_context=raw.get("prompt_webhook_context"),
            prompt_webhook_contexts=raw.get("prompt_webhook_contexts"),
            enrichment_action_batch_id=raw.get("enrichment_action_batch_id"),
            enrichment_action_status=raw.get("enrichment_action_status"),
            enrichment_action_results=raw.get("enrichment_action_results"),
            enrichment=raw.get("enrichment"),
            cluster_id=raw.get("cluster_id"),
            clustering_status=raw.get("clustering_status"),
            debounce_outcome=raw.get("debounce_outcome"),
            analysis_type=raw.get("analysis_type"),
            correlation_result=raw.get("correlation_result"),
            analysis_status=raw.get("analysis_status"),
            analysis_error=raw.get("analysis_error"),
            requested_analysis_version=raw.get("requested_analysis_version"),
            analyzed_version=raw.get("analyzed_version"),
            last_analysis_requested_at=raw.get("last_analysis_requested_at"),
            last_analyzed_at=raw.get("last_analyzed_at"),
            alert_analysis=raw.get("alert_analysis"),
            created_at=raw.get("created_at"),
            updated_at=raw.get("updated_at"),
        )

    @classmethod
    def list_alerts(
        cls,
        tenant_id: str,
        skip: int = 0,
        limit: int = 50,
        since_hours: Optional[int] = None,
        q: Optional[str] = None,
    ) -> AlertPage:
        tenant = Tenant.objects(tenant_id=tenant_id).first()
        if not tenant:
            raise ResourceNotFoundError(f"Tenant with ID {tenant_id} not found")

        alias = DatabaseManager.get_tenant_db_alias(tenant.db_name)
        db = me.connection.get_db(alias)
        coll = db["alerts"]

        query, search = build_alert_query(q=q, since_hours=since_hours)

        total = coll.count_documents(query)
        if search:
            cursor = coll.aggregate(
                [
                    {"$match": query},
                    {
                        "$addFields": {
                            "_exact_rank": {
                                "$cond": [{"$eq": ["$alert_id", search]}, 0, 1]
                            }
                        }
                    },
                    {"$sort": {"_exact_rank": 1, "created_at": -1, "_id": -1}},
                    {"$skip": skip},
                    {"$limit": limit},
                    {"$project": {"_exact_rank": 0}},
                ]
            )
        else:
            cursor = (
                coll.find(query)
                .sort([("created_at", -1), ("_id", -1)])
                .skip(skip)
                .limit(limit)
            )
        items = [cls._alert_from_mongo(doc) for doc in cursor]
        return AlertPage(items=items, total=total)

    @classmethod
    def get_alert_stats(
        cls,
        tenant_id: str,
        *,
        since_hours: Optional[int] = None,
        q: Optional[str] = None,
    ) -> AlertStats:
        tenant = Tenant.objects(tenant_id=tenant_id).first()
        if not tenant:
            raise ResourceNotFoundError(f"Tenant with ID {tenant_id} not found")
        db = DatabaseManager.get_tenant_database(str(tenant.db_name))
        query, _ = build_alert_query(q=q, since_hours=since_hours)
        return AlertStats(**aggregate_alert_stats(db["alerts"], query))

    @classmethod
    def get_alert(cls, tenant_id: str, alert_id: str) -> AlertDocument:
        tenant = Tenant.objects(tenant_id=tenant_id).first()
        if not tenant:
            raise ResourceNotFoundError(f"Tenant with ID {tenant_id} not found")

        alias = DatabaseManager.get_tenant_db_alias(tenant.db_name)
        db = me.connection.get_db(alias)
        doc = db["alerts"].find_one({"alert_id": alert_id})
        if not doc:
            raise ResourceNotFoundError("Alert not found")
        return cls._alert_from_mongo(doc)
