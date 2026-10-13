# Installation and platform configuration

MongoDB, Kafka, internal addresses, JWT signing, and integration encryption keys
are always environment-managed. Only product settings live in the platform database.
See [image-based examples](../examples/usage/README.md) for deployment commands.

## First installation

- `TIERX_INSTALLATION_ENABLED` defaults to `true`. Setting it to `false` disables
  setup writes; it does not mark an empty database installed.
- `TIERX_INSTALLATION_TOKEN` optionally supplies an operator token. Otherwise a
  random token is logged once on first startup; only its SHA-256 hash is stored.
  If lost, provide a replacement token and restart backend before completion.
- `TIERX_BOOTSTRAP_CONFIGURED=true` requires administrator email/password,
  public URL, Ollama URL, and model from environment. Invalid/missing values fail
  startup. Supplying both legacy administrator variables also retains existing
  automated-bootstrap behavior.
- Existing platform administrators mark a database installed without changing
  their identity or password. Completed setup cannot be reopened by flags.
- Until completion, normal APIs and ingestion return `503 INSTALLATION_REQUIRED`.
  Health and installation endpoints remain available; processing services wait.

`GET /api/v1/installation/status` returns `installed` and `wizard_available`.
Incomplete enabled installations additionally return non-secret defaults and
locked fields. `POST /api/v1/installation/test` accepts product values and tests
Ollama model availability plus real structured inference. `POST
/api/v1/installation/complete` accepts `{email,password,values}`. Both writes
require `X-TierX-Installation-Token`. Tokens are never query parameters or browser
storage. The password is at least 12 characters and at most 72 UTF-8 bytes.

Completion reserves one durable administrator identity atomically, then creates
the user and completes the installation. Restart recovers interrupted completion
using the reserved identity/hash. Parallel submissions cannot reserve a second
administrator. A successful completion consumes the token.

## Product values

```json
{
  "public_url": "https://tierx.example.com",
  "ollama_url": "http://ollama:11434",
  "ollama_model": "phi3:latest",
  "llm_analysis_enabled": false,
  "correlation_enabled": false,
  "knowledge_base_processing_enabled": false,
  "knowledge_base_retrieval_enabled": false
}
```

Public URLs require HTTPS except localhost HTTP. Ollama may use HTTP or HTTPS.
Both are origins without embedded credentials, paths, queries, or fragments.
Ollama tests reject redirects and require the exact selected model; they never
download or substitute models. Analysis enabling performs a successful inference
preflight and enables correlation in the same update. Correlation cannot be
disabled while analysis remains enabled.

## Authenticated settings

Platform administrators use `/dashboard/admin/settings/platform` and:

- `GET /api/v1/admin/settings/platform`: effective values, locked fields, saved
  revision, service applied revisions/timestamps/errors, environment-managed fields.
- `PUT /api/v1/admin/settings/platform`: `{expected_revision,values}`. A stale
  revision returns `409`; invalid settings/model preflight return `422`.
- `POST /api/v1/admin/settings/platform/test`: validate Ollama without saving.

Canonical `TIERX_*` overrides take precedence. Empty values mean no override.
Override fields are read-only, and saved shadow values remain intact so removing
an override restores the administrator's saved value. Legacy unprefixed and
`SOC_MIND_*` values are still accepted for existing installations.

Settings record revision, UTC update time, and administrator audit identity.
Backend, pipeline, ingestion, and document processor check every five seconds.
Core consumers retain per-message configuration snapshots. Analysis jobs persist
their captured revision/values for retries. Disabling an optional worker drains
active work and stops new claims; durable pending analysis remains queued.
Refresh failures retain the last valid configuration and expose a safe error.
Heartbeat freshness must be checked alongside revision; a stopped service is not
treated as applied merely because its last recorded revision matches.

No schema migration, TLS provisioning, arbitrary internal wiring editor, or model
download is performed by these APIs. Do not delete installation state to reset
administrators; use normal authenticated user management.
