# Temporary development dependency audit exception

The frontend CI retains an unconditional production audit (`npm audit --omit=dev`).
Its full audit uses `tools/check-npm-audit.mjs` to accept only
`GHSA-vfj7-8cjw-p6xm`, including inherited findings whose complete cause graph
resolves exclusively to that advisory. Every affected lockfile node must be
development-only. Other advisories, malformed responses, network failures,
missing dependency metadata, and expired exceptions fail CI.

The operator approved temporary acceptance through **2026-11-05 00:00 UTC**.
The unpatched `braces` pattern-parser denial-of-service affects the current
Next lint/shadcn toolchain. Runtime exploitability in this application has not
been demonstrated; development-only placement is not a claim of zero risk.
Do not pass untrusted patterns into these tools.

Before expiry, check upstream releases and remove the exception once patched
dependencies are available, or replace the affected chain. Renewal requires
explicit review and approval; never automatically extend the date or broadly
suppress audit failures. This exception is not a vulnerability fix.

Run from `frontend`:

```sh
node --test ../tools/test-npm-audit.mjs
npm audit --omit=dev
node ../tools/check-npm-audit.mjs
```
