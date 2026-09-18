# Tenant Data Model

The `Tenant` document is the central representation of a customer organization or isolated workspace within the TierX platform.

All tenants are stored in a shared MongoDB database called `soc_mind_platform`, in the `tenants` collection. The actual alert, entity, and event data for the tenant is stored in a dedicated, isolated database provisioned specifically for that tenant.

## Schema Definition

| Field | Type | Required | Immutable | Description |
|---|---|---|---|---|
| `_id` | ObjectId | Yes | Yes | Internal MongoDB identifier. |
| `tenant_id` | UUID | Yes | Yes | Unique string UUID assigned on creation. Never accepted from user request body. |
| `name` | String | Yes | Yes | Unique URL-friendly slug across all tenants. Enforced by unique index. |
| `display_name` | String | Yes | No | Human-readable name shown in the UI. |
| `db_name` | String | Yes | Yes | The dedicated MongoDB database name for this tenant's data. Format: `soc_mind_tenant_{slug}`. |
| `status` | String (Enum) | Yes | No | Current lifecycle state: `ONBOARDING`, `ACTIVE`, `SUSPENDED`, or `DELETED`. |
| `allowed_source_systems` | List[String] | No | No | List of allowed data source identifiers (e.g., `["SPLUNK", "JIRA", "CORTEX_XDR"]`). |
| `contact_email` | String | No | No | Primary technical or billing contact email for the tenant. |
| `settings` | Dictionary | No | No | Tenant-level configuration overrides (e.g., `similarity_threshold`, `worker_concurrency`). |
| `created_at` | DateTime | Yes | Yes | Timestamp of creation. |
| `updated_at` | DateTime | Yes | No | Timestamp of the last modification. |
| `created_by` | String | No | No | The identifier (email or ID) of the admin who created the tenant. |

## Lifecycle States (Status)

* **ONBOARDING**: The tenant database has been provisioned, but initial setup (schema, alerts, ML models) is incomplete.
* **ACTIVE**: The tenant is fully provisioned and can ingest and process data.
* **SUSPENDED**: The tenant is temporarily locked out. The `TenantResolver` will immediately return a 403 HTTP error for any ingestion or API requests targeting this tenant.
* **DELETED**: The tenant is soft-deleted. Status transitions to DELETED, but the underlying `db_name` database is NOT dropped. Hard deletion is an out-of-band administrative task.

## Database Generation Logic

The `db_name` is automatically generated on creation using the assigned `name`.
Given a `name` like `"example-corp"`, the `db_name` will be initialized as `"soc_mind_tenant_example_corp"`.

The underlying MongoDB database and its core collections/indexes are immediately provisioned when the tenant document is persisted.

## Example JSON Document

```json
{
  "_id": {
    "$oid": "651adafa1234abcd567890ef"
  },
  "tenant_id": "a1b2c3d4-e5f6-4a5b-8c9d-0e1f2a3b4c5d",
  "name": "example-corp",
  "display_name": "Example Corporation",
  "db_name": "soc_mind_tenant_example_corp",
  "status": "ACTIVE",
  "allowed_source_systems": ["SPLUNK", "CORTEX_XDR"],
  "contact_email": "soc-admin@example.com",
  "settings": {
    "similarity_threshold": 0.85,
    "default_model": "phi3"
  },
  "created_at": "2026-03-10T14:30:00Z",
  "updated_at": "2026-03-10T14:30:00Z",
  "created_by": "platform.admin@example.com"
}
```
