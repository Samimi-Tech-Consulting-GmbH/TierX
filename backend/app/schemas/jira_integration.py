from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator


MAX_JIRA_ATTACHMENTS = 20
MAX_JIRA_ATTACHMENT_BYTES = 5 * 1024 * 1024
MAX_JIRA_ATTACHMENT_TOTAL_BYTES = 20 * 1024 * 1024
MAX_JIRA_RAW_ALERT_BYTES = 1024 * 1024


class JiraIntegrationState(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class JiraSubmissionState(str, Enum):
    UPLOADING = "UPLOADING"
    ACCEPTED = "ACCEPTED"
    FINALIZING = "FINALIZING"
    PROCESSING = "PROCESSING"
    CLUSTERED = "CLUSTERED"
    ANALYZED = "ANALYZED"
    FAILED = "FAILED"


class JiraCommentKind(str, Enum):
    ACKNOWLEDGEMENT = "ACKNOWLEDGEMENT"
    FINAL = "FINAL"
    ERROR = "ERROR"


class JiraIntegrationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    jira_cloud_id: str = Field(min_length=1, max_length=255)
    jira_site_url: HttpUrl

    @field_validator("jira_site_url")
    @classmethod
    def require_https_site(cls, value: HttpUrl) -> HttpUrl:
        if value.scheme != "https":
            raise ValueError("jira_site_url must use HTTPS")
        return value


class JiraIntegrationDocument(BaseModel):
    integration_id: str
    name: str
    jira_cloud_id: str
    jira_site_url: str | None = None
    state: JiraIntegrationState
    secret_prefix: str
    route_count: int = 0
    created_at: datetime
    updated_at: datetime
    created_by: str
    last_used_at: datetime | None = None
    last_submission_at: datetime | None = None
    legacy_tenant_id: str | None = None


class JiraIntegrationCreated(JiraIntegrationDocument):
    secret: str


class JiraProjectRouteCreate(BaseModel):
    project_key: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z][A-Za-z0-9_\-]*$")
    tenant_id: str = Field(min_length=1, max_length=128)
    source_system: str = Field(min_length=1, max_length=255)
    alert_type: str = Field(min_length=1, max_length=512)
    enabled: bool = True

    @field_validator("project_key")
    @classmethod
    def normalize_project_key(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("source_system")
    @classmethod
    def normalize_source_system(cls, value: str) -> str:
        return value.strip().upper()


class JiraProjectRouteUpdate(JiraProjectRouteCreate):
    pass


class JiraProjectRouteStateUpdate(BaseModel):
    enabled: bool


class JiraProjectRouteDocument(BaseModel):
    route_id: str
    integration_id: str
    project_key: str
    tenant_id: str
    tenant_name: str
    source_system: str
    alert_type: str
    enabled: bool
    revision: int
    effective_schema_id: str | None = None
    effective_schema_version: str | None = None
    event_timestamp_path: str | None = None
    created_at: datetime
    updated_at: datetime
    created_by: str
    updated_by: str
    last_used_at: datetime | None = None
    last_error: dict[str, Any] | None = None


class JiraAttachmentManifest(BaseModel):
    attachment_id: str = Field(min_length=1, max_length=255)
    filename: str = Field(min_length=1, max_length=1024)
    size: int = Field(ge=0, le=MAX_JIRA_ATTACHMENT_BYTES)
    media_type: str | None = Field(default=None, max_length=512)
    created_at: datetime | None = None
    author: dict[str, Any] | None = None


class JiraEmbeddedAlert(BaseModel):
    """A normal TierX ingestion envelope transported inside a Jira issue."""

    tenant_id: str | None = Field(default=None, min_length=1, max_length=128)
    source_system: str = Field(min_length=1, max_length=255)
    alert_type: str = Field(min_length=1, max_length=512)
    timestamp: str = Field(min_length=1, max_length=255)
    raw_payload: dict[str, Any]


class JiraEmbeddedAlertSource(BaseModel):
    kind: str = Field(pattern=r"^(DESCRIPTION|ATTACHMENT)$")
    attachment_id: str | None = Field(default=None, max_length=255)
    filename: str | None = Field(default=None, max_length=1024)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class JiraRawAlertSource(BaseModel):
    kind: str = Field(pattern=r"^(DESCRIPTION|ATTACHMENT)$")
    attachment_id: str | None = Field(default=None, max_length=255)
    filename: str | None = Field(default=None, max_length=1024)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def attachment_metadata_matches_kind(self):
        if self.kind == "ATTACHMENT" and not self.attachment_id:
            raise ValueError("attachment_id is required for ATTACHMENT sources")
        if self.kind == "DESCRIPTION" and (self.attachment_id or self.filename):
            raise ValueError("description sources cannot include attachment metadata")
        return self


class JiraSubmissionCreate(BaseModel):
    jira_cloud_id: str = Field(min_length=1, max_length=255)
    jira_site_url: HttpUrl
    issue_id: str = Field(min_length=1, max_length=255)
    issue_key: str = Field(min_length=1, max_length=255)
    project_key: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z][A-Za-z0-9_\-]*$")
    issue_created_at: datetime
    issue_updated_at: datetime
    raw_alert: dict[str, Any]
    raw_alert_source: JiraRawAlertSource
    # Retained only so historical clients receive a deterministic deprecation
    # error rather than silently treating the old envelope as source data.
    issue: dict[str, Any] | None = None
    comments: list[dict[str, Any]] = Field(default_factory=list)
    changelog: list[dict[str, Any]] = Field(default_factory=list)
    submitted_by: dict[str, Any]
    embedded_alert: JiraEmbeddedAlert | None = None
    embedded_alert_source: JiraEmbeddedAlertSource | None = None
    attachments: list[JiraAttachmentManifest] = Field(
        default_factory=list, max_length=MAX_JIRA_ATTACHMENTS
    )

    @field_validator("jira_site_url")
    @classmethod
    def require_https(cls, value: HttpUrl) -> HttpUrl:
        if value.scheme != "https":
            raise ValueError("jira_site_url must use HTTPS")
        return value

    @field_validator("project_key")
    @classmethod
    def normalize_submission_project_key(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("attachments")
    @classmethod
    def validate_attachment_total(
        cls, value: list[JiraAttachmentManifest]
    ) -> list[JiraAttachmentManifest]:
        if sum(item.size for item in value) > MAX_JIRA_ATTACHMENT_TOTAL_BYTES:
            raise ValueError("attachment manifest exceeds the 20 MiB total limit")
        ids = [item.attachment_id for item in value]
        if len(ids) != len(set(ids)):
            raise ValueError("attachment IDs must be unique")
        return value

    @model_validator(mode="after")
    def reject_legacy_wrapper(self):
        if self.embedded_alert is not None or self.embedded_alert_source is not None:
            raise ValueError(
                "The legacy TierX alert envelope is no longer accepted. "
                "Put only its raw_payload JSON object in the Jira description or attachment."
            )
        wrapper_fields = {"tenant_id", "source_system", "alert_type", "timestamp", "raw_payload"}
        if wrapper_fields.issubset(self.raw_alert):
            raise ValueError(
                "The Jira payload is a legacy TierX envelope. Submit only the raw_payload object."
            )
        raw_size = len(
            json.dumps(
                self.raw_alert,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        if raw_size > MAX_JIRA_RAW_ALERT_BYTES:
            raise ValueError("The raw Jira alert exceeds the 1 MiB limit.")
        return self


class JiraAttachmentUploadResponse(BaseModel):
    submission_id: str
    attachment_id: str
    size: int
    sha256: str
    uploaded: bool = True


class JiraSubmissionResponse(BaseModel):
    submission_id: str
    alert_id: str
    tenant_id: str
    jira_cloud_id: str
    issue_id: str
    issue_key: str
    issue_updated_at: datetime
    state: JiraSubmissionState
    source_system: str | None = None
    alert_type: str | None = None
    route_id: str | None = None
    project_key: str | None = None
    raw_alert_source: JiraRawAlertSource | None = None
    source_reference: dict[str, Any] | None = None
    embedded_alert_source: JiraEmbeddedAlertSource | None = None
    idempotent_replay: bool = False
    uploaded_attachment_ids: list[str] = Field(default_factory=list)
    required_attachment_ids: list[str] = Field(default_factory=list)
    cluster_id: str | None = None
    result: dict[str, Any] | None = None
    failure: dict[str, Any] | None = None
    comments: dict[str, str] = Field(default_factory=dict)
    trace_path: str
    alert_path: str
    cluster_path: str | None = None
    created_at: datetime
    updated_at: datetime


class JiraCommentReceipt(BaseModel):
    kind: JiraCommentKind
    jira_comment_id: str = Field(min_length=1, max_length=255)


class JiraSubmissionFailure(BaseModel):
    failed_stage: str = Field(min_length=1, max_length=128)
    error_type: str = Field(min_length=1, max_length=255)
    error_detail: str = Field(min_length=1, max_length=2000)


class JiraConnectionInfo(BaseModel):
    integration_id: str
    jira_cloud_id: str
    jira_site_url: str | None = None
    name: str
    route_count: int = 0
    state: JiraIntegrationState
