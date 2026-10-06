# TierX

[![License: AGPL v3 only](https://img.shields.io/badge/License-AGPL--3.0--only-blue.svg)](LICENSE)

TierX is free software licensed under **GNU AGPL version 3 only**. Network users
can open the in-application Source Code page to reach the exact source tag for
the deployed build. Build and installation details are in [`SOURCE.md`](SOURCE.md).

Copyright © 2026 SAMIMI Tech Consulting GmbH.

The private Jira integration is documented in
[`integrations/jira-forge/README.md`](integrations/jira-forge/README.md). It
routes one raw alert from a Jira project into a configured tenant, source
system, and alert type while keeping the ingestion proxy private.

The Docker Compose stack includes:

- a frontend container on port `3000`
- a FastAPI backend on port `8000`
- MongoDB for persistence
- Ollama for local LLM serving
- an init job that pulls the configured Ollama model on first startup

The local development workflow is wrapped in the provided `Makefile`.

## Project Structure

```text
.
├── backend/              # FastAPI service
├── frontend/             # Node-based placeholder frontend server
├── init/                 # One-off initialization job for Ollama/model setup
├── compose.yaml          # Base Docker Compose services
├── compose.override.yaml # Local development overrides
├── compose.prod.yaml     # Production-style overrides
└── Makefile              # Common project commands
```

## Prerequisites

For an image-based installation without building source, see
[released-image examples and first-run setup](examples/usage/README.md).

Before starting, make sure you have:

- Docker installed and running
- Docker Compose v2 available via `docker compose`
- enough free disk space and memory for Ollama model downloads

## Quick local setup

The project reads environment values from `.env`. A sample file is already included as `.env.example`.

Create the environment and start every service:

```bash
make setup
make health
```

The first run builds the application and downloads the configured Ollama model.
Docker should have at least 8 GiB available. All published development ports bind
only to `127.0.0.1`. Production operators must provide their own deployment
configuration and secret-management system.

Available variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `MONGO_ROOT_USER` | `root` | MongoDB root username |
| `MONGO_ROOT_PASSWORD` | local-only sample | MongoDB root password |
| `PYTHON_ENV` | `development` | Backend environment hint |
| `OLLAMA_MODEL` | `phi3` | Model pulled by the init container |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Frontend API base URL |

These defaults are for local development only. Test and production deployments
must supply generated secrets and run with `PYTHON_ENV` set to a non-development
value. The application has no built-in JWT or administrator credential fallback;
startup fails when these required values are missing.

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

On the first run, startup may take longer because the `init` container checks Ollama and may download the model defined by `OLLAMA_MODEL`.

Once the stack is up, the main endpoints are:

- Frontend: `http://localhost:3000`
- Backend health check: `http://localhost:8000/api/v1/health`
- MongoDB: `localhost:27017`
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
make clean     # Stop the stack and remove volumes
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

## Service Notes

### Frontend

The current frontend container runs a small Node HTTP server from `frontend/server.js`. It serves a placeholder response on port `3000`.

### Backend

The backend is a FastAPI app in `backend/main.py`. The main implemented endpoint today is:

- `GET /api/v1/health` - returns overall health plus MongoDB and Ollama status

### Init Container

The init job in `init/init.sh` runs once during startup. It checks whether the configured Ollama model is already present and pulls it if needed.

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

- If `make up` appears slow on first start, Ollama is probably downloading the configured model.
- If containers stay unhealthy, inspect logs with `make logs`.
- If Ollama fails to start or pull models, make sure Docker has enough RAM and disk available.
- If ports `3000`, `8000`, `11434`, or `27017` are already in use, stop the conflicting process or change the port mappings in `compose.override.yaml`.
