"""
Async service for looking up alert-type schemas from tenant databases.

Tenants are stored in ``soc_mind_platform.tenants``.  Each tenant's alert-type
schemas live in their own database (``db_name``) in the ``alert_type_schemas``
collection.
"""

from __future__ import annotations

import logging
from typing import Any

from app.db.mongodb import get_database, get_client

logger = logging.getLogger(__name__)


async def get_tenant_db_name(tenant_id: str) -> str | None:
    """Return the ``db_name`` for an active tenant, or *None* if not found."""
    db = get_database()
    doc = await db["tenants"].find_one(
        {"tenant_id": tenant_id, "status": "ACTIVE"},
        {"db_name": 1, "_id": 0},
    )
    if doc is None:
        return None
    return doc["db_name"]


async def get_active_schema(
    tenant_id: str, alert_type: str,
) -> dict[str, Any] | None:
    """
    Look up the active alert-type schema for *alert_type* in the tenant's
    dedicated database.  Returns the schema document dict or *None*.
    """
    db_name = await get_tenant_db_name(tenant_id)
    if db_name is None:
        logger.warning("No active tenant found for tenant_id=%s", tenant_id)
        return None

    client = get_client()
    tenant_db = client[db_name]
    schema = await tenant_db["alert_type_schemas"].find_one(
        {"alert_type": alert_type, "is_active": True, "tenant_id": tenant_id},
    )
    return schema
