# Contributing to TierX

The canonical repository is https://github.com/Samimi-Tech-Consulting-GmbH/TierX.
Create feature/, fix/, ci/, or docs/ branches and submit pull requests to main.
Run the component tests and follow SOURCE.md for local builds.

Never submit credentials, tenant exports, real alerts, customer documents,
screenshots containing user data, or deployment-specific configuration.
Use synthetic examples, reserved example domains and documentation IP ranges.

Releases require successful CI. Maintainers enable RELEASES_ENABLED in repository
variables after initial verification. The first release is v0.2.0; subsequent
successful main updates increment the patch version. The manual workflow supports
major/minor increments. Images are published under
ghcr.io/samimi-tech-consulting-gmbh/tierx-<service>, tagged by full SHA and version.
The completed GitHub Release is published only after all images are available.
