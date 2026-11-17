# TierX clean-start identifier contract

This release is a **breaking, clean-start release**. It does not read, migrate or
mirror predecessor identifiers. Do not deploy it over an existing installation
expecting its databases, credentials, browser sessions or Forge queues to work.

## Canonical identifiers

- Platform database: `tierx_platform`.
- New tenant databases: `tierx_tenant_{slug}`.
- Docker container names: `tierx_*`; use Compose service names in automation.
- Environment resolution: `TIERX_*`, then the existing unprefixed setting.
- Signed HTTP headers: `X-TierX-*` only.
- Browser state: `tierx_token`, `tierx_selected_tenant`,
  `tierx_onboarding_seen`; no mirroring or migration.
- Python Knowledge Base package: `tierx_kb` only.
- Default prompt identity: `TIERX_ANALYSIS_DEFAULT`, bootstrapped independently.
- Encryption AAD and deterministic delivery namespaces: `tierx`.
- Jira module, queue and storage identifiers: `tierx-*` / `tierx:*`.

## Operational boundary

Use a new installation with TierX databases, fresh entry/signing credentials and
fresh Jira configuration. Existing encrypted records and delivery identities are
not converted, and browser users must sign in again. Existing Docker volumes are
not deleted or renamed by this change. Changing container names does not make
reusing an existing volume a clean installation: select a new Compose project and
new persistent volumes explicitly.

No database deletion, server reset, secret rotation, Forge reinstallation or data
migration is automated by this source change. Those are separate operator actions.
Rollback is to the previous release together with its original configuration and
data; do not point the previous release at a new installation's state.
