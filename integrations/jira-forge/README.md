# TierX Jira Forge app

Customers configure their own public HTTPS TierX server in Jira; no rebuild or
customer app registration is needed. Publishers use their existing Forge app ID
when deploying. The checked-in ID is a placeholder for independent publishers.
Never commit installation credentials.

This Forge app adds **Send to TierX** to every Jira issue. The issue
acts as a human-facing transport for one raw source alert. A click extracts the
JSON from the description or a text/JSON attachment. TierX selects the
tenant, source system, and alert type from the configured Jira project route,
then comments the acknowledgement and final result on the same Jira issue.

## Raw alert contract

Provide exactly one JSON object in either a description code block or one UTF-8
`.json`/`.txt` attachment. For a Splunk route, paste the Splunk result object as
received. For example:

```json
{
  "result": {
    "host": "JIRA-TEST-ENDPOINT-01",
    "rule_name": "Endpoint Malware Execution",
    "_time": "2026-08-19T08:15:04Z"
  }
}
```

Do not add a TierX wrapper. In particular, do not include `tenant_id`,
`source_system`, `alert_type`, `timestamp`, and `raw_payload` around the source
object. The route is authoritative for those values, and the active schema's
`event.created` mapping is authoritative for the source timestamp. Jira issue
creation time is never substituted.

## Safety boundaries

- Each installation uses administrator-approved customer-managed backend egress.
  There is no fixed server, public relay, or static wildcard permission.
- HTTPS port 443 origins only: no paths, URL credentials, query strings,
  fragments, redirects, or private/reserved DNS answers. DNS is checked before
  each request; Forge's outbound enforcement remains the final connection layer.
- DNS checks use Cloudflare's DNS-over-HTTPS resolver through Forge's HTTPS
  proxy, with a five-second deadline and fail-closed A/AAAA validation. Only the
  server hostname is disclosed to that resolver, never credentials or alerts.
  Its fixed egress permission is separate from administrator-approved TierX
  destination access. A preflight DNS check does not pin Forge's subsequent
  connection IP; do not claim it eliminates DNS-rebinding races.
- TierX HTTP requests have a 20-second total deadline. Scheduled result polling
  visits ten pending submissions per page with at most five concurrent workers,
  retaining the cursor for subsequent five-minute invocations.
- The integration credential is stored with Forge `kvs.setSecret`.
- Exactly one JSON object is accepted from the description or one UTF-8
  `.json`/`.txt` attachment up to 1 MiB.
- Unrelated attachments, comments, children, and changelog data are not sent to
  TierX.
- The clicking user's Jira identity is used to read issue evidence. The app
  identity posts acknowledgement, result, and failure comments.
- Repeated clicks on the same Jira issue revision reuse the same TierX
  submission and comments.

## Register and deploy

Connection mutations use an installation-local encrypted exclusive claim with
`FAIL_IF_EXISTS`. The claim intentionally has no TTL: expiring a lock while a
write is still running could resurrect a disconnected connection. A process
crash during the short commit section fails subsequent changes closed. Operator
recovery must first establish that all previous mutation invocations have ended,
then remove only `tierx:connection-mutation:v1` through an authorized maintenance
invocation. Never clear an active claim or remove the connection record itself.

