# TierX corresponding source

This repository is the corresponding source for TierX releases. A deployed
instance links to the exact immutable `vMAJOR.MINOR.PATCH` tag from its Source
Code page. The tag and full Git revision shown there identify the build.

TierX is licensed under `AGPL-3.0-only`; see [`LICENSE`](LICENSE). Operational
secrets, production data, and private deployment infrastructure are not part of
the application source and are not required to build it.

Copyright © 2026 SAMIMI Tech Consulting GmbH.

## Build and install

Use Docker Compose 5.2.0 or newer for the included manifests. CI pins 5.2.0;
older Compose releases can evaluate nested required-variable fallbacks eagerly
and reject valid canonical environment settings.

Requirements and the local workflow are documented in [`README.md`](README.md)
and `.env.example`. From a clean checkout of the displayed tag:

```bash
cp .env.example .env
make build
make up
make health
```

The Dockerfiles, Compose definitions, initialization scripts, frontend source,
backend, ingestion proxy, processing pipeline, shared Knowledge Base package,
example provider, and Jira Forge integration are included here.

For a customer-operated installation, replace every sample secret in `.env`
before startup and keep persistent data volumes outside the source tree.

## Dependency information

`sbom.cdx.json` is the machine-readable CycloneDX inventory generated from the
locked Node dependencies and the direct Python requirement constraints.
`THIRD_PARTY_NOTICES.md` records license metadata exposed by those manifests.
Python entries without an exact pin are deliberately unversioned; their
constraints remain in the `tierx:requirement` property. Node installation paths
have distinct component identities even when they share a package version.
Regenerate both with `python3 tools/generate_license_artifacts.py`.

## Source repository configuration

Release builds must supply `NEXT_PUBLIC_TIERX_SOURCE_REPOSITORY` as a frontend
build argument. GitHub Actions derives it from the repository being released.
For Compose builds, set `TIERX_SOURCE_REPOSITORY` to that repository's HTTPS URL,
along with `TIERX_APP_RELEASE_VERSION` and `TIERX_APP_RELEASE_SHA`. These values
are embedded during the frontend build; changing container runtime variables
does not update an already-built frontend. Development builds may omit them.
