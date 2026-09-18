# TierX — Developer Onboarding Guide

This guide takes a developer who has **never seen this project** from zero to a running
stack, and walks through the four core day-to-day operations:

1. [Run the stack](#3-run-the-stack)
2. [Test it](#7-testing)
3. [Add a user](#5-add-a-user)
4. [Add a tenant](#4-add-a-tenant)
5. [Ingest an alert](#6-ingest-an-alert)

> If you only read one thing: run `make up`, wait ~30s, open http://localhost:3000,
> and log in with the local administrator values in your `.env` file.

---

## 1. What this project is

TierX is a multi-tenant security-alert processing platform. Alerts are ingested,
validated, normalized, enriched, and stored per-tenant. It runs as a set of Docker
containers orchestrated by Docker Compose.

### Architecture at a glance

```
                         ┌─────────────┐
  Browser ──:3000──────▶ │  frontend   │  Next.js UI
                         └──────┬──────┘
                                │ calls :8000
                         ┌──────▼──────┐
  Admin / API ──:8000──▶ │  backend    │  FastAPI: auth, users, tenants, playbooks
                         └──────┬──────┘
                                │ reads/writes
                         ┌──────▼──────┐      ┌──────────┐
                         │  mongodb    │◀────▶│ pipeline │  Kafka consumers (workers)
                         └──────▲──────┘      └────▲─────┘
                                │                  │ consumes
  Alert source ──:8001──▶ ┌─────┴───────┐    ┌─────┴─────┐
                          │ ingestion-  │───▶│   kafka   │
                          │   proxy     │    └───────────┘
                          └─────────────┘
                                                ┌──────────┐
                          backend + pipeline ──▶│  ollama  │  local LLM
                                                └──────────┘
```

### Services & ports (dev mode)

| Service           | Container                 | Host port | Purpose                                              |
| ----------------- | ------------------------- | --------- | ---------------------------------------------------- |
| frontend          | `socmind_frontend`        | **3000**  | Next.js web UI                                       |
| backend           | `socmind_backend`         | **8000**  | FastAPI: auth, user & tenant admin, playbooks        |
| ingestion-proxy   | `socmind_ingestion_proxy` | **8001**  | Receives alerts, validates, publishes to Kafka       |
| mongodb           | `socmind_mongodb`         | **27017** | Persistence (platform DB + per-tenant DBs)           |
| kafka             | `socmind_kafka`           | **9092**  | Message bus between proxy and pipeline               |
| ollama            | `socmind_ollama`          | **11434** | Local LLM serving                                    |
| pipeline          | `socmind_pipeline`        | —         | Background Kafka workers (no host port)              |
| init              | `socmind_init`            | —         | One-off job: pulls the Ollama model on first startup |

> **Note:** ports above are published only in **dev mode** (`make up`). In production
> mode (`make up-prod`) only the frontend (3000) is exposed; the backend and proxy stay
> internal to the Docker network.

---

## 2. Prerequisites

Install on your machine:

- **Docker** (Docker Desktop on macOS/Windows) — running
- **Docker Compose v2** — available as `docker compose` (note: space, not hyphen)
- **`make`** — preinstalled on macOS/Linux
- ~10 GB free disk + several GB RAM (Ollama models are large)

You do **not** need Node, Python, or any language toolchain installed locally — everything
runs inside containers.

Verify Docker is up:

```bash
docker version        # should print Client AND Server sections
docker compose version
```

---

## 3. Run the stack

```bash
# 1. Clone and enter the repo
cd SOC-Mind-main

# 2. Create your environment file (defaults are fine for local dev)
cp .env.example .env

# 3. Start everything in development mode
make up
```

The **first** run is slow: the `init` container downloads the Ollama model (`phi3` by
default). Subsequent runs are fast.

### Verify it's healthy

```bash
make status                                   # all services should be "Up (healthy)"
curl http://localhost:8000/api/v1/health      # backend -> {"status":"HEALTHY",...}
curl http://localhost:8001/api/v1/health      # ingestion-proxy -> {"status":"healthy",...}
open http://localhost:3000                     # frontend UI
```

### Log in

A **platform admin is auto-created** on first backend startup:

```
email:    local-admin@example.com
password: local-admin-password-change-me
```

Use it to log in at http://localhost:3000, or to get an API token (below).

> These values come from `.env.example` and are for loopback-only development.
> Set generated secrets for any shared environment.

### Interactive API docs (Swagger)

- Backend: **http://localhost:8000/docs**
- Ingestion proxy: **http://localhost:8001/docs**

You can do everything below (create users, tenants, ingest alerts) by clicking through
those pages instead of using `curl`.

### Everyday commands (`make`)

| Command            | What it does                                                      |
| ------------------ | ---------------------------------------------------------------- |
| `make up`          | Start the dev stack (**use this for development**)               |
| `make up-prod`     | Start with production overrides (backend/proxy NOT exposed)      |
| `make down`        | Stop the stack (keeps data)                                      |
| `make restart`     | Restart the dev stack                                            |
| `make logs`        | Follow logs from all services                                    |
| `make build`       | Rebuild local images                                             |
| `make status`      | Show container + health status                                   |
| `make setup-topics`| Create the Kafka topics used by the pipeline (run once)          |
| `make test`        | Run backend (pytest) + frontend tests                           |
| `make clean`       | Stop the stack **and delete all volumes** (wipes the database!)  |

> ⚠️ Always develop with **`make up`**, not `make up-prod`. In prod mode the backend port
> (8000) is not published to your machine, so the frontend's browser calls fail with
> **"Failed to fetch"** on login.

---

## 4. Add a tenant

Tenants are the top-level isolation boundary. You must create a tenant **before** you can
add tenant-scoped users or ingest alerts for it. All tenant admin endpoints require a
**platform admin** token.

### Step 1 — Get an admin token

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"local-admin@example.com","password":"local-admin-password-change-me"}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')

echo "$TOKEN"   # sanity check — should be a long JWT string
```

### Step 2 — Create the tenant

```bash
curl -s -X POST http://localhost:8000/api/v1/admin/tenants \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
        "name": "acme",
        "display_name": "Acme Corp",
        "contact_email": "soc@example.com",
        "allowed_source_systems": ["SPLUNK"]
      }'
```

Field notes:

- `name` — unique, URL-friendly slug (required).
- `display_name` — human-readable name (required).
- `allowed_source_systems` — which alert sources this tenant may send. **Case-insensitive.**
  If left **empty (`[]`), ALL sources are allowed.**
- The response includes a generated `tenant_id` (a **UUID**). **Save it** — you need it for
  users and alerts.

### Step 3 — Activate the tenant ⚠️ required

New tenants start in **`ONBOARDING`** status. Alerts are only accepted for **`ACTIVE`**
tenants, so you must flip the status:

```bash
TENANT_ID="<paste the tenant_id UUID from step 2>"

curl -s -X PATCH http://localhost:8000/api/v1/admin/tenants/$TENANT_ID/status \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"status":"ACTIVE"}'
```

Valid statuses: `ONBOARDING`, `ACTIVE`, `SUSPENDED`, `DELETED`.

### Useful tenant queries

```bash
# List all tenants
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/admin/tenants

# Get one tenant
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/admin/tenants/$TENANT_ID
```

---

## 5. Add a user

There are **three roles**:

| Role              | Scope             | Can be created by                              |
| ----------------- | ----------------- | --------------------------------------------- |
| `PLATFORM_ADMIN`  | Global, no tenant | Another `PLATFORM_ADMIN` only                 |
| `TENANT_ADMIN`    | One tenant        | `PLATFORM_ADMIN`                              |
| `TENANT_OPERATOR` | One tenant        | `PLATFORM_ADMIN` or that tenant's `TENANT_ADMIN` |

Rules enforced by the API:

- Non-admin roles **require** a `tenant_id`, and that tenant must exist.
- `PLATFORM_ADMIN` must **not** have a `tenant_id`.
- Passwords must be **≥ 8 characters**.
- Email must be unique.

### Option A — Platform-admin endpoint (can create any role)

```bash
# A tenant operator (needs an existing tenant_id)
curl -s -X POST http://localhost:8000/api/v1/admin/users \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
        "email": "operator@example.com",
        "password": "changeme123",
        "role": "TENANT_OPERATOR",
        "tenant_id": "'"$TENANT_ID"'"
      }'

# Another platform admin (NO tenant_id)
curl -s -X POST http://localhost:8000/api/v1/admin/users \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin2@example.com","password":"changeme123","role":"PLATFORM_ADMIN"}'
```

### Option B — Tenant-scoped endpoint

A `TENANT_ADMIN` (or platform admin) can create users within a specific tenant. The
`tenant_id` comes from the URL. A `TENANT_ADMIN` may only create `TENANT_OPERATOR`s.

```bash
curl -s -X POST http://localhost:8000/api/v1/tenants/$TENANT_ID/users \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"email":"operator2@example.com","password":"changeme123","role":"TENANT_OPERATOR"}'
```

### Verify / log in as the new user

```bash
# List users
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/admin/users

# Log in as the new user
curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"operator@example.com","password":"changeme123"}'
```

---

## 6. Ingest an alert

Alerts go to the **ingestion-proxy on port 8001**, NOT the backend. The proxy validates
the alert, then publishes it to Kafka, where the pipeline workers process it into MongoDB.
**No auth token is needed** to ingest.

```
POST :8001/api/v1/alerts/ingest  →  validate  →  Kafka "received"  →  pipeline  →  MongoDB
```

### One-time setup: create Kafka topics

```bash
make setup-topics
```

### Required request body

All five fields are required:

```json
{
  "tenant_id": "<UUID of an ACTIVE tenant>",
  "source_system": "SPLUNK",
  "alert_type": "splunk.notable.endpoint_malware",
  "timestamp": "2026-03-19T14:23:17.000Z",
  "raw_payload": { "...": "the raw alert from the source system" }
}
```

### Ingest from a file

A sample is provided at [`test-samples/valid_alert.json`](../test-samples/valid_alert.json).
Edit its `tenant_id` to your ACTIVE tenant's UUID first, then:

```bash
# ⚠️ Run from the repo root OR use an absolute path (see gotcha #1 below)
cd /path/to/SOC-Mind-main

curl -s -X POST http://localhost:8001/api/v1/alerts/ingest \
  -H 'Content-Type: application/json' \
  --data @test-samples/valid_alert.json
```

**Success** returns HTTP 200:

```json
{"alert_id":"...","status":"RECEIVED","kafka_state":"RECEIVED", ...}
```

### Verify the alert landed

```bash
# Watch the pipeline process it
docker logs -f socmind_pipeline

# Query stored alerts for the tenant (needs admin token)
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/admin/tenants/$TENANT_ID/alerts
```

### ⚠️ Ingestion gotchas (read these — they cause most failures)

1. **`Internal Server Error` (HTTP 500) = empty request body.** Almost always `curl`
   couldn't find your `--data @file` (wrong working directory or path), so it sent
   nothing. Fix: run from the repo root, or use an **absolute path**:
   `--data @/full/path/to/test-samples/valid_alert.json`.

2. **`UNKNOWN_TENANT` (HTTP 422).** The `tenant_id` in your alert doesn't match an
   **ACTIVE** tenant. Remember `tenant_id` is the **UUID** from tenant creation, not the
   slug. The sample file's `"test-tenant"` will not match unless such a tenant exists.

3. **`UNKNOWN_SOURCE` (HTTP 422).** The `source_system` isn't in the tenant's
   `allowed_source_systems`. Either add it to the tenant, or leave the tenant's allowed
   list empty (which permits all sources).

4. **Tenant cache lag.** The proxy caches active tenants in memory and refreshes on
   startup + every hour. After creating or activating a tenant, restart the proxy so it
   sees the change immediately:

   ```bash
   docker restart socmind_ingestion_proxy && sleep 5
   ```

5. **Dead-lettered alerts.** Validation failures are pushed to a dead-letter queue, not
   silently dropped. Inspect them:

   ```bash
   curl -s -H "Authorization: Bearer $TOKEN" \
     http://localhost:8000/api/v1/admin/tenants/$TENANT_ID/dead-letters
   ```

### End-to-end happy path (copy-paste)

```bash
cd /path/to/SOC-Mind-main

# 1. token
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"local-admin@example.com","password":"local-admin-password-change-me"}' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')

