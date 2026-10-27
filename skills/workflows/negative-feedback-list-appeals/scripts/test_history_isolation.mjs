// Isolated records only; no browser, production writes, or business submission.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { existingRecordAnyDate, stableRecordKey } from './jinsha.mjs';
import { buildMarkdown, recordPriorOutcome } from './appeal_executor.mjs';

const root = await fs.mkdtemp(path.join(os.tmpdir(), 'feedback-history-'));
const target = { platform: 'meituan', store: '隔离测试店', date: '2026-10-25', orderNo: 'test-order', category: '测试分类' };
const key = stableRecordKey(target);
const record = { ...target, key, businessDate: '2026-10-27', platformLabel: '美团外卖', status: 'unknown' };
let tests = 0;
const receipt = () => ({ unknown: [], verified_submitted: [], blocked: [], skipped: [], historicalUnknown: [], platforms: { meituan: { candidates: [] } } });
async function write(day, patch = {}) {
  const dir = path.join(root, day);
  await fs.mkdir(dir, { recursive: true });
  await fs.writeFile(path.join(dir, key + '.md'), buildMarkdown({ ...record, ...patch }));
}
try {
  await write('2026-10-27');
  const original = await fs.readFile(path.join(root, '2026-10-27', key + '.md'));
  const prior = await existingRecordAnyDate(key, root);
  assert.equal(prior.businessDate, '2026-10-27'); tests++;
  const current = receipt();
  assert.equal(recordPriorOutcome(prior, key, target, 'meituan', '2026-10-28', current), 'continue'); tests++;
  assert.deepEqual(current.unknown, []); tests++;
  assert.equal(current.historicalUnknown[0].state, 'unknown'); tests++;
  assert.match(current.historicalUnknown[0].sourceSha256, /^[a-f0-9]{64}$/); tests++;
  assert.equal(current.verified_submitted.length, 0); tests++;
  assert.equal(recordPriorOutcome(prior, key, target, 'meituan', '2026-10-27', receipt()), 'stop'); tests++;
  assert.equal(recordPriorOutcome(prior, key, target, 'meituan', '2026-10-26', receipt()), 'stop'); tests++;
  assert.equal(recordPriorOutcome({ ...prior, businessDate: null }, key, target, 'meituan', '2026-10-28', receipt()), 'stop'); tests++;
  for (const status of ['verified_submitted', 'blocked', 'submitted_once', 'prepared']) {
    const result = receipt();
    assert.equal(recordPriorOutcome({ ...prior, status }, key, target, 'meituan', '2026-10-28', result), 'continue');
    assert.equal(result.historicalUnknown.length, 0); tests++;
  }
  assert.equal(recordPriorOutcome(null, key, target, 'meituan', '2026-10-28', receipt()), 'new'); tests++;
  assert.deepEqual(await fs.readFile(path.join(root, '2026-10-27', key + '.md')), original); tests++;
  for (const patch of [{ businessDate: '2026-10-26' }, { key: 'bad-key' }, { orderNo: 'changed-order' }, { platformLabel: '淘宝闪购' }]) {
    await write('2026-10-27', patch);
    const invalid = await existingRecordAnyDate(key, root);
    assert.equal(invalid.status, 'unknown');
    assert.equal(invalid.businessDate, null);
    assert.equal(recordPriorOutcome(invalid, key, target, 'meituan', '2026-10-28', receipt()), 'stop'); tests++;
  }
  await fs.rm(path.join(root, '2026-10-27'), { recursive: true });
  await write('2026-02-30', { businessDate: '2026-02-30' });
  assert.equal((await existingRecordAnyDate(key, root)).businessDate, null); tests++;
  await fs.rm(path.join(root, '2026-02-30'), { recursive: true });
  await write('2026-10-27');
  await write('2026-10-28', { businessDate: '2026-10-28' });
  assert.equal((await existingRecordAnyDate(key, root)).businessDate, '2026-10-28'); tests++;
  assert.equal(recordPriorOutcome(await existingRecordAnyDate(key, root), key, target, 'meituan', '2026-10-28', receipt()), 'stop'); tests++;
  await fs.rm(path.join(root, '2026-10-28'), { recursive: true });
  const outside = path.join(root, 'outside.md');
  await fs.writeFile(outside, buildMarkdown(record));
  await fs.rm(path.join(root, '2026-10-27', key + '.md'));
  await fs.symlink(outside, path.join(root, '2026-10-27', key + '.md'));
  assert.equal((await existingRecordAnyDate(key, root)).businessDate, null); tests++;
  console.log(JSON.stringify({ ok: true, tests, productionWrites: 0, sendAttempts: 0 }));
} finally {
  await fs.rm(root, { recursive: true, force: true });
}
