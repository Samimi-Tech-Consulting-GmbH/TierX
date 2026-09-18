import base64
import os

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    kafka_bootstrap_servers: str = "kafka:9092"

    # Topic names
    kafka_received_topic: str = "received"
    kafka_validated_topic: str = "validated"
    kafka_normalized_topic: str = "normalized"
    kafka_enriched_topic: str = "enriched"
    kafka_clustered_topic: str = "clustered"
    kafka_distinct_topic: str = "distinct"
    kafka_dead_letter_topic: str = "dead_letter_queue"
    kafka_trace_topic: str = "alert_processing_events"

    # MongoDB
    mongo_url: str
    mongo_db: str = "soc_mind_platform"

    # Deduplication
    deduplication_window_minutes: int = 60
    debug_trace_enabled: bool = False
    debug_trace_retention_days: int = 7
    debug_trace_max_snapshot_bytes: int = 262_144
    app_release_sha: str = "development"
    app_release_version: str = "development"

    # Correlation and clustering
    correlation_enabled: bool = False
    correlation_lookback_hours: int = 24
    correlation_scheduler_interval_seconds: int = 60
    correlation_debounce_critical_ms: int = 0
    correlation_debounce_high_ms: int = 120_000
    correlation_debounce_medium_ms: int = 300_000
    correlation_debounce_low_ms: int = 600_000

    # Ollama / LLM
    ollama_url: str = "http://ollama:11434"
    ollama_model: str = "phi3:latest"
    ollama_model_digest: str = ""
    llm_analysis_enabled: bool = False
    llm_timeout_seconds: int = 120
    llm_max_tokens: int = 2048
    llm_context_max_bytes: int = 65_536
    llm_scheduler_interval_seconds: int = 5
    llm_job_lease_seconds: int = 1_200
    llm_retry_backoff_seconds: str = "5,10,20"

    # Signed playbook context webhooks
    playbook_context_webhooks_enabled: bool = False
    webhook_secret_encryption_key: str = ""
    playbook_webhook_max_request_bytes: int = 262_144
    playbook_webhook_max_response_bytes: int = 16_384
    playbook_webhook_max_total_prompt_bytes: int = 65_536
    playbook_webhook_timestamp_tolerance_seconds: int = 300
    playbook_webhook_max_count: int = 10
    playbook_webhook_max_concurrency: int = 5

    # Platform-managed pluggable enrichment actions
    enrichment_actions_enabled: bool = False
    enrichment_action_max_count: int = 10
    enrichment_action_max_concurrency: int = 5
    enrichment_action_scheduler_interval_seconds: int = 2
    enrichment_action_max_request_bytes: int = 262_144
    enrichment_action_max_response_bytes: int = 32_768
    enrichment_action_max_context_bytes: int = 16_384

    # Tenant Knowledge Base retrieval
    knowledge_base_retrieval_enabled: bool = False
    knowledge_base_max_candidates: int = 500
    knowledge_base_max_documents: int = 500
    knowledge_base_prompt_max_bytes: int = 32_768

    @model_validator(mode="after")
    def validate_webhook_encryption(self):
        if self.playbook_context_webhooks_enabled or self.enrichment_actions_enabled:
            try:
                key = base64.urlsafe_b64decode(
                    self.webhook_secret_encryption_key
                    + "=" * (-len(self.webhook_secret_encryption_key) % 4)
                )
            except Exception as exc:
                raise ValueError(
                    "WEBHOOK_SECRET_ENCRYPTION_KEY must be base64url"
                ) from exc
            if len(key) != 32:
                raise ValueError(
                    "WEBHOOK_SECRET_ENCRYPTION_KEY must decode to 32 bytes"
                )
        return self

    model_config = SettingsConfigDict(
        env_prefix="",
        case_sensitive=False,
    )


for _field in Settings.model_fields:
    _name = _field.upper()
    if f"TIERX_{_name}" in os.environ:
        os.environ[_name] = os.environ[f"TIERX_{_name}"]
    elif _name not in os.environ and f"SOC_MIND_{_name}" in os.environ:
        os.environ[_name] = os.environ[f"SOC_MIND_{_name}"]

settings = Settings()
