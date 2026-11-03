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
