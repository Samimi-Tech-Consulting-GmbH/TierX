import os
from datetime import datetime
from enum import Enum
from typing import Any, List, Literal, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    field_validator,
    model_validator,
)


class PlaybookAdapterEnum(str, Enum):
    """3.24.2 PlaybookAdapterEnum — allowed adapter values for playbook actions."""

    SPLUNK_SPL = "SPLUNK_SPL"
    CORTEX_XDR_QUERY = "CORTEX_XDR_QUERY"
    GENERIC_HTTP = "GENERIC_HTTP"
    NEO4J_CYPHER = "NEO4J_CYPHER"
    QRADAR_AQL = "QRADAR_AQL"
    WAZUH_API = "WAZUH_API"
    MISP_LOOKUP = "MISP_LOOKUP"
    KB_VECTOR_SEARCH = "KB_VECTOR_SEARCH"


class PlaybookAction(BaseModel):
    """3.19 Playbook Action — all fields required for API validation."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1)
    adapter: PlaybookAdapterEnum
    query_template: str = Field(..., min_length=1)
    query_input_fields: List[str] = Field(default_factory=list)
    time: datetime
    result: str = Field(..., min_length=1)


class PlaybookContextWebhook(BaseModel):
    """Optional, non-secret callback used to add tenant context to a prompt."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    url: HttpUrl
    timeout_seconds: int = Field(5, ge=1, le=10)

    @field_validator("url")
    @classmethod
    def validate_destination(cls, value: HttpUrl) -> HttpUrl:
        if value.scheme != "https":
            raise ValueError("context_webhook.url must use HTTPS")
        if value.username or value.password:
            raise ValueError("context_webhook.url must not contain credentials")
        if value.query:
            raise ValueError("context_webhook.url must not contain a query string")
        if value.fragment:
            raise ValueError("context_webhook.url must not contain a fragment")
        return value


class PlaybookContextWebhookProvider(PlaybookContextWebhook):
    """A stable, ordered context provider in a playbook revision."""

    webhook_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$",
    )
    name: str = Field(..., min_length=1, max_length=128)


class PlaybookKnowledgeBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    top_k: int = Field(default=5, ge=1, le=20)
    retrieval_mode: Literal["deterministic", "hybrid"] = "deterministic"


def _validate_webhook_configuration(model: Any) -> Any:
    if model.context_webhook is not None and model.context_webhooks is not None:
        raise ValueError(
            "context_webhook and context_webhooks cannot both be configured"
        )
    if model.enrichment_actions and (
        model.context_webhook is not None or model.context_webhooks is not None
    ):
        raise ValueError(
            "enrichment_actions cannot be combined with prototype context_webhook(s)"
        )
    providers = model.context_webhooks or []
    maximum = max(1, min(10, int(os.getenv("PLAYBOOK_WEBHOOK_MAX_COUNT", "10"))))
    if len(providers) > maximum:
        raise ValueError(
            f"context_webhooks cannot contain more than {maximum} providers"
        )
    provider_ids = [provider.webhook_id for provider in providers]
    if len(provider_ids) != len(set(provider_ids)):
        raise ValueError("context_webhooks webhook_id values must be unique")
    if len(model.enrichment_actions) > 10:
        raise ValueError("enrichment_actions cannot contain more than 10 action codes")
    if len(model.enrichment_actions) != len(set(model.enrichment_actions)):
        raise ValueError("enrichment_actions action codes must be unique")
    return model


class PlaybookDefinitionPayload(BaseModel):
    """
    YAML/JSON fragment for create (no server-owned identity timestamps).
    playbook_id, tenant_id, playbook_name, created_* are owned by the server/form.
    actions and alert_types may be omitted (empty arrays).
    """

    model_config = ConfigDict(extra="forbid")

    actions: List[PlaybookAction] = Field(default_factory=list)
    prompt: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    alert_types: List[str] = Field(default_factory=list)
    is_active: bool
    is_system: bool
    context_webhook: Optional[PlaybookContextWebhook] = None
    context_webhooks: Optional[List[PlaybookContextWebhookProvider]] = Field(
        default=None, max_length=10
    )
    enrichment_actions: List[str] = Field(
        default_factory=list,
        max_length=10,
    )
    knowledge_base: PlaybookKnowledgeBase = Field(default_factory=PlaybookKnowledgeBase)

    @field_validator("enrichment_actions")
    @classmethod
    def validate_enrichment_action_codes(cls, value: List[str]) -> List[str]:
        pattern = __import__("re").compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
        if any(not pattern.fullmatch(code) for code in value):
            raise ValueError("enrichment_actions contains an invalid action code")
        return value

    @model_validator(mode="after")
    def validate_webhook_configuration(self):
        return _validate_webhook_configuration(self)


