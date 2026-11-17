# TierX compatibility contracts

TierX uses `TIERX_*` environment variables, `X-TierX-*` HTTP headers,
`tierx_*` browser keys, `tierx_kb`, and `TIERX_ANALYSIS_DEFAULT`.

Compatibility is permanent for existing installations:

- Environment resolution is canonical `TIERX_*`, then the existing unprefixed
  name, then `SOC_MIND_*`.
  Compose resolves these names before startup, including required credentials.
  Empty Compose values fall through to the next name or default. Frontend API
  URLs additionally support an explicitly empty value for same-origin requests.
- Inbound signed/private endpoints accept `X-TierX-*` or `X-SOC-Mind-*` and
  reject a request if both carry different values.
- Outbound signed calls emit both header families with identical values.
- Browser state is read and mirrored between canonical and legacy keys.
  If both differ, the legacy value wins so changes made during rollback survive.
- `soc_mind_kb` re-exports `tierx_kb`.
- New encrypted credentials record AAD namespace `tierx`; records without this
  metadata use the legacy AAD namespace.
- The active legacy prompt is copied idempotently into
  `TIERX_ANALYSIS_DEFAULT`; historical provenance is not rewritten.

Repository paths, GHCR image names, databases, Docker identities, the Jira
Forge app/module/queue/storage keys, and other physical deployment identifiers
remain stable by design.

## Locating retained identifiers

These are compatibility identifiers, not the current product name:

| Area | Source locations | Why retained |
| --- | --- | --- |
| Environment aliases and signed headers | `kb_shared/tierx_runtime/`, `backend/app/core/brand_compat.py`, `ingestion-proxy/app/core/brand_compat.py`, `compose.yaml` | Existing configuration and webhook providers must continue working. |
| Platform and tenant databases | `backend/app/db/mongodb.py`, `backend/app/services/tenant_service.py`, workflow storage and semantic retrieval | Renaming requires a coordinated data migration; a text replacement would select different databases. |
| Browser storage | `frontend/src/lib/storage.ts` | Existing sessions and rollback state are migrated/mirrored. |
| Encrypted credentials and delivery identities | Webhook/enrichment services in `backend/app/services/` and `pipeline/app/services/` | Changing AAD can prevent decryption; changing identity inputs can duplicate deliveries. |
| Jira integration | `integrations/jira-forge/manifest.yml`, queue, poller and connection store | Installed module, queue and storage identities must remain stable. |
| Python import and prompt aliases | `kb_shared/soc_mind_kb/`, analysis services/workers | Existing imports and stored prompt provenance remain readable. |
| Docker container identities | `compose.yaml` | Existing deployment automation may address these names. Prefer `docker compose exec`, `logs` and `restart` with service names in new instructions. |

Use TierX for product text, checkout examples and new public identifiers.
`python3 tools/check_branding.py` rejects active old branding, including the old
abbreviation and checkout name, while permitting the compatibility contracts
above. Removing a compatibility identifier requires its own migration design and
rollback verification; do not rename persisted keys or cryptographic inputs as a
cosmetic cleanup.
