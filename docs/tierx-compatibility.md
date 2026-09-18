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
