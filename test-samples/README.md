# TierX — Minimal Test Schema Set

Three files that form a complete validation chain for API testing.

## Files

```
test-schemas/
├── base_schema.yml                           # 5 required fields every alert must carry
├── alert_type_schema_splunk_malware.yml      # Field mapping: raw Splunk → ECS
├── valid_alert.json                          # Alert that passes both schemas (JSON — REST API payload)
└── README.md
```

## Quick test

```bash
# Submit the valid alert
curl -s -w "\nHTTP %{http_code}\n" \
  -X POST http://localhost:8001/api/v1/alerts/ingest \
  -H "Content-Type: application/json" \
  -d @valid_alert.json
```

Expected: `202 Accepted` with `{"alert_id": "...", "status": "RECEIVED"}`

## Prerequisites

Before sending the alert, the following must exist in the system:

1. Tenant `test-tenant` created and in ACTIVE status
2. `test-tenant` has `SPLUNK` in its `allowed_source_systems`
3. Base schema uploaded and activated
4. Alert-type schema `splunk.notable.endpoint_malware` uploaded and activated for `test-tenant`

```bash
# 1. Create tenant
curl -s -X POST http://localhost:8000/api/v1/admin/tenants \
  -H "Content-Type: application/json" \
  -d '{
    "name": "test-tenant",
    "display_name": "Test Tenant",
    "contact_email": "test@example.com",
    "allowed_source_systems": ["SPLUNK"]
  }'

# 2. Activate tenant
curl -s -X PUT http://localhost:8000/api/v1/admin/tenants/{tenant_id}/status \
  -H "Content-Type: application/json" \
  -d '{"status": "ACTIVE"}'

# 3. Upload base schema
curl -s -X POST http://localhost:8000/api/v1/admin/schema-registry/base \
  -H "Content-Type: application/json" \
  -d @base_schema.json

# 4. Activate base schema
curl -s -X POST http://localhost:8000/api/v1/admin/schema-registry/base/{schema_id}/activate

# 5. Upload alert-type schema
curl -s -X POST http://localhost:8000/api/v1/tenants/test-tenant/schema-registry \
  -H "Content-Type: application/json" \
  -d @alert_type_schema_splunk_malware.json

# 6. Activate alert-type schema
curl -s -X POST http://localhost:8000/api/v1/tenants/test-tenant/schema-registry/splunk.notable.endpoint_malware/{schema_id}/activate
```
