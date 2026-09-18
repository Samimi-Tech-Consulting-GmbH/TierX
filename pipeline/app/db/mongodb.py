from motor.motor_asyncio import AsyncIOMotorClient

from app.core.config import settings

_client: AsyncIOMotorClient | None = None


def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(settings.mongo_url, tz_aware=True)
    return _client


def get_database():
    return get_client()[settings.mongo_db]


async def close_client():
    global _client
    if _client is not None:
        _client.close()
        _client = None
