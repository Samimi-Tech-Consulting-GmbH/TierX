from datetime import datetime, timezone

import mongoengine as me


class AlertTypeSchema(me.Document):
    """
    Per-tenant alert-type schema versions in collection ``alert_type_schemas``.
    ``tenant_id`` is required and non-nullable at the MongoEngine level.
    """

    schema_id = me.StringField(required=True, unique=True, max_length=64)
    tenant_id = me.StringField(required=True, null=False)
    alert_type = me.StringField(required=True, max_length=512)
    version = me.StringField(required=True, max_length=64)
    description = me.StringField(null=True)
    fields = me.ListField(me.DictField(), default=lambda: [])
    critical_fields = me.ListField(me.StringField(), required=True)
    field_mapping = me.DictField(required=True)
    playbook_id = me.StringField(null=True)
    is_active = me.BooleanField(required=True, default=False)
    severity = me.StringField(null=True)
    created_at = me.DateTimeField(
        required=True, default=lambda: datetime.now(timezone.utc)
    )
    updated_at = me.DateTimeField(
        required=True, default=lambda: datetime.now(timezone.utc)
    )
    created_by = me.StringField(required=True)

    meta = {
        "collection": "alert_type_schemas",
        "db_alias": "default",
        "indexes": [
            {"fields": ["schema_id"], "unique": True},
            {"fields": ["alert_type", "version"], "unique": True},
            "tenant_id",
        ],
    }
