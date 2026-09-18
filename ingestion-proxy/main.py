from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.ingest import router as ingest_router
from app.core.config import settings
from app.services.kafka_publisher import kafka_publisher
from app.services.tenant_cache import tenant_cache


@asynccontextmanager
async def lifespan(app: FastAPI):
    await tenant_cache.start()
    await kafka_publisher.start()
    try:
        yield
    finally:
        await kafka_publisher.stop()
        await tenant_cache.stop()


app = FastAPI(
    title="TierX Ingestion Proxy",
    version="0.1.0",
    description="Lightweight ingress for alerts: validate tenant, assign alert_id, publish to Kafka.",
    lifespan=lifespan,
)

app.include_router(ingest_router, prefix="/api/v1/alerts")


@app.get("/api/v1/health")
async def health() -> dict[str, str]:
    return {
        "status": "healthy",
        "kafka_bootstrap_servers": settings.kafka_bootstrap_servers,
        "kafka_received_topic": settings.kafka_received_topic,
        "kafka_dead_letter_topic": settings.kafka_dead_letter_topic,
    }
