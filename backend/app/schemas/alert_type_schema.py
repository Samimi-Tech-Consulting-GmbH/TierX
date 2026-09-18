from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


_SEMVER_RE = (
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(-(0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))?(\+[0-9a-zA-Z-]+)?$"
)


class AlertTypeSchemaYamlPayload(BaseModel):
    """
    Accepts alert-type schema YAML/fragment. Server-owned fields are stripped before validation.
    Unknown keys are ignored so optional blocks (e.g. future deduplication) do not break imports.
    """

    model_config = ConfigDict(extra="ignore")

    alert_type: str = Field(..., min_length=1, max_length=512)
    version: str = Field(..., pattern=_SEMVER_RE, max_length=64)
    description: Optional[str] = Field(None, max_length=4000)
    field_mapping: Dict[str, str]
    critical_fields: List[str]
    fields: List[Dict[str, Any]] = Field(default_factory=list)
    severity: Optional[str] = None

    @field_validator("field_mapping")
    @classmethod
    def normalize_mapping(cls, v: Dict[Any, Any]) -> Dict[str, str]:
        if not v:
            raise ValueError("field_mapping must not be empty")
        out: Dict[str, str] = {}
        for raw_k, raw_val in v.items():
            k = str(raw_k).strip()
            if not k:
                raise ValueError("field_mapping keys must be non-empty strings")
            if raw_val is None:
                raise ValueError(f"field_mapping[{k!r}] must not be null")
            value = str(raw_val).strip()
            if not value:
                raise ValueError(f"field_mapping[{k!r}] must not be empty")
            out[k] = value

        by_source: Dict[str, List[str]] = {}
        for ecs, source in out.items():
            by_source.setdefault(source, []).append(ecs)
        duplicates = {
            source: sorted(ecs_keys)
            for source, ecs_keys in by_source.items()
            if len(ecs_keys) > 1
        }
        if duplicates:
            details = "; ".join(
                f"{source!r} → {ecs_keys}"
                for source, ecs_keys in sorted(duplicates.items())
            )
            raise ValueError(
                "field_mapping has the same source path mapped to multiple ECS "
                f"fields: {details}"
            )
        return out

    @field_validator("critical_fields")
    @classmethod
    def normalize_critical(cls, v: List[Any]) -> List[str]:
        if not v:
            raise ValueError("critical_fields must be a non-empty list")
        out: List[str] = []
        for i, item in enumerate(v):
            s = str(item).strip()
            if not s:
                raise ValueError(f"critical_fields[{i}] must be a non-empty string")
            out.append(s)
        return out

    @field_validator("fields")
    @classmethod
    def normalize_fields(cls, v: Any) -> List[Dict[str, Any]]:
        if v is None:
            return []
        if not isinstance(v, list):
            raise ValueError("fields must be a list of objects when provided")
        for i, item in enumerate(v):
            if not isinstance(item, dict):
                raise ValueError(f"fields[{i}] must be an object")
        return v

    @field_validator("severity", mode="before")
    @classmethod
    def coerce_severity(cls, v: Any) -> Optional[str]:
        if v is None or v == "":
            return None
        return str(v)


class AlertTypeSchemaDocument(BaseModel):
    """Stored alert-type schema document returned by the API."""

    model_config = ConfigDict(populate_by_name=True)

    id: Optional[str] = Field(None, alias="_id")
    schema_id: str
    tenant_id: str
    alert_type: str
    version: str
    description: Optional[str] = None
    fields: List[Dict[str, Any]]
    critical_fields: List[str]
    field_mapping: Dict[str, Any]
    playbook_id: Optional[str] = None
    is_active: bool
    severity: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    created_by: str


class AlertTypeSchemaListResponse(BaseModel):
    items: List[AlertTypeSchemaDocument]
    total: int
    skip: int
    limit: int
