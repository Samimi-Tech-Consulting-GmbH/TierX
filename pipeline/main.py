import asyncio
import logging
import signal

from app.core.config import settings
from app.db.mongodb import close_client
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
    logger.info("MongoDB: %s", settings.mongo_url.split("@")[-1])

    workers = [
        ValidationWorker(),
        NormalizationWorker(),
        FingerprintWorker(),
        EnrichmentWorker(),
        DeadLetterWorker(),
    ]
    if settings.debug_trace_enabled:
        workers.append(TraceWorker())
    if settings.correlation_enabled:
        workers.append(CorrelationClusteringWorker())
    if settings.llm_analysis_enabled:
        workers.append(AgenticAnalysisWorker())

    for w in workers:
        await w.start()

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    logger.info("Pipeline service ready — %d worker(s) running", len(workers))
    await stop.wait()

    logger.info("Shutting down workers …")
    for w in workers:
        await w.stop()

    await close_client()
    logger.info("Pipeline service stopped")


if __name__ == "__main__":
    asyncio.run(main())
