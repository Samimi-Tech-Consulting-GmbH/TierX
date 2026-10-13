# Ingestion V2 local verification

## Review candidate

The experimental implementation starts from the requested PR #10 commit
`3bc29ab7a983ab9c5e049821e5b6819fc7e8efe5`. PR #10 has since advanced; this
branch is intentionally pinned and must be reconciled with the final installer
branch before any future main merge. No release, remote deployment, Jira change,
or data migration is included.

## Automated checks

Local results on 13 October 2026:

| Check | Result |
| --- | --- |
| Backend including V2 | 238 passed, 3 environment-dependent MongoDB tests skipped |
| Pipeline including V2 | 127 passed |
| Ingestion proxy regression suite | 10 passed |
| Frontend | 101 passed; production build passed |
| Frontend lint | No errors; four existing navigation warnings |
| Jira Forge regression suite | 50 passed |
| Semantic KB suite | 49 passed |
| Example enrichment provider | 3 passed |
| Setup helper | 2 passed |
| Branding, license and Compose tool tests | 8 passed |
| npm audit policy tests | 8 passed |
| Compose all-in-one/external Ollama plus V2 overlays | Rendered successfully |
| Staged diff and existing Git history secret scans | No findings |

The inherited development dependency advisory `GHSA-vfj7-8cjw-p6xm` remains
covered by the existing bounded audit exception expiring 5 November 2026. No
production dependency vulnerability was reported by the npm audit check.

## Container and browser verification

A separate localhost-only Docker project built backend, pipeline, and frontend
from this branch, using a disposable MongoDB and local Ollama. The smoke script
created synthetic tenants and alerts and verified:

- Immediate solo-cluster analysis with real structured model output.
- A second non-duplicate alert joining that cluster, incrementing its analysis
  version, and preserving summary history.
- Exact duplicates and missing critical fields taking explicit dead-letter paths.
- Parallel KB/provider branches, a failed provider on the reserved `.invalid`
  domain, a successful catch, ordered join, and continued real model analysis.
- V2 analysis status, UTC timestamps, and linked cluster request history.
- Zero V1 alert and cluster records in the synthetic tenant databases.

Browser checks covered templates, graph validation, read-only historical
execution snapshots, node state/timing details, dark canvas controls, responsive
canvas expansion, and linked cluster summaries/members. All screenshot values
are synthetic. The local demo exposes only a localhost reverse proxy; it does
not expose ingestion, MongoDB, Kafka, or Ollama ports.

## Remaining review gates

This is a draft experimental PR, not a production-readiness claim. Before enabling
V2 outside an isolated PoC:

- Review the complete scheduler and storage isolation design, including process
  termination at every persistence boundary and distributed worker behavior.
- Exercise debounce expiry, window closure, stale delta versions, and cluster
  concurrency end to end with controlled time. Existing correlation unit tests
  cover the reused algorithms; local smoke checks use critical immediate analysis.
- Test native tool calling against a real capable model and OpenAI-compatible
  implementation. Adapter tests are mocked; the live local model validates
  structured analysis, not every native protocol.
- Evaluate ordinary inference replay after a crash between provider response and
  persistence. External exactly-once behavior is explicitly unsupported.
- Add a profile model-digest policy and stronger free-text redaction if sensitive
  tenant data will be used. Current safeguards are not general-purpose DLP.
- Stress queue fairness, dataset size, response pagination, and snapshot retention.
  This milestone uses a single execution worker and has no V2 retention policy.
- Review operator ergonomics: advanced configuration uses typed JSON fields;
  resource mapping is explicit, not a guided migration of V1 schemas/playbooks.

Keep `TIERX_INGESTION_V2_ENABLED=false` in normal deployments while these gates
remain open. Disabling the flag prevents new API submissions and worker startup;
existing V2 records stay intact. Stop the local Compose project without removing
volumes when the evaluation is complete.