Run these commands from the application worktree root (the directory containing
this repository's `Makefile`):

```bash
test -f integrations/jira-forge/package.json
test -f integrations/jira-forge/manifest.yml
npm --prefix integrations/jira-forge ci
npm --prefix integrations/jira-forge run forge -- --version
npm --prefix integrations/jira-forge run forge -- login
npm --prefix integrations/jira-forge run forge -- whoami
npm --prefix integrations/jira-forge test
npm --prefix integrations/jira-forge run forge -- register
npm --prefix integrations/jira-forge run forge -- lint
npm --prefix integrations/jira-forge run forge -- deploy --environment development
npm --prefix integrations/jira-forge run forge -- install \
  --environment development \
  --site example.atlassian.net \
  --product Jira
```

Use a Forge-scoped Atlassian API token when `forge login` prompts. A Jira REST
API token is not automatically a Forge CLI credential. Registration replaces
the all-zero app ID in `manifest.yml` with the ID owned by the project's
Atlassian developer account. Review and personally accept Atlassian's developer
terms when prompted, then approve the requested Jira read, comment-write,
offline impersonation, storage, and TierX egress permissions.

Do not run `npx forge`: npm can download the unrelated package named `forge`.
The `npm run forge` commands above explicitly invoke
`npx --yes @forge/cli@13.5.0`, so the official Atlassian package and version are
unambiguous. The CLI is intentionally not installed by ordinary `npm ci`
because it is a release-operator tool rather than an application dependency.
Its upstream dependency audit must be reviewed before each Forge deployment;
run it only against this trusted repository and never against unreviewed input.

The Forge app is intentionally prepared for private/direct distribution. Do not
submit it to Marketplace without a separate privacy and security review.

## Configure

Open **TierX → Settings → Integrations → Jira** as a platform administrator.
Create a site connection using the Jira Cloud ID and site URL. The response
reveals the connection ID and secret once. Then create one project route for
each Jira project that can transport alerts. A route selects an active tenant,
one of its allowed source systems, and an active alert-type schema.

The equivalent API calls are:

```http
POST /api/v1/admin/integrations/jira
Authorization: Bearer <platform-admin-jwt>
Content-Type: application/json

{
  "name": "Samimi Jira testing",
  "jira_cloud_id": "<Atlassian cloud ID>",
  "jira_site_url": "https://example.atlassian.net"
}
```

```http
POST /api/v1/admin/integrations/jira/<connection-id>/routes
Authorization: Bearer <platform-admin-jwt>
Content-Type: application/json

{
  "project_key": "DEMO",
  "tenant_id": "00000000-0000-4000-8000-000000000001",
  "source_system": "SPLUNK",
  "alert_type": "splunk.notable.endpoint_malware",
  "enabled": true
}
```

The response shows the secret once. In Jira, open **Apps → Manage apps →
Configure TierX**, then enter:

- TierX server URL: your public HTTPS origin (for example `https://tierx.example.com`)
- Connection ID from the response
- One-time integration secret from the response

The configuration page verifies that the credential is bound to the current
Jira cloud ID before saving it. Routing remains exclusively in TierX; Forge
cannot choose or override the tenant, source system, or alert type.

**Test and save** first validates the destination, asks for Atlassian outbound
consent, then verifies the credential. Rejected consent sends no credentials.
**Test connection** checks the saved connection without revealing the secret.
**Disconnect** removes the credential and stops future sends/polling; it does
not delete Jira comments or TierX records. A request already sent cannot be recalled.

Only Jira administrators may manage this configuration. One connection is active
per installation. Replacing its URL or ID requires a new credential and makes
old queued work ineligible. Rotating the secret for the same connection retains
pending work. Prototype configurations require fresh pairing.

Failed pairing leaves the saved connection intact. A destination approved before
a failed pairing can remain in Atlassian Connected Apps; administrators can revoke
unused destinations there. Revoked permissions fail closed on subsequent requests.

Customer-managed egress is an Atlassian Preview feature. Validate the consent UI,
async consumer, and scheduled polling in a development installation before
production release. This app is not eligible for the Runs on Atlassian badge.
Public DNS and trusted TLS must be reachable from Forge; VPN-only hosts are not
supported. Forge's DNS/connection enforcement must be verified before claiming
protection against DNS rebinding; application DNS prechecks alone do not pin the
connection address.

The connector sends only `X-TierX-Integration-ID`; legacy Jira headers and
prototype pairing are intentionally unsupported. Polling diagnostics retain
only fixed error categories and HTTP status codes, not upstream response bodies,
credentials, or arbitrary exception messages.

The app identity must have **Browse Projects** and **Add Comments** in each Jira
project where acknowledgement or result comments are expected. A missing
comment permission does not resend or duplicate the TierX alert.

## Processing behavior

The async consumer extracts the raw alert, queues it, reserves an alert UUID,
posts the acknowledgement, and finalizes ingestion. The operator can close the
dialog immediately. A
five-minute scheduled trigger follows pending submissions:

- `ANALYZED`: post the persisted TierX summary and recommendations.
- `FAILED`: post a sanitized stage and error report.
- `PROCESSING` or `CLUSTERED`: leave pending without a timeout comment.

Unknown or disabled Jira projects, invalid JSON, old wrapper payloads, missing
schema timestamp fields, and route configuration drift produce a sanitized Jira
error comment. When LLM analysis is disabled, valid issues normally remain
pending at `CLUSTERED`. When it is enabled, the existing Ollama analysis worker
can produce the final result without changes to this Forge app.
