"""Task-local adapter for invoking existing stage logic on isolated V2 data."""

from contextlib import contextmanager
from contextvars import ContextVar

scope = ContextVar("tierx_workflow_storage", default=None)
ALIASES = {
    "alerts": "v2_alerts",
    "clusters": "v2_clusters",
    "analysis_runs": "v2_analysis_runs",
    "alert_processing_events": "v2_processing_events",
    "dead_letters": "v2_dead_letters",
}


@contextmanager
def isolated(db_name, tenant_id, cohort):
    token = scope.set((db_name, tenant_id, cohort))
    try:
        yield
    finally:
        scope.reset(token)


class Collection:
    def __init__(self, collection, cohort):
        self.raw, self.cohort = collection, cohort

    def query(self, query=None):
        return {"$and": [query or {}, {"cohort": self.cohort}]}

    def find(self, query=None, *args, **kwargs):
        return self.raw.find(self.query(query), *args, **kwargs)

    async def find_one(self, query=None, *args, **kwargs):
        return await self.raw.find_one(self.query(query), *args, **kwargs)

    async def update_one(self, query, update, **kwargs):
        return await self._update("update_one", query, update, **kwargs)

    async def update_many(self, query, update, **kwargs):
        return await self._update("update_many", query, update, **kwargs)

    async def find_one_and_update(self, query, update, **kwargs):
        return await self._update("find_one_and_update", query, update, **kwargs)

    async def _update(self, method, query, update, **kwargs):
        if not isinstance(update, dict) or any(
            not key.startswith("$") for key in update
        ):
            raise ValueError("V2 requires operator updates")
        if any("cohort" in values for values in update.values()):
            raise ValueError("Cohort cannot be overwritten")
        update = {
            **update,
            "$setOnInsert": {**update.get("$setOnInsert", {}), "cohort": self.cohort},
        }
        return await getattr(self.raw, method)(self.query(query), update, **kwargs)

    async def insert_one(self, document):
        return await self.raw.insert_one({**document, "cohort": self.cohort})

    async def count_documents(self, query, **kwargs):
        return await self.raw.count_documents(self.query(query), **kwargs)

    async def create_index(self, *args, **kwargs):
        return await self.raw.create_index(*args, **kwargs)


class Client:
    def __init__(self, raw, selected):
        self.raw, self.selected = raw, selected

    def __getitem__(self, name):
        db_name, tenant_id, cohort = self.selected
        if name == db_name:
            return Database(self.raw[name], cohort)
        if name == "soc_mind_platform":
            return Platform(self.raw[name], tenant_id)
        raise ValueError("V2 cross-tenant database access rejected")


class Database:
    def __init__(self, raw, cohort):
        self.raw, self.cohort = raw, cohort

    def __getitem__(self, name):
        return (
            Collection(self.raw[ALIASES[name]], self.cohort)
            if name in ALIASES
            else self.raw[name]
        )


def wrap(client):
    selected = scope.get()
    return Client(client, selected) if selected else client


class Platform:
    def __init__(self, raw, tenant_id):
        self.raw, self.tenant_id = raw, tenant_id

    def __getitem__(self, name):
        return (
            TenantCollection(self.raw[name], self.tenant_id)
            if name == "tenants"
            else self.raw[name]
        )


class TenantCollection:
    def __init__(self, raw, tenant_id):
        self.raw, self.tenant_id = raw, tenant_id

    def query(self, query=None):
        return {"$and": [query or {}, {"tenant_id": self.tenant_id}]}

    def find(self, query=None, *args, **kwargs):
        return self.raw.find(self.query(query), *args, **kwargs)

    async def find_one(self, query=None, *args, **kwargs):
        return await self.raw.find_one(self.query(query), *args, **kwargs)
