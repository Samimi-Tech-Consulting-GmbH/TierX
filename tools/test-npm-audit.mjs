import { test } from 'node:test';
import assert from 'node:assert/strict';
import { checkAudit, parseAuditProcess } from './check-npm-audit.mjs';

const report = (vulnerabilities = {}) => ({
  auditReportVersion: 2, vulnerabilities,
  metadata: { vulnerabilities: { total: Object.keys(vulnerabilities).length } },
});

test('clean audit passes', () => {
  assert.deepEqual(checkAudit(report()), []);
});
test('all findings fail, including the formerly excepted advisory', () => {
  for (const name of ['braces', 'sharp', 'other-development-tool']) {
    assert.throws(() => checkAudit(report({ [name]: { dev: true } })), /Vulnerabilities found/);
  }
});
test('malformed, error, and inconsistent responses fail closed', () => {
  for (const value of [{}, { error: { code: 'ENETWORK' } },
    { ...report({ sharp: {} }), metadata: { vulnerabilities: { total: 0 } } }]) {
    assert.throws(() => checkAudit(value));
  }
});
test('audit process errors and invalid JSON fail closed', () => {
  for (const result of [{ status: 2, stdout: '{}' },
    { status: null, error: new Error('timeout') }, { status: 1, stdout: 'not JSON' },
    { status: 1, signal: 'SIGTERM', stdout: '{}' }]) {
    assert.throws(() => parseAuditProcess(result));
  }
});
