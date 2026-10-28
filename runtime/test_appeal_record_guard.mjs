import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { readAppealRecord, applyPriorAppealRecord } from './appeal_record_guard.mjs';

const receipt = () => ({ verified_submitted: [], skipped: [], blocked: [], unknown: [], warnings: [] });
async function temporary(t) {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'appeal-record-guard-'));
  t.after(() => fs.rm(root, { recursive: true, force: true })); return root;
}

for (const autoEnabledSkip of [false, true]) {
  for (const status of ['prepared', 'ready_for_confirmation', 'submitted_once', 'verified_submitted', 'skipped', 'blocked', 'unknown']) {
    test(status + ', auto skip=' + autoEnabledSkip + ' preserves original bytes', async t => {
      const root = await temporary(t); const file = path.join(root, 'record.md');
      const bytes = '# original evidence\n- 记录状态：' + status + '\n- 创建时间：old-original-time\n';
      await fs.writeFile(file, bytes);
      const prior = await readAppealRecord(file), result = receipt();
      const action = applyPriorAppealRecord(prior, result, 'key', { autoEnabledSkip });
      const expected = ['submitted_once', 'unknown'].includes(status) ? 'stop'
        : ['verified_submitted', 'blocked'].includes(status) || (autoEnabledSkip && status === 'skipped') ? 'read-only' : 'proceed';
      assert.equal(action, expected); assert.equal(await fs.readFile(file, 'utf8'), bytes);
      assert.equal(result.recordReadbacks[0].sha256, prior.sha256);
      if (action === 'stop') assert.deepEqual(result.unknown, ['key']);
    });
  }
}

test('missing file alone may proceed; malformed/duplicate/future states stay read-only', async t => {
  const root = await temporary(t), file = path.join(root, 'record.md');
  assert.equal(applyPriorAppealRecord(await readAppealRecord(file), receipt(), 'key'), 'proceed');
  for (const bytes of ['', 'partial record', '- 记录状态：attempted\n', '- 记录状态：unknown\n- 记录状态：prepared\n']) {
    await fs.writeFile(file, bytes);
    assert.equal(applyPriorAppealRecord(await readAppealRecord(file), receipt(), 'key'), 'stop');
    assert.equal(await fs.readFile(file, 'utf8'), bytes);
  }
});

test('symlink and directory are existing uncertain evidence, never treated as missing', async t => {
  const root = await temporary(t), link = path.join(root, 'record.md');
  await fs.symlink(path.join(root, 'missing-target'), link);
  assert.equal(applyPriorAppealRecord(await readAppealRecord(link), receipt(), 'key'), 'stop');
  assert.equal(applyPriorAppealRecord(await readAppealRecord(root), receipt(), 'key'), 'stop');
});

async function runAutoBranch(source, root, status) {
  const start = source.indexOf("    for (const initial of state.cards.filter(x => x.auto === '自动申诉已开启')) {");
  assert.ok(start > 0);
  const end = source.indexOf('\n    for (const initial of ', start + 5);
  const branch = source.slice(start, end);
  const execute = new (Object.getPrototypeOf(async function() {}).constructor)(
    'state', 'receipt', 'RECORDS', 'businessDate', 'readAppealRecord', 'applyPriorAppealRecord',
    'existingStatus', 'path', 'now', 'atomicWrite', 'buildMarkdown', 'excerpt', 'LABEL', branch);
  const dir = path.join(root, '2026-10-27'); await fs.mkdir(dir, { recursive: true });
  const file = path.join(dir, 'key.md'); const bytes = '- 记录状态：' + status + '\n- 创建时间：original\n';
  await fs.writeFile(file, bytes); const result = receipt(), writes = [];
  await execute({ totalNumber: 1, cards: [{ key: 'key', store: '测试店', date: '2026-10-27', auto: '自动申诉已开启', comment: '测试' }] },
    result, root, '2026-10-27', readAppealRecord, applyPriorAppealRecord, async () => status,
    path, () => 'test-time', async (file, record) => writes.push({ file, record }), value => value, value => value, '美团外卖');
  assert.equal(await fs.readFile(file, 'utf8'), bytes);
  return { result, writes };
}

test('old actual auto-enabled branch reproduces overwrite of unknown', async t => {
  const source = await fs.readFile(new URL('./state/appeal-record-readonly-20261028/meituan-waimai-negative-review-appeals-original.mjs', import.meta.url), 'utf8');
  const { writes } = await runAutoBranch(source, await temporary(t), 'unknown');
  assert.equal(writes.length, 1); assert.equal(writes[0].record.status, 'skipped');
});

for (const status of ['unknown', 'submitted_once', 'verified_submitted', 'blocked']) {
  test('new actual auto-enabled branch never overwrites ' + status, async t => {
    const source = await fs.readFile(new URL('../skills/workflows/meituan-waimai-negative-review-appeals/scripts/appeal_executor.mjs', import.meta.url), 'utf8');
    const { result, writes } = await runAutoBranch(source, await temporary(t), status);
    assert.equal(writes.length, 0);
    assert.deepEqual(result[status === 'submitted_once' ? 'unknown' : status], ['key']);
  });
}