class PlaybookListItem(BaseModel):
    playbook_id: str
    version: int
    tenant_id: str
    playbook_name: str
    alert_types: List[str]
    is_active: bool
    is_system: bool
    context_webhook: Optional[PlaybookContextWebhook] = None
    context_webhooks: Optional[List[PlaybookContextWebhookProvider]] = None
    enrichment_actions: List[str] = Field(default_factory=list)
    knowledge_base: PlaybookKnowledgeBase = Field(default_factory=PlaybookKnowledgeBase)
    created_at: datetime
    updated_at: datetime


class PlaybookOut(BaseModel):
    """3.18 Playbook Context — full document returned by GET / POST / PUT."""

    playbook_id: str
    version: int
    tenant_id: str
    playbook_name: str
    actions: List[dict[str, Any]]
    prompt: str
    description: str
    alert_types: List[str]
    is_active: bool
    is_system: bool
    context_webhook: Optional[PlaybookContextWebhook] = None
    context_webhooks: Optional[List[PlaybookContextWebhookProvider]] = None
    enrichment_actions: List[str] = Field(default_factory=list)
    knowledge_base: PlaybookKnowledgeBase = Field(default_factory=PlaybookKnowledgeBase)
    created_by: str
    created_at: datetime
    updated_at: datetime


class PlaybookDocument(PlaybookOut):
    id: Optional[str] = Field(None, alias="_id")

    model_config = ConfigDict(populate_by_name=True)


class PlaybookVersionSummary(BaseModel):
    playbook_id: str
    version: int
    playbook_name: str
    alert_types: List[str]
    is_active: bool
    is_system: bool
    context_webhook: Optional[PlaybookContextWebhook] = None
    context_webhooks: Optional[List[PlaybookContextWebhookProvider]] = None
    enrichment_actions: List[str] = Field(default_factory=list)
    knowledge_base: PlaybookKnowledgeBase = Field(default_factory=PlaybookKnowledgeBase)
    created_by: str
    created_at: datetime
    updated_at: datetime


class PlaybookStats(BaseModel):
    total_playbooks: int = 0
    active_playbooks: int = 0
    system_playbooks: int = 0
    covered_alert_types: int = 0


class PlaybookReplace(BaseModel):
    """
    PUT body — snapshots the latest revision plus these fields into a **new row**
    with an auto-incremented ``version``.
    playbook_id / tenant_id / version are unchanged on the logical key; timestamps
    and ``created_by`` are set fresh for each revision row.
    """

    model_config = ConfigDict(extra="forbid")

    playbook_name: str = Field(..., min_length=1, max_length=512)
    actions: List[PlaybookAction] = Field(default_factory=list)
    prompt: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    alert_types: List[str] = Field(default_factory=list)
    is_active: bool
    is_system: bool
    context_webhook: Optional[PlaybookContextWebhook] = None
    context_webhooks: Optional[List[PlaybookContextWebhookProvider]] = Field(
        default=None, max_length=10
    )
    enrichment_actions: List[str] = Field(default_factory=list, max_length=10)
    knowledge_base: PlaybookKnowledgeBase = Field(default_factory=PlaybookKnowledgeBase)

    @field_validator("enrichment_actions")
    @classmethod
    def validate_enrichment_action_codes(cls, value: List[str]) -> List[str]:
        pattern = __import__("re").compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
        if any(not pattern.fullmatch(code) for code in value):
            raise ValueError("enrichment_actions contains an invalid action code")
        return value

    @model_validator(mode="after")
    def validate_webhook_configuration(self):
        return _validate_webhook_configuration(self)
