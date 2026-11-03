import logging
import os
import signal
import time
from datetime import datetime, timezone

from tierx_runtime import normalize_environment
normalize_environment()

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


def refresh_configuration(db, previous):
    try:
        document = db[COLLECTION].find_one({"_id": IDENTITY})
        values, _ = effective((document or {}).get("values"))
        return (document, values), None
    except Exception:
        logger.warning("Configuration refresh failed; retaining last validated configuration")
        return previous, "SETTINGS_REFRESH_FAILED"


def report_heartbeat(db, revision, configuration_error, processing_error=None):
    try:
        value = heartbeat("knowledge-base-processor", revision, configuration_error)
        value["processing_error"] = processing_error
        db.service_heartbeats.update_one({"service": "knowledge-base-processor"}, {"$set": value}, upsert=True)
    except Exception:
        logger.warning("Processor heartbeat could not be persisted")


def main() -> None:
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    DatabaseManager.initialize()
    interval = max(1, int(os.getenv("KNOWLEDGE_BASE_PROCESSOR_INTERVAL_SECONDS", "5")))
    lease = max(60, int(os.getenv("KNOWLEDGE_BASE_PROCESSOR_LEASE_SECONDS", "600")))
    platform_db = DatabaseManager.get_tenant_database("soc_mind_platform")
    logger.info("Knowledge Base processor ready")
    cached_configuration = None
    processing_error = None
    loop_error = None
    while running:
        processed = False
        cached_configuration, refresh_error = refresh_configuration(platform_db, cached_configuration)
        configuration, values = cached_configuration or (None, {})
        revision = (configuration or {}).get("revision", 0)
        report_heartbeat(platform_db, revision, refresh_error, processing_error or loop_error)
        if not installed(configuration) or not values.get("knowledge_base_processing_enabled"):
            time.sleep(5)
            continue
        try:
            for tenant in Tenant.objects(status__ne="DELETED").only("db_name"):
                db = DatabaseManager.get_tenant_database(str(tenant.db_name))
                KnowledgeBaseService._ensure_database_indexes(db)
                document = KnowledgeBaseService.claim_next(db, lease_seconds=lease)
                if not document:
                    continue
                processed = True
                try:
                    count = KnowledgeBaseService.process_claimed(db, document)
                    processing_error = None
                    report_heartbeat(platform_db, revision, refresh_error, processing_error or loop_error)
                    logger.info(
                        "Indexed document_id=%s chunks=%d",
                        document["document_id"],
                        count,
                    )
                except Exception:
                    logger.exception("Failed document_id=%s", document["document_id"])
                    processing_error = "PROCESSING_FAILED"
                    report_heartbeat(platform_db, revision, refresh_error, processing_error)
        except Exception:
            logger.warning("Processor work failed")
            loop_error = "PROCESSING_FAILED"
            report_heartbeat(platform_db, revision, refresh_error, processing_error or loop_error)
        else:
            # A clean idle pass proves loop recovery, but not document recovery.
            if loop_error:
                loop_error = None
                report_heartbeat(platform_db, revision, refresh_error, processing_error)
        if not processed:
            time.sleep(interval)


if __name__ == "__main__":
    main()
