import logging
from typing import Optional, Dict

class TenantResolver:
    """
    In-memory cache for mapping simple tenant assertions quickly,
    handling suspension logic for ingestion paths avoiding DB hops initially.
    """
    _status_cache: Dict[str, str] = {}

    @classmethod
    def update_status(cls, tenant_id: str, status: str):
        """Update the cached status for a given tenant."""
        cls._status_cache[tenant_id] = status
        logging.info(f"TenantResolver updated: {tenant_id} status set to {status}")

    @classmethod
    def invalidate(cls, tenant_id: str):
        """Remove a tenant from the cache."""
        if tenant_id in cls._status_cache:
            del cls._status_cache[tenant_id]
            logging.info(f"TenantResolver invalidated cache for {tenant_id}")

    @classmethod
    def get_status(cls, tenant_id: str) -> Optional[str]:
        """Get the current cached status of a tenant."""
        return cls._status_cache.get(tenant_id)

tenant_resolver = TenantResolver()
