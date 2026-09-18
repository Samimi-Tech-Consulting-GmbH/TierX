# Pipeline Test Scenarios — valid & invalid samples per worker

Sample data for every pipeline stage: **alerts** (per-topic Kafka messages and HTTP ingest bodies), **alert-type schemas** (YAML uploads), and **playbooks** (YAML uploads). Each file states in its header comment whether it is valid or invalid and what the expected outcome is. All samples use one consistent demo world:

| Object | Value |
|---|---|
| Tenant | `tenant-demo` (db `soc_mind_tenant_demo`, allowed sources: SPLUNK, CORTEX_XDR) |
| Alert type A | `splunk.notable.endpoint_malware` — schema linked to playbook `pb-malware-triage` |
| Alert type B | `splunk.notable.phishing` — schema WITHOUT playbook link; playbook `pb-phishing` matches via `alert_types` |
| Alert type C | `splunk.notable.poisoned` — schema valid at upload, fails every alert at validation |
| Playbooks | `pb-malware-triage`, `pb-phishing`, `pb-system-default` (`is_system=true`) |

## Setup

```bash
make up
docker exec -i socmind_mongodb mongosh -u root -p example < seed/mongo-seed.js
```

Kafka console tools must run **inside** the broker container (it advertises `kafka:9092`):

```bash
# consume a topic (watch results):
docker exec -it socmind_kafka /opt/kafka/bin/kafka-console-consumer.sh \
  --bootstrap-server kafka:9092 --topic <topic> --from-beginning

# produce a sample file to a topic (message must be one line):
jq -c . <file>.json | docker exec -i socmind_kafka \
  /opt/kafka/bin/kafka-console-producer.sh --bootstrap-server kafka:9092 --topic <topic>
```

## Scenario matrix

### 1. Ingestion Proxy — `POST http://localhost:8001/api/v1/alerts/ingest`

| File | Expected outcome |
|---|---|
| `01-ingestion/alert-valid.json` | `200`, alert on `received` topic |
| `01-ingestion/alert-invalid-missing-timestamp.json` | `422`, DLQ `ALERT_SCHEMA_MISSING` (body validation) |
| `01-ingestion/alert-invalid-unknown-tenant.json` | `422`, DLQ `UNKNOWN_TENANT` |
| `01-ingestion/alert-invalid-unknown-source.json` | `422`, DLQ `UNKNOWN_SOURCE` (WAZUH not allowed) |

### 2. Validation Worker — produce to `received`, watch `validated` / `dead_letter_queue`

| File | Expected outcome |
|---|---|
| `02-validation/received-valid.json` | forwarded to `validated` |
| `02-validation/received-invalid-no-schema.json` | DLQ `ALERT_SCHEMA_MISSING` (no schema for `unknown.custom_type`) |
| `02-validation/received-invalid-missing-critical-field.json` | DLQ `MISSING_REQUIRED_FIELD` (`source.ip` — payload has no `result.src`) |

### 3. Normalization Worker — produce to `validated`, watch `normalized`

| File | Expected outcome |
|---|---|
| `03-normalization/validated-valid.json` | ECS `normalized_payload` built, alert document inserted in Mongo, forwarded to `normalized` |
| `03-normalization/validated-invalid-unknown-tenant.json` | DLQ `NORMALIZATION_FAILED` (tenant db not resolvable) |

### 4. Fingerprint Worker — produce to `normalized`, watch `distinct`

| File | Expected outcome |
|---|---|
| `04-fingerprint/normalized-valid-unique.json` | fingerprint computed, forwarded to `distinct` |
| `04-fingerprint/normalized-duplicate-1.json` + `-2.json` | 1st → `distinct`; 2nd → DLQ `DUPLICATED_ALERT` (same ECS hash fields, different `alert_id`) |

