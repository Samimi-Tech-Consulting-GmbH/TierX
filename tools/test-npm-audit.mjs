import { test } from 'node:test';
import assert from 'node:assert/strict';
import { checkAudit, parseAuditProcess } from './check-npm-audit.mjs';

const exception = { advisory: 'GHSA-vfj7-8cjw-p6xm', package: 'braces', expires: '2026-11-05' };
const now = new Date('2026-10-06T00:00:00Z');
const fixture = () => ({
  auditReportVersion: 2,
  vulnerabilities: {
    braces: { via: [{ name: 'braces', dependency: 'braces', url: `https://github.com/advisories/${exception.advisory}` }], nodes: ['node_modules/braces'] },
    tool: { via: ['braces'], nodes: ['node_modules/tool'] },
  },
  metadata: { vulnerabilities: { total: 2 } },
});
const lock = { packages: { 'node_modules/braces': { dev: true }, 'node_modules/tool': { dev: true } } };
test('accepts only exact advisory and inherited development findings', () => {
  assert.deepEqual(checkAudit(fixture(), lock, exception, now), ['braces', 'tool']);
});
test('rejects another advisory, even on the same package or mixed with allowed cause', () => {
  const report = fixture();
  report.vulnerabilities.braces.via.push({ name: 'braces', dependency: 'braces', url: 'https://github.com/advisories/GHSA-other' });
  assert.throws(() => checkAudit(report, lock, exception, now), /Unapproved/);
});
test('rejects expiry at UTC boundary', () => {
  assert.throws(() => checkAudit(fixture(), lock, exception, new Date('2026-11-05T00:00:00Z')), /expired/);
});
test('rejects production or missing lockfile nodes', () => {
  assert.throws(() => checkAudit(fixture(), { packages: {} }, exception, now), /development-only/);
  assert.throws(() => checkAudit(fixture(), { packages: { ...lock.packages, 'node_modules/braces': { dev: false } } }, exception, now), /development-only/);
});
test('rejects missing causes and cyclic dependency graphs', () => {
  for (const cause of ['missing', 'tool']) {
    const report = fixture(); report.vulnerabilities.braces.via = [cause];
    assert.throws(() => checkAudit(report, lock, exception, now), /Unresolvable/);
  }
});
test('rejects malformed, error, and inconsistent audit responses', () => {
  for (const report of [{}, { error: { code: 'ENETWORK' } }, { ...fixture(), metadata: { vulnerabilities: { total: 0 } } }]) {
    assert.throws(() => checkAudit(report, lock, exception, now));
  }
});
test('audit process errors and invalid JSON fail closed', () => {
  for (const result of [{ status: 2, stdout: '{}' }, { status: null, error: new Error('timeout') }, { status: 1, stdout: 'not JSON' }, { status: 1, signal: 'SIGTERM', stdout: '{}' }]) {
    assert.throws(() => parseAuditProcess(result));
  }
});
test('clean audit passes without relying on expired exception', () => {
  const report = fixture(); report.vulnerabilities = {}; report.metadata.vulnerabilities.total = 0;
  assert.deepEqual(checkAudit(report, lock, exception, new Date('2027-01-01')), []);
});
