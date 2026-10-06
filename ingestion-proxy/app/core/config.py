import os

from pydantic_settings import BaseSettings, SettingsConfigDict


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


for _field in Settings.model_fields:
    _name = _field.upper()
    if os.environ.get(f"TIERX_{_name}"):
        os.environ[_name] = os.environ[f"TIERX_{_name}"]
    elif _name not in os.environ and f"SOC_MIND_{_name}" in os.environ:
        os.environ[_name] = os.environ[f"SOC_MIND_{_name}"]

settings = Settings()
