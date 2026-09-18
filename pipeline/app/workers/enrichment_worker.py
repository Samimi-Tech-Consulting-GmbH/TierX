"""
Enrichment Worker
─────────────────
Consumes from the ``distinct`` topic.

1. Looks up the active playbook for the alert's ``alert_type`` — first via
   the alert-type schema's ``playbook_id`` link, then by scanning playbooks
   whose ``alert_types`` list contains the type.
2. Builds an enriched Kafka message, optionally including the playbook prompt.
3. Produces to the ``enriched`` topic.

The worker records enrichment state and matched playbook metadata on the alert.
If no playbook is found the message is still produced without a ``prompt``
field. Exceptions are dead-lettered with ``error_type = ENRICHMENT_FAILURE``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.core.config import settings
from app.db.mongodb import get_client
from app.schemas.messages import DistinctAlertMessage, EnrichedAlertMessage
from app.services.schema_registry import get_active_schema, get_tenant_db_name
from app.services.playbook_context_webhook import PlaybookContextWebhookClient
from app.services.enrichment_action import EnrichmentActionCoordinator
from app.services.knowledge_base import KnowledgeBaseRetriever
from app.workers.base import BaseWorker

PLAYBOOKS_COLLECTION = "playbooks"
ALERTS_COLLECTION = "alerts"


class EnrichmentWorker(BaseWorker):

    def __init__(self):
        super().__init__(
            name="enrichment",
            input_topic=settings.kafka_distinct_topic,
            output_topic=settings.kafka_enriched_topic,
        )
        self._action_coordinator = EnrichmentActionCoordinator(
            self.produce, self.logger
        )
        self._knowledge_base = KnowledgeBaseRetriever()

    async def start(self):
        await super().start()
        if settings.enrichment_actions_enabled:
            await self._action_coordinator.start()

    async def stop(self):
        if settings.enrichment_actions_enabled:
            await self._action_coordinator.stop()
        await super().stop()

    async def _handle(self, msg: Any):
        """Route enrichment failures to DLQ with ENRICHMENT_FAILURE."""
        try:
            result = await self.process(msg.value)
            if result is not None and self.output_topic:
                await self.produce(self.output_topic, result)
        except Exception as exc:
            self.logger.exception("Enrichment failed — routing to dead-letter")
            await self.produce_dead_letter(
                alert_id=msg.value.get("alert_id", "unknown"),
                tenant_id=msg.value.get("tenant_id"),
                alert_type=msg.value.get("alert_type"),
                source_system=msg.value.get("source_system"),
                raw_payload=msg.value.get("raw_payload"),
                error_type="ENRICHMENT_FAILURE",
                error_detail=str(exc),
                failed_stage="ENRICHMENT",
            )

    async def _resolve_playbook(
        self,
        tenant_id: str,
        alert_type: str,
    ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        """Find the active playbook for *alert_type* in the tenant DB."""
        resolution: dict[str, Any] = {
            "schema_link_attempted": False,
            "schema_playbook_id": None,
            "alert_type_fallback_attempted": False,
            "resolution": "NONE",
        }
        db_name = await get_tenant_db_name(tenant_id)
        if db_name is None:
            resolution["tenant_database_resolved"] = False
            return None, resolution
        resolution["tenant_database_resolved"] = True

        schema = await get_active_schema(tenant_id, alert_type)
        tenant_db = get_client()[db_name]
        playbooks_col = tenant_db[PLAYBOOKS_COLLECTION]

        if schema and schema.get("playbook_id"):
            resolution["schema_link_attempted"] = True
            resolution["schema_playbook_id"] = schema["playbook_id"]
            pb = await playbooks_col.find_one(
                {"playbook_id": schema["playbook_id"], "is_active": True},
                sort=[("version", -1)],
            )
            if pb:
                resolution["resolution"] = "SCHEMA_LINK"
                return pb, resolution

        resolution["alert_type_fallback_attempted"] = True
        playbook = await playbooks_col.find_one(
            {"alert_types": alert_type, "is_active": True, "tenant_id": tenant_id},
            sort=[("version", -1), ("playbook_id", 1)],
        )
        if playbook:
            resolution["resolution"] = "ALERT_TYPE_FALLBACK"
        return playbook, resolution

    async def process(self, data: dict[str, Any]) -> dict[str, Any] | None:
        async with self.trace_span("ENRICHMENT", data) as trace:
            msg = DistinctAlertMessage.model_validate(data)

            playbook, resolution = await self._resolve_playbook(
                msg.tenant_id, msg.alert_type
            )
            prompt: str | None = playbook.get("prompt") if playbook else None
            playbook_id = playbook.get("playbook_id") if playbook else None
            playbook_version = playbook.get("version") if playbook else None
            resolution.update(
                {
                    "matched_playbook_id": playbook_id,
                    "matched_playbook_version": playbook_version,
                    "prompt_present": prompt is not None,
                }
            )

            if playbook:
                self.logger.info(
                    "alert_id=%s matched playbook=%s",
                    msg.alert_id,
                    playbook_id,
                )
            else:
                self.logger.info(
                    "alert_id=%s — no playbook for alert_type=%s, producing without prompt",
                    msg.alert_id,
                    msg.alert_type,
                )

            enriched = EnrichedAlertMessage(
                alert_id=msg.alert_id,
                tenant_id=msg.tenant_id,
                alert_type=msg.alert_type,
                source_system=msg.source_system,
                normalized_payload=msg.normalized_payload,
                raw_payload=msg.raw_payload,
                source_reference=msg.source_reference,
                fingerprint=msg.fingerprint,
                prompt=prompt,
            )
            output = enriched.model_dump(exclude_none=True)

            db_name = await get_tenant_db_name(msg.tenant_id)
            kb_config = (playbook or {}).get("knowledge_base") or {}
            kb_context: dict[str, Any] = {
                "status": "SKIPPED",
                "retrieval_version": "kb-retrieval-v1",
                "query_sha256": None,
                "query_summary": {},
                "matches": [],
                "reason": (
                    "FEATURE_DISABLED"
                    if bool(kb_config.get("enabled"))
                    and not settings.knowledge_base_retrieval_enabled
                    else "PLAYBOOK_DISABLED"
                ),
            }
            if (
                db_name
                and settings.knowledge_base_retrieval_enabled
                and bool(kb_config.get("enabled"))
            ):
                try:
                    kb_context = await self._knowledge_base.search_alert(
                        get_client()[db_name],
                        alert_type=msg.alert_type,
                        normalized_payload=msg.normalized_payload,
                        top_k=int(kb_config.get("top_k") or 5),
                        tenant_id=msg.tenant_id,
                        retrieval_mode=kb_config.get("retrieval_mode", "deterministic"),
                    )
                except Exception as exc:
                    self.logger.exception(
                        "Knowledge Base retrieval failed alert_id=%s", msg.alert_id
                    )
                    kb_context = {
                        "status": "ERROR",
                        "retrieval_version": "kb-retrieval-v1",
                        "query_sha256": None,
                        "query_summary": {},
                        "matches": [],
                        "error": {
                            "code": type(exc).__name__,
                            "detail": "Knowledge Base retrieval failed",
                        },
                    }
            resolution["knowledge_base"] = {
                key: value for key, value in kb_context.items() if key != "matches"
            }
            resolution["knowledge_base"]["matches"] = [
                {key: value for key, value in match.items() if key != "text"}
                for match in kb_context.get("matches") or []
            ]
            configured_action_codes = (
                list(playbook.get("enrichment_actions") or []) if playbook else []
            )
            if (
                db_name
                and settings.enrichment_actions_enabled
                and configured_action_codes
            ):
                tenant_db = get_client()[db_name]
                queued = await self._action_coordinator.queue(
                    db_name=db_name,
                    tenant_id=msg.tenant_id,
                    alert=msg.model_dump(),
                    playbook=playbook,
                    output_message=output,
                )
                await tenant_db[ALERTS_COLLECTION].update_one(
                    {"alert_id": msg.alert_id},
                    {
                        "$set": {
                            "playbook_id": playbook_id,
                            "playbook_version": playbook_version,
                            "playbook_resolution": resolution["resolution"],
                            "enrichment.kb_context": kb_context,
                            "updated_at": datetime.now(timezone.utc),
                        }
                    },
                )
                resolution["enrichment_actions"] = {
                    **queued,
                    "configured_order": configured_action_codes,
                }
                await trace.finish(
                    "SUCCEEDED",
                    output_value={"queued_action_batch": queued},
                    checks=[
                        {
                            "name": "enrichment_action_batch",
                            "outcome": "SUCCEEDED",
                            "warning": None,
                        }
                    ],
                    decisions=resolution,
                )
                self.logger.info(
                    "Queued %d enrichment action(s) alert_id=%s batch_id=%s",
                    len(configured_action_codes),
                    msg.alert_id,
                    queued["batch_id"],
                )
                return None
            webhook_context = None
            webhook_contexts = None
            if db_name:
                tenant_db = get_client()[db_name]
                alerts_collection = tenant_db[ALERTS_COLLECTION]
                existing_alert = await alerts_collection.find_one(
                    {"alert_id": msg.alert_id},
                    {
                        "_id": 0,
                        "prompt_webhook_context": 1,
                        "prompt_webhook_contexts": 1,
                    },
                )
                if playbook:
                    webhook_client = PlaybookContextWebhookClient(tenant_db)
                    if playbook.get("context_webhooks") is not None:
                        webhook_contexts = await webhook_client.execute_many(
                            tenant_id=msg.tenant_id,
                            alert=msg.model_dump(),
                            playbook=playbook,
                            existing=(existing_alert or {}).get(
                                "prompt_webhook_contexts"
                            ),
                        )
                    else:
                        webhook_context = await webhook_client.execute(
                            tenant_id=msg.tenant_id,
                            alert=msg.model_dump(),
                            playbook=playbook,
                            existing=(existing_alert or {}).get(
                                "prompt_webhook_context"
                            ),
                        )
                update_fields = {
                    "kafka_state": "ENRICHED",
                    "enriched": True,
                    "playbook_id": playbook_id,
                    "playbook_version": playbook_version,
                    "playbook_resolution": resolution["resolution"],
                    "enrichment.kb_context": kb_context,
                    "updated_at": datetime.now(timezone.utc),
                }
                if webhook_context is not None:
                    update_fields["prompt_webhook_context"] = webhook_context
                if webhook_contexts is not None:
                    update_fields["prompt_webhook_contexts"] = webhook_contexts
                await alerts_collection.update_one(
                    {"alert_id": msg.alert_id},
                    {"$set": update_fields},
                )

            webhook_decision = None
            if webhook_context:
                webhook_decision = {
                    key: value
                    for key, value in webhook_context.items()
                    if key != "prompt_footer"
                }
            resolution["playbook_context_webhook"] = webhook_decision
            webhook_decisions = None
            if webhook_contexts is not None:
                webhook_decisions = [
                    {
                        key: value
                        for key, value in context.items()
                        if key != "prompt_footer"
                    }
                    for context in webhook_contexts
                ]
            resolution["playbook_context_webhooks"] = webhook_decisions

            await trace.finish(
                "SUCCEEDED",
                output_value=output,
                checks=[
                    {
                        "name": "playbook_resolution",
                        "outcome": "SUCCEEDED",
                        "warning": (
                            None if playbook else "No matching playbook; prompt omitted"
                        ),
                    }
                ],
                decisions=resolution,
            )
            self.logger.info("Enriched alert_id=%s", msg.alert_id)
            return output
