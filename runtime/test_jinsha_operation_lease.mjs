import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { withJinshaOperationLease } from './jinsha_operation_lease.mjs';
import { acquireJinshaLease, releaseJinshaLease } from '../skills/posts/jinsha-post/scripts/lease.mjs';
import * as meituan from '../skills/workflows/meituan-waimai-negative-review-appeals/scripts/appeal_executor.mjs';
import * as taobao from '../skills/workflows/taobao-shangou-negative-review-appeals/scripts/appeal_executor.mjs';
import * as mtCollect from '../skills/workflows/meituan-waimai-negative-review-appeals/scripts/all_appeals_collector.mjs';
import * as tbCollect from '../skills/posts/jinsha-post/scripts/appeal_collector.mjs';

test('acquire precedes operation; original owner released exactly once', async () => {
  const events = []; const lease = { leaseId: 'owned' };
  const result = await withJinshaOperationLease(async () => { events.push('operation'); return 42; }, {
    acquire: async () => { events.push('acquire'); return lease; },
    release: async value => { assert.equal(value, lease); events.push('release'); },
  });
  assert.equal(result, 42); assert.deepEqual(events, ['acquire', 'operation', 'release']);
});

for (const busy of ['throw', 'null']) test('busy=' + busy + ' never calls operation or release', async () => {
  await assert.rejects(withJinshaOperationLease(async () => assert.fail('operation forbidden'), {
    acquire: async () => { if (busy === 'throw') throw Error('jinsha-lease-busy'); return null; },
    release: async () => assert.fail('not owner'),
  }), /lease-busy/);
});

test('operation exception still releases once; release error never retries operation', async () => {
  let releases = 0, calls = 0;
  await assert.rejects(withJinshaOperationLease(async () => { calls++; throw Error('business failed'); }, {
    acquire: async () => ({}), release: async () => releases++,
  }), /business failed/);
  assert.equal(releases, 1); assert.equal(calls, 1);
  await assert.rejects(withJinshaOperationLease(async () => { calls++; }, {
    acquire: async () => ({}), release: async () => { throw Error('release failed'); },
  }), /release failed/);
  assert.equal(calls, 2);
});

for (const [name, module] of [['meituan', meituan], ['taobao', taobao]]) {
  for (const mode of ['execute', 'inspect']) test(name + ' ' + mode + ' cannot reach CDP when busy', async () => {
    const previous = globalThis.fetch; let calls = 0;
    globalThis.fetch = async () => { calls++; assert.fail('CDP forbidden'); };
    try {
      await assert.rejects(module[mode]({ leaseGuard: async () => { throw Error('jinsha-lease-busy'); } }), /lease-busy/);
      assert.equal(calls, 0);
    } finally { globalThis.fetch = previous; }
  });
}

for (const [name, module] of [['meituan', mtCollect], ['taobao', tbCollect]]) {
  test(name + ' full collector validates then cannot reach CDP while busy', async () => {
    let guards = 0;
    const leaseGuard = async () => { guards++; throw Error('jinsha-lease-busy'); };
    assert.throws(() => module.collectAllAppeals({ businessDate: 'bad' }, { leaseGuard }), /config-invalid/);
    assert.equal(guards, 0);
    await assert.rejects(module.collectAllAppeals({ businessDate: '2026-10-27', platformValue: '1',
      channelLabel: '美团外卖', contextLabel: '美团' }, { leaseGuard }), /lease-busy/);
    assert.equal(guards, 1);
  });
}

test('original real lease excludes another process throughout operation, then permits it', async t => {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'jinsha-operation-test-'));
  t.after(() => fs.rm(dir, { recursive: true, force: true }));
  const file = path.join(dir, 'post.lock');
  const leaseUrl = new URL('../skills/posts/jinsha-post/scripts/lease.mjs', import.meta.url).href;
  const script = `import {acquireJinshaLease,releaseJinshaLease} from ${JSON.stringify(leaseUrl)};
    try { const lease=await acquireJinshaLease('child',process.argv[1]);await releaseJinshaLease(lease);console.log('acquired'); }
    catch(error){if(!error.message.startsWith('jinsha-lease-busy:'))throw error;console.log('busy');}`;
  const probe = async () => (await promisify(execFile)(process.execPath, ['--input-type=module', '-e', script, file])).stdout.trim();
  await withJinshaOperationLease(async () => {
    assert.equal(await probe(), 'busy');
    const held = JSON.parse(await fs.readFile(file, 'utf8'));
    assert.equal(held.pid, process.pid);
  }, { acquire: id => acquireJinshaLease(id, file), release: releaseJinshaLease });
  assert.equal(await probe(), 'acquired');
  await assert.rejects(fs.stat(file), error => error.code === 'ENOENT');
});
