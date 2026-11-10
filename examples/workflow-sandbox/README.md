# TierX Workflow Sandbox

Dependency-free local alert sender and node-debug watcher. Requires Node.js 20+.

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
