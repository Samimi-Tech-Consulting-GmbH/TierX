from contextlib import asynccontextmanager
import asyncio

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import PyMongoError
from tierx_runtime import COLLECTION, IDENTITY, installed, heartbeat

from app.api.v1.ingest import router as ingest_router
from app.core.config import settings
from app.services.kafka_publisher import kafka_publisher
from app.services.tenant_cache import tenant_cache


@asynccontextmanager
async def lifespan(app: FastAPI):
    await tenant_cache.start()
    await kafka_publisher.start()
    monitor = asyncio.create_task(configuration_monitor())
    try:
        yield
    finally:
        monitor.cancel()
        try:
            await monitor
        except asyncio.CancelledError:
            pass
        await kafka_publisher.stop()
        await tenant_cache.stop()


app = FastAPI(
    title="TierX Ingestion Proxy",
    version="0.1.0",
    description="Lightweight ingress for alerts: validate tenant, assign alert_id, publish to Kafka.",
    lifespan=lifespan,
)

app.include_router(ingest_router, prefix="/api/v1/alerts")


@app.middleware("http")
async def installation_gate(request, call_next):
    if request.url.path != "/api/v1/health":
        try:
            if not await installation_complete():
                return JSONResponse(status_code=503, content={"detail": "INSTALLATION_REQUIRED"})
        except PyMongoError:
            return JSONResponse(status_code=503, content={"detail": "INSTALLATION_STATUS_UNAVAILABLE"})
    return await call_next(request)


async def installation_complete():
    client = AsyncIOMotorClient(settings.mongo_url, serverSelectionTimeoutMS=2000)
    try:
        document = await client[settings.mongo_db][COLLECTION].find_one({"_id": IDENTITY})
        return installed(document)
    finally:
        client.close()


async def configuration_monitor():
    client = AsyncIOMotorClient(settings.mongo_url, serverSelectionTimeoutMS=2000)
    try:
        while True:
            try:
                db = client[settings.mongo_db]
                document = await db[COLLECTION].find_one({"_id": IDENTITY})
                await db.service_heartbeats.update_one({"service": "ingestion-proxy"}, {
                    "$set": heartbeat("ingestion-proxy", (document or {}).get("revision", 0))}, upsert=True)
            except PyMongoError:
                pass
            await asyncio.sleep(5)
    finally:
        client.close()


@app.get("/api/v1/health")
async def health() -> dict[str, str]:
    try:
        ready = await installation_complete()
    except PyMongoError:
        return {"status": "INSTALLATION_STATUS_UNAVAILABLE"}
    return {
        "status": "healthy" if ready else "INSTALLATION_REQUIRED",
        "kafka_bootstrap_servers": settings.kafka_bootstrap_servers,
        "kafka_received_topic": settings.kafka_received_topic,
        "kafka_dead_letter_topic": settings.kafka_dead_letter_topic,
    }
