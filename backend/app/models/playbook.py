from datetime import datetime, timezone

import mongoengine as me


class Playbook(me.Document):
    """Stored in each tenant DB. Shape follows 3.18 Playbook Context."""

    playbook_id = me.StringField(required=True)
    version = me.IntField(required=True, default=1, min_value=1)
    tenant_id = me.StringField(required=True)
    playbook_name = me.StringField(required=True, max_length=512)
    actions = me.ListField(me.DictField(), default=lambda: [])
    prompt = me.StringField(required=True)
    description = me.StringField(required=True)
    alert_types = me.ListField(me.StringField(), default=lambda: [])
    is_active = me.BooleanField(required=True)
    is_system = me.BooleanField(required=True)
    context_webhook = me.DictField(null=True)
    context_webhooks = me.ListField(me.DictField(), null=True)
    enrichment_actions = me.ListField(me.StringField(), default=lambda: [])
    knowledge_base = me.DictField(default=lambda: {"enabled": False, "top_k": 5})
    created_by = me.StringField(required=True)
    created_at = me.DateTimeField(
        required=True, default=lambda: datetime.now(timezone.utc)
    )
    updated_at = me.DateTimeField(
        required=True, default=lambda: datetime.now(timezone.utc)
    )

    meta = {
        "collection": "playbooks",
        "db_alias": "default",
        "indexes": [
            {"fields": ["playbook_id", "version"], "unique": True},
            "tenant_id",
            "is_active",
        ],
    }
