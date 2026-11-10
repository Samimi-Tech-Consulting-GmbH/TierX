# TierX Workflow Sandbox

Dependency-free local alert sender and node-debug watcher. Requires Node.js 20+.

## Switch environments without restarting

The Environment selector switches between server-approved targets. Configure
additional targets once using `SANDBOX_TARGETS` (a JSON array), for example:

```sh
TIERX_TARGET=http://127.0.0.1:18084 \
SANDBOX_TARGETS='[{"label":"Testing","target":"https://testing-api.example.com","ui_origin":"https://testing.example.com"}]' \
npm run dev
```

Switching stops local requests/watchers and clears login, entry token and workflow
path. Re-enter the destination environment's credentials and workflow path.
Payloads remain available for reuse. Targets cannot be supplied by AI or imported
scenarios; arbitrary browser-supplied proxy destinations are rejected. Target
configuration changes require one server restart, but switching configured targets
does not. Only HTTPS and localhost HTTP origins are accepted.

```sh
npm install
TIERX_TARGET=https://your-instance.example npm run dev
```

Open `http://127.0.0.1:4174`. The default target is `http://127.0.0.1:8080` for local development. Set `SANDBOX_PORT` to change the local port. If your local frontend uses a different origin from the API, set `TIERX_UI_ORIGIN` to the frontend origin so Debug links open correctly. It binds only to localhost; do not expose it as a public service.

1. Prepare a disposable tenant and a published, assigned workflow. Its entry must match the raw JSON you send. The supplied payload is synthetic, not a real customer alert.
2. Log in with an account authorized to inspect that tenant. The observer JWT stays in page memory, not local/session storage or files.
3. Paste the fixed workflow ingestion **path** and its copy-once entry token. The token is used only for ingestion; it is not the observer login token.
4. Edit/format the payload or choose Make unique. Send returns after acceptance, without waiting for analysis. Duplicate pair sends two distinct deliveries of the identical payload, useful for fingerprint tests.
5. Watch up to five alerts every five seconds for five active minutes each. Pause freezes the clock. Cancel only stops local observation. Resume/Watch again starts another period after timeout or completion. A sixth alert evicts the oldest watcher; reload clears all memory and credentials.

Cards show the immutable workflow revision, application release, node state, route/selection, safe inputs/outputs, attempts and timings. The full-debug link opens the graph and nested playbook/agent executions in TierX. Raw documents, full prompts and credentials are intentionally absent from debug snapshots.

The local proxy permits only login, identity, fixed workflow ingestion and tenant run inspection against the startup-configured origin. It rejects foreign browser origins, redirects, arbitrary proxy paths and oversized payloads. It never logs or stores credentials. Do not use production alert data in a sandbox.

`npm test` checks proxy routing, origin boundaries, credential forwarding and redirect rejection. Zip this directory without `node_modules` to share it; it has no runtime dependencies. Never include credentials or a local environment file in the archive.

## Populate the disposable acceptance instance

From an application checkout, after `acceptance.py --serve` has prepared the dedicated local stack, run
`python seed_demo.py` with the application Python dependencies. It adds a named
demo tenant, fast and real-model workflows, reusable playbook flows and an agent,
an indexed synthetic Markdown Knowledge Base, and success/correlation/duplicate/
validation examples. Re-running updates the demo definitions without adding the
same initial alert batch again. It accepts only the isolated localhost target.

Use **Workflows**, **Playbooks**, and **Agents** for the unified graph libraries.
The former Ingestion V2 entry URLs redirect to this Studio; there is no separate
editor. Select a playbook/agent node to preview or open its subflow. Select a
playbook selector to inspect its mapped, candidate and fallback playbooks.
Start with `demo-fast-triage` for an
interactive test; its reasoning is explicitly a protocol fixture. Use
`demo-real-triage` for actual phi3 inference, which can take several minutes.

The Python harnesses require an application checkout and its Python dependencies;
they are not part of the sender-only ZIP. Ordinary sender use needs only Node.js.

## Optional AI scenarios

Configure a separate local-server provider explicitly. AI is disabled by default;
manual sending and saved replay work without it. No SDK or runtime dependencies
are needed. Keep real customer data and credentials out of samples/descriptions.

