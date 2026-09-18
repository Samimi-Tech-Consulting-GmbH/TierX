from datetime import datetime, timezone
import mongoengine as me

class Tenant(me.Document):
    """
    MongoEngine Document for the Tenant schema in the soc_mind_platform database.
    This acts as the single source of truth for the database schema.
    """
    tenant_id = me.StringField(required=True, unique=True)
    name = me.StringField(required=True, unique=True, max_length=255)
    display_name = me.StringField(required=True, max_length=255)
    db_name = me.StringField(required=True, unique=True)

    status = me.StringField(required=True, choices=["ONBOARDING", "ACTIVE", "SUSPENDED", "DELETED"])
    allowed_source_systems = me.ListField(me.StringField())
    contact_email = me.EmailField(null=True)
    settings = me.DictField(default=dict)

    created_at = me.DateTimeField(default=lambda: datetime.now(timezone.utc))
    updated_at = me.DateTimeField(default=lambda: datetime.now(timezone.utc))
    created_by = me.StringField(null=True)

    meta = {
        'collection': 'tenants',
        'db_alias': 'default',   # Always stored in soc_mind_platform
        'indexes': [
            'name',
            'tenant_id',
            'status'
        ]
    }
