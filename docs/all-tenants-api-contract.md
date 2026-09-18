# Listing search & all-tenants listings — API contract

The sidebar tenant picker has an **All tenants** scope. With it selected, every
section shows records from all tenants and its search box searches across them.

The frontend for this is merged and calls the endpoints below.

> **Status update — these are implemented.** All four routes landed in
> `feat: implement all-tenant listing APIs (#20)` (`3a3c739`) and are mounted at
> `/api/v1/admin` in `backend/main.py:131`; see
> `backend/app/api/v1/admin/platform_lists.py`. Every parameter this document
> marked "reserved" is honoured, including `status` on clusters and `is_active`
> on schemas and playbooks. The error text below is now a fallback, not the
> expected state. The rest of the document stands as the contract the
> implementation is measured against — and one thing it does **not** cover is
> still missing, see *Alert filters* below.

## Why the server has to do this

Fanning out from the browser — list tenants, then query each one — was tried and
rejected. It costs one request per tenant per keystroke, cannot page or sort a
merged result correctly, and it trips the `switch_db` bug below. Searching,
filtering, sorting and paging all belong in one query.

## Endpoints

| Section        | Endpoint                             |
| -------------- | ------------------------------------ |
| Alerts         | `GET /api/v1/admin/alerts`            |
| Clusters       | `GET /api/v1/admin/clusters`          |
| Schema Registry| `GET /api/v1/admin/alert-type-schemas`|
| Playbooks      | `GET /api/v1/admin/playbooks`         |

### Query parameters

| Param         | Sections            | Notes                                            |
| ------------- | ------------------- | ------------------------------------------------ |
| `q`           | all                 | Free text. Omitted when the search box is empty. |
| `skip`,`limit`| all                 | Standard paging; the client sends 10/25/50.      |
| `since_hours` | alerts              | Period filter. Served.                           |
| `status`      | clusters            | Status filter. Served.                           |
| `is_active`   | schemas, playbooks  | Served; **not sent while searching**.            |

**No other filter exists on any of these routes.** For alerts specifically that
is a gap the design needs closed — see *Alert filters* below.

Every served filter is now wired in the UI: `since_hours` on all-tenants alerts,
`status` on all-tenants clusters, `is_active` on all-tenants schemas and
playbooks. Clusters, Schema Registry and Playbooks render the **same view in
both scopes** — one component per section, taking `tenantId` or `null` — so the
all-tenants scope is the per-tenant screen sourced from the platform endpoint,
not a separate table. Note how rule 1 is implemented server-side — `list_clusters` applies
`status` only `if cluster_status and not search`, and `list_schemas` /
`list_playbooks` do the same with `is_active`, so a search really does cover
every status. The client therefore disables those controls while a term is
applied rather than sending a parameter the server will drop.

**Missing for playbooks: platform totals.** The per-tenant Playbook screen shows
three KPI cards (active playbooks, alert types covered, system playbooks)
counted from the rows it holds. Across tenants the list is paged, so the same
count would be per-page while reading as a platform total — the cards are
therefore omitted in that scope. A `GET /admin/playbooks/stats` (or the counts
on the list response) would let them come back.

**Missing for clusters: a time filter.** The per-tenant route takes
`created_after`/`created_before`; `GET /api/v1/admin/clusters` takes neither, so
the Period control in the all-tenants cluster view is rendered disabled. Adding
`created_after` (or `since_hours`, to match alerts) is all that is needed — the
client already has the control and the wiring.

Two rules the frontend depends on:

1. **Search is never narrowed by status.** A draft schema, an inactive playbook
   or a closed cluster must still be findable by `q`.
2. **Scope comes from the token, not a parameter.** These routes are
   platform-admin only. Tenant users never reach them — they stay on the
   existing per-tenant endpoints.

### Response

```jsonc
{
  "items": [ /* the section's normal item shape, plus the two fields below */ ],
  "total": 128,   // matches across all tenants, for paging
  "skip": 0,
  "limit": 25
}
```

Every item must carry its owner:

```jsonc
{
  "alert_id": "cccccccc-…",
  "alert_type": "splunk.notable.endpoint_malware",
  "tenant_id": "example-tenant-id",       // required — the client routes on it
  "tenant_name": "Demo Tenant"     // resolved server-side, shown in the Tenant column
}
```

Otherwise the item shapes are the ones the per-tenant endpoints already return
(`AlertDocument`, `ClusterListItem`, `AlertTypeSchemaDocument`,
`PlaybookListItem`), so no client-side mapping is needed.

**Gap to close:** `ClusterListItem` has no `tenant_id` today. It must be added
for clusters — without it a row cannot be linked back to its tenant.