**Note:** the duplicate check reads the `alerts` collection, which is populated by the Normalization Worker. To demo deduplication, inject the duplicate pair at the `validated` topic (or send `01-ingestion/alert-valid.json` twice through the proxy) — injecting directly at `normalized` skips the Mongo insert and both messages come out distinct.

### 5. Enrichment Worker — produce to `distinct`, watch `enriched`

| File | Expected outcome |
|---|---|
| `05-enrichment/distinct-valid-schema-playbook.json` | resolution tier (a): schema `playbook_id` → `pb-malware-triage`; message on `enriched` carries its `prompt` |
| `05-enrichment/distinct-valid-alert-type-fallback.json` | resolution tier (b): schema has no `playbook_id` → playbook matched via `alert_types` → `pb-phishing` prompt |
| `05-enrichment/distinct-edge-no-playbook.json` | **current code:** forwarded to `enriched` WITHOUT `prompt`. **Future target:** SYSTEM default `pb-system-default`, DLQ `ENRICHMENT_FAILURE` only if that is missing too |
| `05-enrichment/distinct-invalid-malformed.json` | DLQ `ENRICHMENT_FAILURE` (message fails contract validation — no `fingerprint`/`normalized_payload`) |

### 6. Correlation Worker — produce to `enriched`, watch `clustered`

| File | Expected outcome |
|---|---|
| `06-correlation/enriched-shared-ip-a.json` | Creates an open solo cluster and enters debounce |
| `06-correlation/enriched-shared-ip-b.json` | Joins A's cluster through exact `source.ip` and MITRE overlap |
| `06-correlation/enriched-no-overlap.json` | Creates a separate solo cluster |

### Schemas — upload via Schema Registry API/dashboard

| File | Expected outcome |
|---|---|
| `schemas/schema-valid-endpoint-malware.yaml` | accepted; link playbook on the form |
| `schemas/schema-valid-phishing-no-playbook.yaml` | accepted; no playbook link (fallback demo) |
| `schemas/schema-invalid-empty-mapping.yaml` | rejected — `field_mapping must not be empty` |
| `schemas/schema-invalid-duplicate-source.yaml` | rejected — same source path mapped to two ECS fields |
| `schemas/schema-invalid-bad-version.yaml` | rejected — version must be full semver |
| `schemas/schema-invalid-syntax.yaml` | rejected — YAML parser error |
| `schemas/schema-invalid-critical-not-mapped.yaml` | **accepted at upload**, but every alert of the type dies at validation with `MISSING_REQUIRED_FIELD` — upload-vs-runtime gap demo |

### Playbooks — upload via `POST /api/v1/tenants/{id}/playbooks` (multipart, YAML only)

| File | Expected outcome |
|---|---|
| `playbooks/playbook-valid-minimal.yaml` | accepted (prompt + description + flags) |
| `playbooks/playbook-valid-full.yaml` | accepted (alert_types + one action) |
| `playbooks/playbook-invalid-missing-prompt.yaml` | rejected — `prompt` required |
| `playbooks/playbook-invalid-unknown-field.yaml` | rejected — unknown keys forbidden (`promt`, `steps`) |
| `playbooks/playbook-invalid-unknown-adapter.yaml` | rejected — adapter not a platform-defined identifier |
| `playbooks/playbook-invalid-syntax.yaml` | rejected — YAML parser error |

Renaming any playbook file to `.txt` (or uploading non-UTF-8 content) demonstrates the file-level rejections.

## End-to-end happy path

```bash
curl -s -X POST http://localhost:8001/api/v1/alerts/ingest \
  -H 'Content-Type: application/json' \
  -d @01-ingestion/alert-valid.json | jq
# then watch:
docker exec -it socmind_kafka /opt/kafka/bin/kafka-console-consumer.sh \
  --bootstrap-server kafka:9092 --topic enriched --from-beginning
```

Send the same body twice within 60 minutes to also see `DUPLICATED_ALERT` on `dead_letter_queue`. To generate a *new* distinct alert instead, change any hash-relevant field (e.g. `result.src`).