# 2. tenant (allow SPLUNK) -> capture UUID
TENANT_ID=$(curl -s -X POST http://localhost:8000/api/v1/admin/tenants \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"acme","display_name":"Acme Corp","allowed_source_systems":["SPLUNK"]}' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["tenant_id"])')

# 3. activate
curl -s -X PATCH http://localhost:8000/api/v1/admin/tenants/$TENANT_ID/status \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"status":"ACTIVE"}' >/dev/null

# 4. let the proxy see it
make setup-topics
docker restart socmind_ingestion_proxy && sleep 5

# 5. ingest
curl -s -X POST http://localhost:8001/api/v1/alerts/ingest \
  -H 'Content-Type: application/json' \
  -d '{"tenant_id":"'"$TENANT_ID"'","source_system":"SPLUNK",
       "alert_type":"splunk.notable.endpoint_malware",
       "timestamp":"2026-03-19T14:23:17.000Z",
       "raw_payload":{"host":"WS-FRA-0847","severity":"critical"}}'

# 6. verify
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/admin/tenants/$TENANT_ID/alerts
```

---

## 7. Testing

```bash
make test          # runs backend pytest + frontend tests inside the containers
```

Run just the backend test suite:

```bash
docker compose -f compose.yaml -f compose.override.yaml exec backend \
  bash -c "PYTHONPATH=/app pytest tests/ -v"
