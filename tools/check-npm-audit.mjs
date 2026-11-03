import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';

// Fail closed for every reported vulnerability, including development tools.
export function checkAudit(report) {
  if (report?.error || report?.auditReportVersion !== 2 ||
      !report.vulnerabilities || !Number.isInteger(report.metadata?.vulnerabilities?.total)) {
    throw new Error('Invalid or unsuccessful npm audit response');
  }
  const names = Object.keys(report.vulnerabilities);
  if (names.length !== report.metadata.vulnerabilities.total) {
    throw new Error('Inconsistent npm audit findings');
  }
  if (names.length) throw new Error(`Vulnerabilities found: ${names.join(', ')}`);
  return [];
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
    checkAudit(parseAuditProcess(result));
    console.log('No npm vulnerabilities found.');
  } catch (error) {
    console.error(`Audit gate failed: ${error.message}`);
    process.exitCode = 1;
  }
}
