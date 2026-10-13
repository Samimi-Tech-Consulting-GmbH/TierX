import os

from pydantic_settings import BaseSettings, SettingsConfigDict
from tierx_runtime import normalize_environment


class Settings(BaseSettings):
    kafka_bootstrap_servers: str = "kafka:9092"
    kafka_received_topic: str = "received"
    kafka_dead_letter_topic: str = "dead_letter_queue"
    kafka_trace_topic: str = "alert_processing_events"

    mongo_url: str
    mongo_db: str = "soc_mind_platform"
    tenant_cache_ttl_seconds: int = 3600
    debug_trace_enabled: bool = False
    debug_trace_max_snapshot_bytes: int = 262_144
    app_release_sha: str = "development"
    app_release_version: str = "development"

    model_config = SettingsConfigDict(
        env_prefix="",
        case_sensitive=False,
    )


normalize_environment()

settings = Settings()
