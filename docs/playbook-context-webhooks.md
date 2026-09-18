# Signed playbook context webhooks

TierX can ask a tenant-owned HTTPS endpoint for additional analysis
instructions while enriching an alert. This callback is optional, observes the
normalized alert only, and cannot stop the alert from continuing to correlation.

## Playbook configuration

Add an ordered list of non-secret context providers to a playbook YAML revision:

```yaml
context_webhooks:
  - webhook_id: threat-intel
    name: Threat intelligence
    enabled: true
    url: https://customer.example/tierx/threat-context
    timeout_seconds: 5
  - webhook_id: asset-context
    name: Asset inventory
    enabled: true
    url: https://customer.example/tierx/asset-context
    timeout_seconds: 3
```

The URL must use HTTPS and cannot contain credentials, a query string, or a
fragment. The timeout defaults to five seconds and must be between one and ten
seconds. A revision may contain at most ten providers. Provider IDs must be
unique, stable lowercase identifiers containing letters, numbers, `_`, or `-`.
The legacy singular `context_webhook` remains supported, but a revision cannot
contain both forms. Signing secrets are generated through the API/UI, never YAML.

Enabled providers run independently with at most five requests in flight. Their
results are stored in configuration order. Failure of one provider does not stop
another provider or the alert pipeline. Every provider uses the same effective
playbook signing secret, falling back to the tenant default.

Tenant and platform administrators can manage a tenant default secret at
`/api/v1/tenants/{tenant_id}/webhook-signing-secret` and one shared playbook override at
`/api/v1/tenants/{tenant_id}/playbooks/{playbook_id}/webhook-signing-secret`.
`POST` creates or rotates a 32-byte secret and reveals it once; `GET` returns
metadata only; `DELETE` removes it. A playbook override wins over the tenant
default immediately.

## Request and signature

The request is compact, key-sorted UTF-8 JSON. It contains `spec_version`, a
deterministic `delivery_id`, `sent_at`, tenant ID, normalized alert identity and
payload, the exact playbook revision, and release version/SHA. It never contains
the raw alert, authorization headers, credentials, or deployment secrets.

Headers:

```text
X-TierX-Webhook-Version: 1
X-TierX-Delivery-ID: <uuid>
X-TierX-Timestamp: <unix seconds>
X-TierX-Key-ID: <key id>
X-TierX-Signature: v1=<hex HMAC-SHA256>
```

TierX also emits the permanent `X-SOC-Mind-*` compatibility family with
identical values. Providers should prefer `X-TierX-*`; receivers that accept
both must reject conflicting pairs.

Verify the HMAC over the exact bytes:

```text
timestamp.delivery_id.raw_request_body
```

Receivers should reject timestamps more than five minutes from their clock and
store delivery IDs idempotently. Return HTTP 200 JSON with one non-empty string:

```json
{"prompt_footer":"Additional tenant-provided analysis instructions."}
```

The footer limit is 16 KiB. TierX makes no retry in one enrichment attempt.
Timeouts, invalid destinations, redirects, non-200 responses, and malformed or
oversized bodies are recorded as safe failure metadata; alert processing always
continues.

### Python verification

```python
import hashlib, hmac, time

timestamp = request.headers["X-TierX-Timestamp"]
delivery_id = request.headers["X-TierX-Delivery-ID"]
raw = request.body
if abs(int(time.time()) - int(timestamp)) > 300:
    raise ValueError("expired")
expected = hmac.new(
    secret.encode(),
    timestamp.encode() + b"." + delivery_id.encode() + b"." + raw,
    hashlib.sha256,
).hexdigest()
if not hmac.compare_digest("v1=" + expected, request.headers["X-TierX-Signature"]):
    raise ValueError("invalid signature")
```

### Node verification

```js
import { createHmac, timingSafeEqual } from "node:crypto";

const signed = Buffer.concat([
  Buffer.from(timestamp + "." + deliveryId + "."),
  rawRequestBody,
]);
const expected = "v1=" + createHmac("sha256", secret).update(signed).digest("hex");
if (!timingSafeEqual(Buffer.from(expected), Buffer.from(receivedSignature))) {
  throw new Error("invalid signature");
}
```

## Hosted reference receiver

Testing exposes `POST /api/v1/examples/playbook-context-webhook`. It uses the
same active tenant/playbook signing key, timestamp and signature checks, and
idempotent delivery ID behavior. It returns deterministic text derived from a
small allow-list of normalized alert fields. It performs no inference or action.

Configure the complete testing URL in a new playbook revision:

```text
https://tierx.example.com/api/v1/examples/playbook-context-webhook
```

Enable processing with `PLAYBOOK_CONTEXT_WEBHOOKS_ENABLED=true`. Both backend
and pipeline require the same base64url-encoded 32-byte
`WEBHOOK_SECRET_ENCRYPTION_KEY` and fail startup if it is absent or invalid.
`PLAYBOOK_WEBHOOK_MAX_COUNT` defaults to 10 and
`PLAYBOOK_WEBHOOK_MAX_CONCURRENCY` defaults to 5.
