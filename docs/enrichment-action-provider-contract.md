# Enrichment action provider contract

Platform-managed enrichment actions let one playbook request evidence from up
to ten external providers before correlation. A provider receives the full
normalized alert, but never the raw source payload or credentials. Its result is
recorded and appended to the analysis prompt as explicitly untrusted evidence.

## Configuration

A platform administrator creates an action under **Settings → Enrichment
actions**, selects all tenants or an allowlist, and copies the generated secret
once into the provider's secret manager. Tenant and platform admins then use the
immutable action code in a playbook revision:

```yaml
enrichment_actions:
  - check-server-port
  - validate-managed-login
```

Action URLs and timeout values are centrally managed and do not appear in the
playbook. The timeout range is 1–1800 seconds, default 300. A breaking behavior
change uses a new action code.

## HTTP request

TierX makes a `POST` to the configured public HTTPS URL with canonical JSON:

```json
{
  "spec_version": "1.0",
  "delivery_id": "deterministic UUID",
  "sent_at": "2026-08-31T12:00:00Z",
  "tenant_id": "tenant UUID",
  "action": {"code": "check-server-port"},
  "alert": {
    "alert_id": "alert UUID",
    "alert_type": "endpoint.malware",
    "source_system": "SPLUNK",
    "fingerprint": "sha256",
    "normalized_payload": {}
  },
  "playbook": {"playbook_id": "UUID", "version": 4},
  "release": {"version": "0.1.x", "sha": "full SHA"}
}
```

Headers:

```text
X-TierX-Action-Version: 1
X-TierX-Delivery-ID: <delivery_id>
X-TierX-Timestamp: <Unix seconds>
X-TierX-Key-ID: <key_id>
X-TierX-Signature: v1=<HMAC-SHA256 hex>
```

TierX also emits the permanent `X-SOC-Mind-*` compatibility family with
identical values. Providers should prefer `X-TierX-*`; receivers that accept
both must reject conflicting pairs.

Calculate the signature over the exact bytes:

```text
timestamp.delivery_id.raw_request_body
```

Providers must compare signatures in constant time, allow no more than five
minutes of clock skew, and persist delivery IDs. A repeated delivery ID must
return the original stored result because TierX may redeliver after a worker
crash.

## Successful response

Return HTTP 200 and JSON:

```json
{
  "spec_version": "1.0",
  "delivery_id": "matching delivery UUID",
  "outcome": "PORT_OPEN",
  "context_text": "The authorized check found TCP port 443 reachable."
}
```

`outcome` must match `[A-Z][A-Z0-9_]{0,63}`. `context_text` is required and may
contain at most 16 KiB of UTF-8. TierX does not follow redirects or retry an
action automatically. HTTP, TLS, timeout, and schema failures are recorded but
do not dead-letter the alert.

Providers, not TierX, own target authorization, credentials, allowlists,
rate limits, lockout prevention, and the safety of the action performed.

See `examples/enrichment-action-provider` for a containerized deterministic
implementation that verifies this contract and performs no external action.

## Guarded rollback of pending batches

Disable `ENRICHMENT_ACTIONS_ENABLED` and restart the pipeline before using this
command. It is a dry run unless both acknowledgement arguments are supplied:

```bash
cd /app
PYTHONPATH=. python tools/skip_pending_enrichment_actions.py
PYTHONPATH=. python tools/skip_pending_enrichment_actions.py \
  --apply --confirm SKIP_PENDING_ENRICHMENT_ACTIONS
```

The apply form marks unfinished actions skipped and publishes their stored
enriched messages. It does not delete batches or results.
