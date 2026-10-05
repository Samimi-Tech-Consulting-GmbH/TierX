import { readFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';

// Fail closed: every dependency path must resolve exclusively to the approved
// advisory, and every affected installed node must be development-only.
export function checkAudit(report, lock, exception, now = new Date()) {
  if (report?.error || report?.auditReportVersion !== 2 ||
      !report.vulnerabilities || !Number.isInteger(report.metadata?.vulnerabilities?.total)) {
    throw new Error('Invalid or unsuccessful npm audit response');
  }
  const findings = report.vulnerabilities;
  const names = Object.keys(findings);
  if (names.length !== report.metadata.vulnerabilities.total) {
    throw new Error('Inconsistent npm audit findings');
  }
  if (!names.length) return [];
  if (exception.advisory !== 'GHSA-vfj7-8cjw-p6xm' || exception.package !== 'braces' ||
      !/^\d{4}-\d{2}-\d{2}$/.test(exception.expires) ||
      !Number.isFinite(Date.parse(exception.expires)) || now >= new Date(`${exception.expires}T00:00:00Z`)) {
    throw new Error('Audit exception invalid or expired');
  }
  const visit = (name, ancestors = new Set()) => {
    const entry = findings[name];
    if (!entry || ancestors.has(name) || !Array.isArray(entry.via) || !entry.via.length ||
        !Array.isArray(entry.nodes) || !entry.nodes.length) {
      throw new Error(`Unresolvable audit finding: ${name}`);
    }
    for (const node of entry.nodes) {
      if (lock.packages?.[node]?.dev !== true) {
        throw new Error(`Affected dependency is not development-only: ${name}`);
      }
    }
    const next = new Set([...ancestors, name]);
    for (const cause of entry.via) {
      if (typeof cause === 'string') visit(cause, next);
      else if (cause?.url !== `https://github.com/advisories/${exception.advisory}` ||
               cause?.name !== exception.package || cause?.dependency !== exception.package) {
        throw new Error(`Unapproved advisory affecting ${name}`);
      }
    }
  };
  names.forEach(name => visit(name));
  return names;
}

export function parseAuditProcess(result) {
  if (result.error || result.signal || ![0, 1].includes(result.status)) {
    throw new Error('npm audit failed to execute successfully');
  }
  return JSON.parse(result.stdout);
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const result = spawnSync('npm', ['audit', '--json'], {
      encoding: 'utf8', timeout: 120_000, maxBuffer: 10 * 1024 * 1024,
    });
    const report = parseAuditProcess(result);
    const lock = JSON.parse(readFileSync('package-lock.json', 'utf8'));
    const exception = JSON.parse(readFileSync(new URL('./npm-audit-exceptions.json', import.meta.url), 'utf8'));
    const accepted = checkAudit(report, lock, exception);
    console.log(accepted.length
      ? `TEMPORARY EXCEPTION: ${exception.advisory}; expires ${exception.expires} UTC; affected dev packages: ${accepted.join(', ')}`
      : 'No npm vulnerabilities found.');
  } catch (error) {
    console.error(`Audit gate failed: ${error.message}`);
    process.exitCode = 1;
  }
}