### What `q` should match

| Section  | Match on                                                   |
| -------- | ---------------------------------------------------------- |
| Alerts   | `alert_id`, `alert_type`, `source_system`, `fingerprint`   |
| Clusters | `cluster_id`, analysis headline/narrative, MITRE technique |
| Schemas  | `alert_type`, `schema_id`                                  |
| Playbooks| `playbook_name`, `alert_types`, `playbook_id`              |

Exact-id matches should rank first — pasting an id is the common case.

### Errors

| Status  | Client behaviour                                              |
| ------- | ------------------------------------------------------------- |
| 404/501 | "…platform-wide endpoint may not be available yet."           |
| 403     | Same message; these routes are admin-only by design.          |
| 401     | Existing global handling — token cleared, redirect to login.  |

## Per-tenant search (`q` on existing endpoints)

The single-tenant Alerts and Clusters pages now have search boxes. They send an
optional `q` to endpoints that already exist:

| Page     | Endpoint                                                       | Param added |
| -------- | -------------------------------------------------------------- | ----------- |
| Alerts   | `GET /api/v1/admin/tenants/{tenant_id}/alerts` (admins)          | `q`         |
| Alerts   | `GET /api/v1/tenants/{tenant_id}/alerts` (tenant users)          | `q`         |
| Clusters | `GET /api/v1/tenants/{tenant_id}/clusters`                       | `q`         |

Schema Registry and Playbooks already had per-tenant search; schemas use `q`
server-side today, playbooks still filter in the browser and would benefit from
the same param.

**This was the one place the frontend failed quietly** — FastAPI ignores unknown
query params, so an unread `q` returned the *unfiltered* list rather than an
error and the box looked like it did nothing. **Resolved:** `q` is honoured on
all three alert routes and on clusters (`tenant_info.py:60-71`,
`admin/tenants.py:95-110`, `clusters.py:28-36`). Per-tenant playbooks still have
no `q` and still filter in the browser.

Matching should follow the same rules as the platform-wide search: exact ids
first, and **never narrowed by status** — the clusters page already drops its
status filter while a term is present, and expects the server to do the same.

Suggested fields:

| Endpoint | Match on                                                     |
| -------- | ------------------------------------------------------------ |
| Alerts   | `alert_id`, `alert_type`, `source_system`, `fingerprint`     |
| Clusters | `cluster_id`, analysis headline/narrative, MITRE technique   |

The frontend keeps `q` in the URL (`?q=…`), so a filtered view stays shareable.

## Alert filters — missing in both scopes

Verified against the server: every alert list route accepts `skip`, `limit`,
`since_hours`, `q` and nothing else — the all-tenants
`GET /api/v1/admin/alerts` (`admin/platform_lists.py:20-31`) exactly as much as
the two per-tenant ones (`tenant_info.py:60-71`, `admin/tenants.py:95-110`).
Of the designed filter bar, only **Zeitraum's preset ranges** can be built —
`since_hours` is served in both scopes and the all-tenants alerts view now sends
it. **Status, Schweregrad and the custom date range have nothing to send in
either scope**, and the all-tenants view additionally has no way to narrow to a
subset of tenants.

Clusters are the counter-example and the shape to copy: the per-tenant route
already takes `status`, `assigned_to`, `is_open_for_grouping`,
`created_after`/`created_before` (`clusters.py:28-36`), and the platform route
carries `status` across tenants. Alerts are the section left behind.

**The full specification lives in §2.2.2 of `docs/backend-gaps-report.md`** —
which params, which are blocked (`severity` on §1.5, `status` on the §1.7
vocabulary question), which two can ship immediately (`alert_type`,
`source_system`), why `severity` needs `$getField` rather than a dotted path, and
why the frontend is not shipping this ahead of the server the way it did `q`.
Recorded here so that anyone implementing the all-tenants routes from this
document alone does not conclude the alert endpoint is finished.

Whatever lands must obey rule 1 above: filters AND with `q`, they never narrow
it.

## Known blocker

`PlaybookService` and `AlertTypeSchemaService` scope queries with mongoengine's
`switch_db`, which mutates global model state. Concurrent requests for different
tenants already clobber each other — measured: a request for tenant A returning
tenant B's rows. A cross-tenant query that touches many tenant databases in one
request will hit this hard, so it needs fixing as part of this work.

## Also missing

Point 4 of the plan — a tenant user opening **Settings → Tenant details** — routes
to `/dashboard/<tenantId>/settings`. That page currently rejects anyone who is
not a TENANT_ADMIN, so tenant operators get an error toast. Either the page
should render read-only for operators, or the API should expose a read-only
tenant profile for them. Product decision, flagged here so it is not lost.
