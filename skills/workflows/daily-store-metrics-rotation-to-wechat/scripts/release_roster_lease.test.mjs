import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { releaseExitedRosterLease, validRosterRunId } from './release_roster_lease.mjs';
import { releasePostLease } from '../../../posts/taobao-brand-post/scripts/lease.mjs';

const runId = 'monthly-roster-12345678-1234-4234-8234-123456789abc';
const otherId = 'monthly-roster-12345678-1234-4234-8234-123456789abd';
async function isolated(t) {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'roster-lease-test-'));
  t.after(() => fs.rm(dir, { recursive: true, force: true }));
  const child = spawn(process.execPath, ['-e', 'process.exit(0)']);
  await once(child, 'exit');
  return { leasePath: path.join(dir, 'lease.json'), pid: child.pid };
}
const write = (p, value) => fs.writeFile(p, JSON.stringify(value));

test('only a unique valid roster UUID is accepted', () => {
  assert.equal(validRosterRunId(runId), true);
  for (const v of ['monthly-roster-old', 'other-'+runId, '', undefined]) assert.equal(validRosterRunId(v), false);
});
test('missing lease is idempotent', async t => {
  const v = await isolated(t);
  assert.equal((await releaseExitedRosterLease(runId, v.pid, v)).reason, 'lease-absent');
});
test('own reaped child lease is released using original API, ignoring stored path', async t => {
  const v = await isolated(t);
  await write(v.leasePath, { runId, pid: v.pid, acquiredAt: Date.now(), leasePath: '/never/use/stored/path' });
  assert.equal((await releaseExitedRosterLease(runId, v.pid, v)).released, true);
  await assert.rejects(fs.access(v.leasePath), { code: 'ENOENT' });
});
test('live owner is preserved regardless of old timestamp', async t => {
  const v = await isolated(t);
  const owner = { runId, pid: process.pid, acquiredAt: 1 };
  await write(v.leasePath, owner);
  await assert.rejects(releaseExitedRosterLease(runId, process.pid, v), /still-alive/);
  assert.deepEqual(JSON.parse(await fs.readFile(v.leasePath)), owner);
});
for (const mismatch of ['pid', 'runId']) test(`foreign ${mismatch} is preserved byte for byte`, async t => {
  const v = await isolated(t);
  await write(v.leasePath, { runId: mismatch === 'runId' ? otherId : runId, pid: mismatch === 'pid' ? process.pid : v.pid });
  const before = await fs.readFile(v.leasePath);
  assert.equal((await releaseExitedRosterLease(runId, v.pid, v)).reason, 'foreign-lease-preserved');
  assert.deepEqual(await fs.readFile(v.leasePath), before);
});
test('malformed lease and invalid caller cannot authorize release', async t => {
  const v = await isolated(t);
  for (const body of ['null', '{', '{"pid":0,"runId":"x"}']) {
    await fs.writeFile(v.leasePath, body);
    await assert.rejects(releaseExitedRosterLease(runId, v.pid, v), /lease-(invalid|unreadable)/);
    assert.equal(await fs.readFile(v.leasePath, 'utf8'), body);
  }
  await assert.rejects(releaseExitedRosterLease('monthly-roster-bad', v.pid, v), /identity-invalid/);
});
test('original release refuses a replacement task that acquired before release', async t => {
  const v = await isolated(t);
  await write(v.leasePath, { runId, pid: v.pid });
  const release = async lease => {
    await write(v.leasePath, { runId: otherId, pid: process.pid });
    return releasePostLease(lease);
  };
  assert.equal((await releaseExitedRosterLease(runId, v.pid, { ...v, release })).released, false);
  assert.equal(JSON.parse(await fs.readFile(v.leasePath)).runId, otherId);
});
