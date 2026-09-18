import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient

from app.core.config import settings

logger = logging.getLogger(__name__)


class TenantCache:
    """
    In-memory cache of active tenants and their allowed source systems,
    backed by MongoDB. Refreshes automatically on a configurable interval.
    """

    def __init__(self) -> None:
        self._client: AsyncIOMotorClient | None = None
        self._tenants: dict[str, set[str]] = {}
        self._last_refreshed: datetime | None = None
        self._refresh_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._client = AsyncIOMotorClient(settings.mongo_url)
        await self._refresh()
        self._refresh_task = asyncio.create_task(self._periodic_refresh())

    async def stop(self) -> None:
        if self._refresh_task is not None:
            self._refresh_task.cancel()
            try:
                await self._refresh_task
            except asyncio.CancelledError:
                pass
            self._refresh_task = None

        if self._client is not None:
            self._client.close()
            self._client = None

    async def _refresh(self) -> None:
        if self._client is None:
            raise RuntimeError("TenantCache is not started")

        db = self._client[settings.mongo_db]
        cursor = db["tenants"].find(
            {"status": "ACTIVE"},
            {"tenant_id": 1, "allowed_source_systems": 1, "_id": 0},
        )

        new_cache: dict[str, set[str]] = {}
        async for doc in cursor:
            tid = doc["tenant_id"]
            sources = doc.get("allowed_source_systems") or []
            new_cache[tid] = {s.upper() for s in sources}

        self._tenants = new_cache
        self._last_refreshed = datetime.now(timezone.utc)
        logger.info(
            "Tenant cache refreshed: %d active tenant(s) loaded", len(new_cache)
        )

    async def _periodic_refresh(self) -> None:
        while True:
            await asyncio.sleep(settings.tenant_cache_ttl_seconds)
            try:
                await self._refresh()
            except Exception:
                logger.exception("Failed to refresh tenant cache; will retry next cycle")

    def is_active_tenant(self, tenant_id: str) -> bool:
        return tenant_id in self._tenants

    def is_source_allowed(self, tenant_id: str, source_system: str) -> bool:
        allowed = self._tenants.get(tenant_id)
        if allowed is None:
            return False
        if not allowed:
            return True
        return source_system.upper() in allowed

    def get_allowed_sources(self, tenant_id: str) -> set[str]:
        return self._tenants.get(tenant_id, set())


tenant_cache = TenantCache()