```sh
# Ollama: set the exact installed model you choose; no model is downloaded.
SANDBOX_AI_PROVIDER=ollama SANDBOX_AI_URL=http://127.0.0.1:11434 \
  SANDBOX_AI_MODEL=your-installed-model TIERX_TARGET=https://your-test-instance.example npm run dev

# OpenAI-compatible: use an API base supporting chat/completions + JSON Schema.
SANDBOX_AI_PROVIDER=openai-compatible SANDBOX_AI_URL=https://ai.example/v1 \
  SANDBOX_AI_MODEL=your-model npm run dev
```

Supply `SANDBOX_AI_API_KEY` through your shell/secret manager if required. It stays
on the local server and is never returned to the browser or sent to TierX. Optional
`.env.example` is a reference; `npm run dev` does not automatically load `.env`.
With Node supporting it, `node --env-file=.env server.mjs` loads a local ignored file.
Only HTTPS or localhost HTTP AI endpoints are accepted; redirects are rejected.
Providers without the requested structured-output contract fail visibly; there is
no silent provider/model substitution. Only sample JSON, scenario description,
preset/count and optional schema are sent to the AI, never TierX routing/tokens.

1. Keep the source sample in **Alert JSON**, describe a synthetic scenario, choose
   a preset and generate 1–20 alerts. Review/edit the batch before sending.
2. **Send batch once** sends each previewed alert once. **Start loop** either
   replays the batch or generates fresh batches of up to five as needed.
3. Defaults: ten submissions, five seconds apart, one request at a time. Limits:
   1,000 submissions or 60 wall-clock minutes (including pauses), whichever first.
   A confirmation lists the fixed target/path, mode, limits and negative-test state.
4. Pause aborts local in-flight work and stops new sends. Resume retries an uncertain
   pending submission with the same idempotency key. Stop never recalls accepted
   alerts. Interrupted submissions are archived as `UNKNOWN`; inspect their delivery
   IDs before replaying. Transient failures allow three retries using the same key;
   authentication/routing failures stop the run, while 422 payload rejections count
   separately and continue. Generation has one slot and a 120-second timeout.

The supplied correlated preset preserves `result.host`, `result.src`, `result.user`
from the sample; adjust the sample/preview to the actual workflow mapping. Correlation
still depends on the deployed workflow. Duplicate mode disables field refresh and
repeats an identical generated alert. Validation-failure mode requires explicit
consent and removes the configured required field, including after replay refresh.
It is labelled an intentional negative test, not schema-valid success.

Replay can preserve bytes at the JSON-value level or refresh configured dotted
timestamp/unique fields (defaults `result._time` and `result.rule_id`). The same
delivery's retries keep its exact body. Different replay submissions use different
delivery IDs, allowing the pipeline's fingerprint deduplication to be tested.

### Validation and local archives

Without a schema the badge reads `STRUCTURAL_ONLY`: valid JSON is not proof of a
valid Splunk alert. The dependency-free JSON Schema subset supports `type`,
`properties`, `required`, `additionalProperties`, `items`, item/string length and
numeric bounds, `enum`, `const`, `allOf`, `anyOf`, `oneOf`, `title`, `description`
and `$schema`. Unsupported keywords (including `$ref`, `pattern` and `format`)
are rejected rather than ignored. Generation validates before applying explicitly
selected negative-test mutations. No scanning, credential testing, tool execution
or real security investigation is performed by generation.

Generated/edited scenarios are saved automatically under `.sandbox-data/` (ignored
by Git), or `SANDBOX_DATA_DIR`. Directories use 0700 and files 0600. Outcome JSONL
records contain actual sent payloads, delivery IDs, status and accepted alert/run
IDs—never request headers or credentials. The server rejects credential-bearing
JSON properties/private keys and common token/credential URL forms; this is a
safeguard, not a guarantee that arbitrary free text contains no sensitive data.
Archives are limited to 10 MiB per scenario and scenario requests to 2 MiB; a full
archive stops the run visibly. Export/archive these files privately as needed.

Use the saved list or JSON import/export to replay without AI. Export includes the
actual submission outcomes; importing a run selects the sent payloads for replay.
Credentials must be entered again. Never include `.sandbox-data`, `.env`, logs or
credentials in a client ZIP. Existing five-card watchers remain independent of
loop counters; evicting a watcher does not cancel processing.
