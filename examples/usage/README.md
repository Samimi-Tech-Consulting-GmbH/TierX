# Run TierX from released images

Requires Docker Engine and Compose v2.20+ (Compose `include` support). Copy this
whole folder, including `compose.common.yaml` and `nginx.conf`. Node 20+ is needed
only for the optional setup helper. No application build or npm install is needed.
Published application images currently target Linux x86-64. ARM machines need
explicit amd64 emulation or locally built ARM images; native ARM release images
are not provided by the current release workflow.

Choose an exact release tag containing this installer. These examples cannot
provide installation features when used with an older image such as v0.2.0.
All application services use the same explicit tag; do not use `latest`.
Git release tags include `v`; GHCR image tags do not. The setup helper stores
the numeric image tag (for example `0.2.0`) in `TIERX_RELEASE`. Select a release
published after this installer is merged; pre-installer releases are not compatible.

## All-in-one

```sh
node setup.mjs --release vX.Y.Z
docker compose -f compose.all-in-one.yaml up -d
docker compose -f compose.all-in-one.yaml logs backend
```

Open http://localhost:8080/installation and enter the one-time token printed by
the backend. Choose the first administrator and product settings. Leave Ollama
at `http://ollama:11434`; model-init downloads the model on first startup.
Analysis can stay disabled while that download completes. Enabling it requires
successful model lookup and a real structured inference check.

Use at least 4 CPU cores, 12 GiB RAM and 30 GiB free disk for the default CPU
model; performance varies with hardware. MongoDB 7 requires a compatible CPU
(including AVX on x86). This example does not upgrade existing MongoDB volumes.

## External Ollama

```sh
node setup.mjs --release vX.Y.Z
docker compose -f compose.external-ollama.yaml up -d
docker compose -f compose.external-ollama.yaml logs backend
```

Enter the external Ollama origin/model in the installer, or set
`TIERX_OLLAMA_URL` and `TIERX_OLLAMA_MODEL` in `.env` to manage them by environment.
The origin must be reachable from application containers. `localhost` refers to
the container; on Docker Desktop a host service may use
`http://host.docker.internal:11434`. Linux operators must explicitly configure
host-gateway access if needed. The external operator installs the selected model;
TierX never automatically replaces or pulls an external model.

Allow at least 4 CPU cores, 6 GiB RAM and 20 GiB disk without local inference.
Only Ollama's API is supported here, not an OpenAI-compatible endpoint.

## Environment-only installation

Set the following before startup (and keep `.env` outside Git):

```dotenv
TIERX_BOOTSTRAP_CONFIGURED=true
TIERX_INSTALLATION_ENABLED=false
TIERX_PLATFORM_ADMIN_EMAIL=admin@example.com
TIERX_PLATFORM_ADMIN_PASSWORD=<unique-password-at-least-12-characters>
TIERX_PUBLIC_URL=https://tierx.example.com
TIERX_OLLAMA_URL=http://ollama:11434
TIERX_OLLAMA_MODEL=phi3:latest
```

Incomplete environment bootstrap fails with missing variable names. Existing
installations retain their administrator and never reset its password on restart.
The first successful setup closes the installer; subsequently sign in and open
Settings → Platform settings. Environment-supplied values remain read-only there.
Database, Kafka, internal service URLs, JWT and encryption keys are deployment
configuration. They cannot be edited in the installer or admin panel.
`TIERX_MONGO_URL` can override the generated internal MongoDB URI. These two
variants still include a local MongoDB service; an external-database topology
requires an operator-reviewed Compose override. Never put credential-bearing
URIs in the public URL or Ollama fields.

Without Node, copy `.env.example` to `.env`, select the release, and supply unique
MongoDB/JWT/encryption secrets manually. The encryption key must encode 32 random
bytes as base64url. Restrict `.env` to mode 0600.

## Access and HTTPS

Only the proxy is published, on localhost by default. For a remote installation,
use a trusted HTTPS reverse proxy in front of this port and set the public URL
accordingly. Do not send setup tokens, passwords, or login requests over public
HTTP. Certificate automation is deliberately outside this example.

MongoDB, Kafka, Ollama, ingestion and optional vector services remain unpublished.
Send alerts through authenticated TierX integrations/debug APIs, not a public
ingestion-proxy port. Internal API requests use same-origin `/api` and require no
frontend image rebuild. The public URL does not change DNS or proxy routing.

## Operations

Use the selected filename consistently:

```sh
docker compose -f compose.all-in-one.yaml ps
curl -f http://localhost:8080/api/v1/health
docker compose -f compose.all-in-one.yaml logs --tail 100 pipeline backend
docker compose -f compose.all-in-one.yaml down
```

`down` preserves data. Named volumes hold MongoDB (including users, installation
state, files and settings), Kafka and local models. Protect deployment secrets:
losing the encryption key can make stored integration credentials unrecoverable.

Before upgrades, stop ingestion/application writers and take a consistent backup
of MongoDB/GridFS, Kafka, optional vector/history volumes, and `.env`; encrypt and
keep a copy off the Docker host. Test restoration on an isolated Docker project.
Change `TIERX_RELEASE` to the reviewed release, then run `pull` and `up -d` with
the same Compose file/project. Keep a copy of the previous configuration for rollback.
Never assume changing an image tag reverses a future data migration.

Destructive local reset requires an explicit operator command:

```sh
# WARNING: permanently deletes this project's named volumes and installation.
docker compose -f compose.all-in-one.yaml down --volumes
```

## Optional semantic Knowledge Base

Start `--profile semantic` only after reviewing the separate Knowledge Base
documentation and embedding-model preflight. Set `TIERX_EMBEDDING_OLLAMA_URL`
when embeddings use an external host. Semantic flags default to false; merely
starting Qdrant does not enable retrieval. Model digest and resource checks are
required before enabling semantic features. The installer exposes deterministic
Knowledge Base switches only.

## Troubleshooting

- `INSTALLATION_REQUIRED`: finish setup, or supply complete environment bootstrap.
- Installer unavailable: installation is complete, or disabled by environment.
  An unfinished installation can use an operator-provided replacement token
  through `TIERX_INSTALLATION_TOKEN` after restarting backend.
- Model missing/inference rejected: check model name, reachability and Ollama
  output. Analysis stays disabled; the installer does not substitute a model.
- Settings changed: reload before saving again. Applied revisions may lag while
  an active job finishes. Check service timestamps and safe configuration errors.
- Do not use reset to troubleshoot an existing deployment; it removes all data.

## Developer verification

`node --test test-setup.mjs` checks secret generation, file permissions, and
preservation of existing values without touching your `.env`.

For a **fresh disposable localhost deployment only**, run:

```sh
TIERX_SMOKE_URL=http://127.0.0.1:8080 TIERX_SMOKE_TOKEN='<setup-token>' \
  node smoke-installation.mjs
```

This completes installation with a synthetic `admin@example.com` administrator
and a random password that is not printed. It verifies API gates, token
consumption, revision conflicts and service propagation. It refuses already
installed databases or remote hosts. It is not a production onboarding command.
