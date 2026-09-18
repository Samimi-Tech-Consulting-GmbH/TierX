import os
from mongoengine import connect, disconnect, connection

MONGO_URL = os.environ["MONGO_URL"]

class DatabaseManager:
    """Manages MongoEngine connection aliases safely."""

    @staticmethod
    def initialize():
        """Creates the default connection to the platform database."""
        connect(
            db="soc_mind_platform",
            host=MONGO_URL,
            alias="default",
            uuidRepresentation="standard"
        )

    @staticmethod
    def get_tenant_db_alias(db_name: str) -> str:
        """
        Ensures a connection alias exists for the tenant database
        and returns the alias name.
        """
        alias = f"tenant_{db_name}"
        if alias not in connection._connections:
            connect(
                db=db_name,
                host=MONGO_URL,
                alias=alias,
                uuidRepresentation="standard"
            )
        return alias

    @staticmethod
    def get_tenant_database(db_name: str):
        """Return a tenant database without mutating MongoEngine model state.

        Tenant data lives on the same MongoDB deployment as the platform
        database.  Accessing it through the already-initialized default
        connection is safe for concurrent requests and avoids ``switch_db``,
        whose temporary mutation of a document class' alias can leak one
        tenant's query into another request.
        """
        return connection.get_connection("default")[db_name]
