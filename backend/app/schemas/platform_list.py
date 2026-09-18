from __future__ import annotations

from pydantic import BaseModel

from app.schemas.alert_type_schema import AlertTypeSchemaDocument
from app.schemas.cluster import ClusterListItem
from app.schemas.playbook import PlaybookListItem
from app.schemas.tenant import AlertDocument


class PlatformAlertItem(AlertDocument):
    tenant_name: str


class PlatformClusterItem(ClusterListItem):
    tenant_name: str


class PlatformAlertTypeSchemaItem(AlertTypeSchemaDocument):
    tenant_name: str


class PlatformPlaybookItem(PlaybookListItem):
    tenant_name: str


class PlatformAlertPage(BaseModel):
    items: list[PlatformAlertItem]
    total: int
    skip: int
    limit: int


class PlatformClusterPage(BaseModel):
    items: list[PlatformClusterItem]
    total: int
    skip: int
    limit: int


class PlatformAlertTypeSchemaPage(BaseModel):
    items: list[PlatformAlertTypeSchemaItem]
    total: int
    skip: int
    limit: int


class PlatformPlaybookPage(BaseModel):
    items: list[PlatformPlaybookItem]
    total: int
    skip: int
    limit: int
