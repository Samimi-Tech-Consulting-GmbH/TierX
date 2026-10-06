import asyncio
import logging
import signal

from app.core.config import settings
from app.db.mongodb import close_client, get_database
from tierx_runtime import COLLECTION, IDENTITY, effective, installed, heartbeat
from app.workers.dead_letter_worker import DeadLetterWorker
from app.workers.enrichment_worker import EnrichmentWorker
from app.workers.fingerprint_worker import FingerprintWorker
from app.workers.normalization_worker import NormalizationWorker
from app.workers.validation_worker import ValidationWorker
from app.workers.trace_worker import TraceWorker
from app.workers.correlation_worker import CorrelationClusteringWorker
from app.workers.analysis_worker import AgenticAnalysisWorker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-28s | %(levelname)-5s | %(message)s",
)
logger = logging.getLogger("pipeline")


async def main():
    logger.info("Pipeline service starting")
    logger.info("Kafka: %s", settings.kafka_bootstrap_servers)
    logger.info("MongoDB deployment configured through environment")

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    workers = []
    optional = {}
    while not stop.is_set():
        try:
            db = get_database()
            document = await db[COLLECTION].find_one({"_id": IDENTITY})
            if installed(document):
                values, _ = effective(document.get("values"))
                # Core consumers stay alive: their per-message snapshots isolate active
                # work. Only disabled optional workers drain and stop claiming work.
                desired = {"correlation": values["correlation_enabled"],
                           "analysis": values["llm_analysis_enabled"]}
                for name in list(optional):
                    if not desired[name]:
                        await optional.pop(name).stop()
                settings.values, settings.revision = values, document["revision"]
                if not workers:
                    workers = [ValidationWorker(), NormalizationWorker(), FingerprintWorker(),
                               EnrichmentWorker(), DeadLetterWorker()]
                    if settings.debug_trace_enabled:
                        workers.append(TraceWorker())
                    for worker in workers:
                        await worker.start()
                for name, factory in (("correlation", CorrelationClusteringWorker),
                                      ("analysis", AgenticAnalysisWorker)):
                    if desired[name] and name not in optional:
                        worker = factory()
                        await worker.start()
                        optional[name] = worker
            await db.service_heartbeats.update_one({"service": "pipeline"}, {
                "$set": heartbeat("pipeline", settings.revision)}, upsert=True)
        except Exception:
            logger.warning("Settings refresh failed; retaining last valid configuration")
            try:
                await get_database().service_heartbeats.update_one({"service": "pipeline"}, {
                    "$set": heartbeat("pipeline", settings.revision, "SETTINGS_REFRESH_FAILED")}, upsert=True)
            except Exception:
                pass
        try:
            await asyncio.wait_for(stop.wait(), timeout=5)
        except asyncio.TimeoutError:
            pass

    logger.info("Shutting down workers …")
    for w in [*optional.values(), *workers]:
        await w.stop()

    await close_client()
    logger.info("Pipeline service stopped")


if __name__ == "__main__":
    asyncio.run(main())
