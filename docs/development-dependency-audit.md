# Dependency audit policy

Frontend CI requires zero reported vulnerabilities in both production and full
dependency audits. Network failures, malformed reports, and any reported finding
fail the audit gate. There are no active advisory exceptions.

The former temporary Braces exception was removed after
[GHSA-vfj7-8cjw-p6xm](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm)
was withdrawn on October 23, 2026. The current lockfile also updates the affected
runtime and development dependency chains; withdrawal is not a package patch.

Run from `frontend`:

```sh
node --test ../tools/test-npm-audit.mjs
npm audit --omit=dev
node ../tools/check-npm-audit.mjs
```

## November 2026 remediation

- The frontend no longer installs the shadcn generator CLI and its deepmerge/MCP
  dependency chain. Its runtime CSS is retained verbatim from shadcn 4.22.1 under
  `frontend/src/styles`, with the MIT notice and an SBOM entry. Future component
  generation requires a separately audited tool; it is not part of application
  installation.
- Frontend minimatch is pinned to upstream 11.0.4. Older ESLint plugins expect a
  callable CommonJS/default export, so a small postinstall adapter restores those
  exports without changing upstream matching logic. It validates both original
  source checksums before writing, is idempotent, and fails closed on drift.
  `npm test` checks callable, named, class, defaults, and ESM APIs. Review the
  adapter and hashes before changing the pin; Docker includes the install script.
- Forge uses glob 14.0.3 and minimatch 11.0.4, removing the vulnerable traversal
  and matching versions. Forge's runtime/manifest tests and audit must pass.

These are dependency remediations, not audit suppressions. The full zero-finding
policy above remains unchanged.
