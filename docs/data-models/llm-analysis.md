# LLM analysis PoC

The analysis worker consumes versioned requests from `clustered` and supports
two scopes.

An unmatched enriched alert remains clusterless:

```text
cluster_id = null
clustering_status = UNCLUSTERED
analysis_type = SINGLE_ALERT_ANALYSIS
```

It receives an immediate standalone result under `alert.alert_analysis`. If a
later alert shares an exact correlation entity within 24 hours, correlation
creates or joins a real cluster, preserves the standalone result with a
`superseded_by_cluster_id`, and requests cluster analysis.

A real cluster contains at least two correlated alerts. Its current result is
stored under `cluster.summary`; replaced successful summaries are retained
under `summary.history`.

## Durable jobs

Each tenant database has an `analysis_runs` collection uniquely keyed by:

```text
analysis_scope_type
analysis_scope_id
requested_analysis_version
```

States are `PENDING`, `RUNNING`, `SUCCEEDED`, `FAILED`, and `SUPERSEDED`.
Workers claim jobs with an expiring lease. A stale cluster version or promoted
standalone job cannot commit over the current scope.

After the initial attempt, transient or validation failures retry after 5, 10,
and 20 seconds. An exhausted run is retained as failed and produces an
`LLM_INFERENCE_FAILURE` dead-letter record. Tenant admins and platform admins
can reopen the current failed version without deleting its audit history.

## Prompt and context rules

`TIERX_ANALYSIS_DEFAULT` is the immutable-versioned platform fallback
prompt. Enrichment-resolved playbook prompts are selected by exact playbook
ID/version, deduplicated, and combined in stable order. Alert types without a
usable prompt receive the system fallback once.

Successful signed playbook-context webhook results are appended after the
stored playbook/system sections and before the output-schema instruction.
Cluster footers are ordered by playbook revision and alert ID, deduplicated by
checksum within a playbook revision, and admitted as complete sections within
a 64 KiB budget. Prompt provenance records the contributing alert IDs and
checksums but never stores the signing secret or full footer text.

Only normalized payloads and available enrichment enter evidence context. Raw
payloads, credentials, authorization headers, database URLs, and deployment
secrets are excluded. Oversized context fails with
`LLM_CONTEXT_TOO_LARGE`; there is no implicit truncation.

The validated model result contains:

- version, headline, and narrative;
- supported kill-chain stages;
- `HIGH`, `MEDIUM`, or `LOW` confidence;
- recommended actions;
- generation/model metadata;
- trigger and prompt-source metadata;
- context and effective-prompt checksums.

Model output does not change analyst verdict, assignment, escalation, or
workflow status. Automated response execution is outside this PoC.

## Interfaces

Tenant users can read alert and cluster analysis-run history. Tenant admins and
platform admins can retry failed runs. Platform admins can read the active
system prompt and create a new immutable version through the admin analysis
API. Alert and cluster detail pages expose results, history, prompt metadata,
safe errors, and links between superseded standalone and cluster analysis.