```

Backend tests live in [`backend/tests/`](../backend/tests/):
`test_users.py`, `test_tenants.py`, `test_playbooks.py`, `test_schema_registry.py`.

---

## 8. Resetting / cleaning up

```bash
make down     # stop the stack, keep all data
make clean CONFIRM=destroy  # stop the stack AND delete all volumes
```

After `make clean`, the next `make up` starts from a blank database and re-seeds the
default platform admin.

---

## 9. Troubleshooting quick reference

| Symptom                                   | Cause / Fix                                                                 |
| ----------------------------------------- | -------------------------------------------------------------------------- |
| Login UI shows **"Failed to fetch"**      | You're in prod mode. Use `make up`. Backend port 8000 isn't exposed in prod. |
| Frontend logs: **`sh: next: not found`**  | Stale image. See "Frontend dev fix" in section 10. Rebuild + recreate.       |
| Ingest returns **500 Internal Server Error** | Empty body — `curl --data @file` couldn't read the file. Use absolute path. |
| Ingest returns **422 UNKNOWN_TENANT**     | `tenant_id` not an ACTIVE tenant; restart proxy after activating.            |
| Ingest returns **422 UNKNOWN_SOURCE**     | `source_system` not in tenant's allowed list.                               |
| Containers stuck **unhealthy**            | `make logs` to inspect; ensure Docker has enough RAM/disk.                   |
| First `make up` very slow                 | Ollama is downloading the model. Wait it out.                               |
| Port already in use (3000/8000/...)       | Stop the conflicting process or edit ports in `compose.override.yaml`.       |

---

## 10. Frontend dev fix (for maintainers)

The frontend's final image is production-only (it ships a Next.js *standalone* server
with no `next` CLI). Dev mode runs `npm run dev`, so it builds the Dockerfile's
`development` stage with full, Linux-native `node_modules`.
This is configured in `compose.override.yaml`. If you ever see `sh: next: not found`:

```bash
docker compose -f compose.yaml -f compose.override.yaml build frontend
docker compose -f compose.yaml -f compose.override.yaml up -d \
  --force-recreate --renew-anon-volumes frontend
```

The `--renew-anon-volumes` flag is important: it repopulates the `/app/node_modules`
volume from the freshly built image.
