from datetime import datetime, timezone
import mongoengine as me


class User(me.Document):
    user_id = me.StringField(required=True, unique=True)
    email = me.StringField(required=True, unique=True)
    hashed_password = me.StringField(required=True)
    role = me.StringField(
        required=True,
        choices=["PLATFORM_ADMIN", "TENANT_ADMIN", "TENANT_OPERATOR"],
    )
    tenant_id = me.StringField(null=True)
    is_active = me.BooleanField(default=True)
    created_at = me.DateTimeField(default=lambda: datetime.now(timezone.utc))
    updated_at = me.DateTimeField(default=lambda: datetime.now(timezone.utc))
    created_by = me.StringField(null=True)

    meta = {
        "collection": "users",
        "db_alias": "default",
        "indexes": ["user_id", "email", "tenant_id", "role"],
    }
