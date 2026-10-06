import logging
import os
import signal
import time
from datetime import datetime, timezone

for _key, _value in tuple(os.environ.items()):
    if _key.startswith("TIERX_") and _value:
        os.environ[_key.removeprefix("TIERX_")] = _value
for _key, _value in tuple(os.environ.items()):
    if _key.startswith("SOC_MIND_"):
        _unprefixed = _key.removeprefix("SOC_MIND_")
        if _unprefixed not in os.environ and f"TIERX_{_unprefixed}" not in os.environ:
            os.environ[_unprefixed] = _value

from app.db.mongodb import DatabaseManager
from app.models.tenant import Tenant
from app.services.knowledge_base_service import KnowledgeBaseService
from tierx_runtime import COLLECTION, IDENTITY, effective, installed, heartbeat

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | kb-processor | %(levelname)-5s | %(message)s",
)
logger = logging.getLogger("kb-processor")
running = True


def stop(*_args):
    global running
    running = False


def main() -> None:
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    DatabaseManager.initialize()
    interval = max(1, int(os.getenv("KNOWLEDGE_BASE_PROCESSOR_INTERVAL_SECONDS", "5")))
    lease = max(60, int(os.getenv("KNOWLEDGE_BASE_PROCESSOR_LEASE_SECONDS", "600")))
    platform_db = DatabaseManager.get_tenant_database("soc_mind_platform")
    logger.info("Knowledge Base processor ready")
    while running:
        processed = False
        try:
            configuration = platform_db[COLLECTION].find_one({"_id": IDENTITY})
            values, _ = effective((configuration or {}).get("values"))
            platform_db.service_heartbeats.update_one({"service": "knowledge-base-processor"}, {
                "$set": heartbeat("knowledge-base-processor", (configuration or {}).get("revision", 0))}, upsert=True)
            if not installed(configuration) or not values["knowledge_base_processing_enabled"]:
                time.sleep(5)
                continue
            platform_db.service_heartbeats.update_one(
                {"service": "knowledge-base-processor"},
                {
                    "$set": {
                        "service": "knowledge-base-processor",
                        "seen_at": datetime.now(timezone.utc),
                    }
                },
                upsert=True,
            )
            for tenant in Tenant.objects(status__ne="DELETED").only("db_name"):
                db = DatabaseManager.get_tenant_database(str(tenant.db_name))
                KnowledgeBaseService._ensure_database_indexes(db)
                document = KnowledgeBaseService.claim_next(db, lease_seconds=lease)
                if not document:
                    continue
                processed = True
                try:
                    count = KnowledgeBaseService.process_claimed(db, document)
                    logger.info(
                        "Indexed document_id=%s chunks=%d",
                        document["document_id"],
                        count,
                    )
                except Exception:
                    logger.exception("Failed document_id=%s", document["document_id"])
        except Exception:
            logger.warning("Processor iteration failed; retaining last valid configuration")
            try:
                platform_db.service_heartbeats.update_one({"service": "knowledge-base-processor"}, {
                    "$set": {"configuration_error": "SETTINGS_REFRESH_FAILED"}}, upsert=True)
            except Exception:
                pass
        if not processed:
            time.sleep(interval)


if __name__ == "__main__":
    main()
