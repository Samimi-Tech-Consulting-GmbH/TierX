# TierX

[![License: AGPL v3 only](https://img.shields.io/badge/License-AGPL--3.0--only-blue.svg)](LICENSE)

TierX is free software licensed under **GNU AGPL version 3 only**. Network users
can open the in-application Source Code page to reach the exact source tag for
the deployed build. Build and installation details are in [`SOURCE.md`](SOURCE.md).

Copyright © 2026 SAMIMI Tech Consulting GmbH.

The Jira integration is documented in
[`integrations/jira-forge/README.md`](integrations/jira-forge/README.md). It
routes one raw alert into an explicitly configured workflow URL while keeping
the ingestion proxy private.
The platform-managed graph runtime, fixed workflow URLs, nested playbooks,
agents, and REST/MCP tools are documented in [Workflow Studio](docs/workflows.md).
Platform-admin-authored [Python tools](docs/python-tools.md) run in disposable
containers through a separately provisioned rootless execution broker.
Workflows are the only execution system; an administrator must publish a workflow
and grant its tenant access before sending alerts. No default workflow is seeded.

## Installation

There are two supported ways to run TierX:

- from released images, for evaluation and customer-operated deployments
- from a source checkout, for development and debugging

### From released images

Requires Docker Engine and Compose v2.20+ (the examples rely on Compose
`include`). Published application images target Linux x86-64; on ARM hosts use
amd64 emulation or build the images locally. Node 20+ is needed only for the
optional setup helper.

```sh
cp -R examples/usage /path/to/tierx-install
cd /path/to/tierx-install
node setup.mjs --release vX.Y.Z
docker compose -f compose.all-in-one.yaml up -d
```

The helper writes `.env` with generated secrets (file mode 0600) and pins the
release. Without Node, copy `.env.example` to `.env` and fill in the secrets
yourself, and set `TIERX_RELEASE` to its numeric release tag without `v` (for
example `0.2.11`). Required generated secrets are `TIERX_MONGO_ROOT_PASSWORD`,
`TIERX_JWT_SECRET_KEY` and `TIERX_WEBHOOK_SECRET_ENCRYPTION_KEY`.
Use an exact release tag that includes the installer; older images
such as v0.2.0 do not. The all-in-one variant wants at least 4 CPU cores,
12 GiB RAM and 30 GiB of free disk. The external-Ollama topology,
environment-only bootstrap, model digest pinning, HTTPS, backups and upgrades
are covered in [`examples/usage/README.md`](examples/usage/README.md).

### First-run setup

A fresh deployment starts uninstalled: normal APIs answer
`503 INSTALLATION_REQUIRED` and the processing services wait. Open
`http://localhost:8080/installation`, copy the one-time setup token from the backend logs
(`docker compose -f compose.all-in-one.yaml logs backend`), choose the first administrator and the
product settings, then complete the wizard. The installer closes afterwards
and rejects further writes. Setting `TIERX_BOOTSTRAP_CONFIGURED=true` together
with the administrator, public URL and Ollama values installs from environment
alone. Both flows, the settings API and the token replacement procedure are
specified in
[`docs/installation-and-settings.md`](docs/installation-and-settings.md).

### From source (developer setup)

The local development workflow is wrapped in the provided `Makefile`. You
need Docker running, Compose v5.2.0 or newer, and enough free disk and memory for the
Ollama model downloads (8 GiB or more for Docker). CI exercises the manifests
against Compose v5.2.0; older releases have evaluated the nested environment
fallbacks in `compose.yaml` incorrectly, so keep Compose current.

The project reads environment values from `.env`. A sample file is included
as `.env.example`. Create the environment and start every service:

```bash
make setup
make health
```

The first run builds the application and downloads the configured Ollama
model. In this mode the platform administrator is bootstrapped from
`PLATFORM_ADMIN_EMAIL` and `PLATFORM_ADMIN_PASSWORD` instead of the installer.
All published development ports bind only to `127.0.0.1`. The sample values
are for local development only: test and production deployments must supply
generated secrets and run with `PYTHON_ENV` set to a non-development value.
The application has no built-in JWT or administrator credential fallback;
startup fails when these required values are missing.

## Project Structure

```text
.
├── backend/              # FastAPI service
├── frontend/             # Next.js frontend: login, installer, dashboard
├── ingestion-proxy/      # Authenticated alert ingestion in front of Kafka
├── pipeline/             # Kafka alert pipeline and workflow engine
├── kb_semantic/          # Optional semantic Knowledge Base indexing service
├── kb_shared/            # Shared Knowledge Base package
├── init/                 # One-off initialization job for Ollama/model setup
├── integrations/         # Jira Forge integration
├── docs/                 # Feature and contract documentation
├── examples/usage/       # Released-image Compose examples and setup helper
├── tools/                # Development and release tooling
├── compose.yaml          # Base Docker Compose services
├── compose.override.yaml # Local development overrides
├── compose.prod.yaml     # Production-style overrides
└── Makefile              # Common project commands
```

## Stack Services

The base `compose.yaml` defines the following services:

- `frontend` — Next.js application with login, first-run installation,
  onboarding and the analyst dashboard (alerts, clusters, schema registry,
  playbooks, knowledge base, admin settings)
- `backend` — FastAPI service with authentication, the installation and
  platform settings APIs, and tenant and alert handling
- `pipeline` — durable workflow scheduler executing the published graph's
  validation, mapping, deduplication, correlation and analysis nodes
- `ingestion-proxy` — retained transport service; legacy ingestion endpoints
  return `410`. Send new alerts through fixed workflow ingestion URLs
- `knowledge-base-processor` — background processor for Knowledge Base uploads
- `kb-semantic` — semantic Knowledge Base indexing service (retrieval/indexing
  flags default to false, but this source-stack container starts normally)
- `mongodb`, `kafka`, `ollama`, `qdrant` — persistence, event topics, local
  LLM serving, and the vector store behind the optional semantic KB
- `init` — one-off job that checks Ollama and pulls the configured model on
  first startup

The released-image examples instead name the initialization job `model-init`
and start semantic services only with `--profile semantic`.

## Configuration

Environment resolution prefers canonical `TIERX_*` names, then unprefixed
names; see
[`docs/tierx-compatibility.md`](docs/tierx-compatibility.md). The variables
that matter most for a local source setup are below. Released-image installs
use the canonical `TIERX_*` variables documented in `examples/usage/.env.example`.

| Variable | Default | Purpose |
| --- | --- | --- |
| `MONGO_ROOT_USER` | `root` | MongoDB root username |
| `MONGO_ROOT_PASSWORD` | local-only sample | MongoDB root password |
| `PLATFORM_ADMIN_EMAIL` | `local-admin@example.com` | Administrator bootstrapped on first startup |
| `PLATFORM_ADMIN_PASSWORD` | local-only sample | Administrator password, 12 to 72 bytes |
| `JWT_SECRET_KEY` | local-only sample | JWT signing key |
| `WEBHOOK_SECRET_ENCRYPTION_KEY` | empty | 32 random bytes as base64url; needed for playbook webhooks |
| `PYTHON_ENV` | `development` | Backend environment hint |
| `OLLAMA_MODEL` | `phi3:latest` | Model pulled by the init container |
| `OLLAMA_MODEL_DIGEST` | pinned `phi3` digest | Preflight and analysis reject digest mismatch; init may pull the tag |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Frontend API base URL |

Generate the webhook key with
`openssl rand -base64 32 | tr '+/' '-_' | tr -d '='`. The remaining Kafka,
LLM, webhook, enrichment and Knowledge Base knobs are commented in
[`.env.example`](.env.example).

## Running Locally

Start the local development stack:

```bash
make up
```

This uses `compose.yaml` together with `compose.override.yaml`, which enables:

- port mappings for all main services
- live source mounts for `backend/` and `frontend/`
- backend auto-reload with Uvicorn
- the frontend development command

On the first run, startup may take longer because the `init` container checks
Ollama and may download the model defined by `OLLAMA_MODEL`.

Once the stack is up, the main endpoints are:

- Frontend: `http://localhost:3000`
- Backend health check: `http://localhost:8000/api/v1/health`
- Ingestion proxy: `http://localhost:8001`
- MongoDB: `localhost:27017`
- Kafka (Docker-network clients): `kafka:9092`; the published localhost port is
  not a supported host-client endpoint because Kafka advertises its internal name
- Ollama API: `http://localhost:11434`

## Common Commands

Use the `Makefile` for day-to-day tasks:

```bash
make up        # Start the local development stack
make up-prod   # Start with production-style overrides
make down      # Stop the stack
make restart   # Restart the development stack
make logs      # Follow logs from all services
make build     # Rebuild local images
make status    # Show container status
make config    # Print merged Docker Compose config
make clean CONFIRM=destroy # Destructively remove stack volumes
```

Run the implemented checks:

```bash
make test
make lint
```

Both commands fail when a check fails.

Playbooks may optionally request signed tenant context during enrichment. The
configuration, HMAC contract, credential APIs, receiver examples, and hosted
testing reference endpoint are documented in
[`docs/playbook-context-webhooks.md`](docs/playbook-context-webhooks.md).
That URL-bearing playbook contract is retained for historical compatibility.
New platform-managed action integrations and their normalized-alert provider
contract are documented in
[`docs/enrichment-action-provider-contract.md`](docs/enrichment-action-provider-contract.md).

Tenant Knowledge Base upload, deterministic processing/search, playbook opt-in,
and untrusted-evidence prompt contract are documented in
[`docs/knowledge-base.md`](docs/knowledge-base.md).

Canonical TierX names and permanent rollback-compatible aliases are listed in
[`docs/tierx-compatibility.md`](docs/tierx-compatibility.md).

## Production-Style Run

To start the stack with the production override file:

```bash
make up-prod
```

This uses `compose.yaml` together with `compose.prod.yaml`. In that mode:

- the frontend is exposed on port `3000`
- the backend is not published to the host
- source-code mounts are not used
- resource limits are declared for the services

This profile is meant for local production-style trials. Customer-operated
installations should use the released-image setup described above.
It is not a production-ready networking configuration: the frontend binds on all
interfaces, and the browser API URL must be made reachable explicitly.

## Stopping and Resetting

To stop the stack:

```bash
make down
```

To remove Docker volumes, including persisted MongoDB, Kafka, and Ollama data,
provide the explicit destructive confirmation:

```bash
make clean CONFIRM=destroy
```

Use `make clean` carefully because it removes local persisted data.

## Troubleshooting

- A normal API answers `503 INSTALLATION_REQUIRED`: the deployment is not
  installed yet. Finish first-run setup or supply a complete environment
  bootstrap
  ([`docs/installation-and-settings.md`](docs/installation-and-settings.md)).
- If `make up` appears slow on first start, Ollama is probably downloading the configured model.
- If containers stay unhealthy, inspect logs with `make logs`.
- If Ollama fails to start or pull models, make sure Docker has enough RAM and disk available.
- If ports `3000`, `8000`, `8001`, `9092`, `11434`, or `27017` are already in use, stop the conflicting process or change the port mappings in `compose.override.yaml`.
