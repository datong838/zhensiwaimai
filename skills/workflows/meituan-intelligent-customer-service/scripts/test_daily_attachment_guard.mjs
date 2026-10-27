import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { checkDailyAttachmentAttempts } from './daily_attachment_guard.mjs';

const ledger = await fs.mkdtemp(path.join(os.tmpdir(), 'customer-attachment-'));
const group = '隔离测试完整运营群';
const date = new Date('2026-10-28T17:10:00+08:00');
const name = 'meituan-customer-reply-daily-2026-10-28-170100.json';
const payload = { state: 'unknown', sendAttempts: 1, groupName: group, payloadType: 'file',
  payloads: [{ name: '美团客户回复记录-2026-10-28.xlsx', sha256: 'a'.repeat(64) }] };
let tests = 0;
const check = at => checkDailyAttachmentAttempts({ ledger, group, date: at || date });
async function write(file = name, changes = {}) {
  await fs.writeFile(path.join(ledger, file), JSON.stringify({ ...payload, ...changes }));
}
try {
  assert.equal((await check()).ok, true); tests++;
  for (const changes of [{}, { state: 'attempted', sendAttempts: null }, { state: 'blocked', sendAttempts: null }, { state: 'blocked', sendAttempts: '0' }, { state: 'unexpected', sendAttempts: 0 }]) {
    await write(name, changes);
    const before = await fs.readFile(path.join(ledger, name));
    const result = await check();
    assert.equal(result.ok, false); assert.equal(result.newSendAttempts, 0);
    assert.deepEqual(await fs.readFile(path.join(ledger, name)), before); tests++;
  }
  for (const changes of [{ state: 'blocked', sendAttempts: 0 }, { state: 'verified', sendAttempts: 1 }]) {
    await write(name, changes); assert.equal((await check()).ok, true); tests++;
  }
  for (const changes of [{ groupName: '错误群' }, { payloadType: 'image' }, { payloads: [] }, { payloads: [{ name: '旧文件.xlsx' }] }]) {
    await write(name, changes); assert.equal((await check()).ok, false); tests++;
  }
  await fs.writeFile(path.join(ledger, name), '{');
  assert.equal((await check()).ok, false); tests++;
  await fs.rm(path.join(ledger, name));
  await write('meituan-customer-reply-daily-2026-10-28-120100.json');
  assert.equal((await check()).ok, true); tests++;
  assert.equal((await check(new Date('2026-10-28T12:30:00+08:00'))).ok, false); tests++;
  await write('meituan-customer-reply-daily-2026-10-27-170100.json');
  assert.equal((await check()).ok, true); tests++;
  await write('meituan-customer-reply-daily-2026-10-28.json');
  assert.equal((await check()).ok, false); tests++;
  await fs.rm(path.join(ledger, 'meituan-customer-reply-daily-2026-10-28.json'));
  await fs.writeFile(path.join(ledger, 'outside.json'), JSON.stringify(payload));
  await fs.symlink(path.join(ledger, 'outside.json'), path.join(ledger, name));
  assert.equal((await check()).ok, false); tests++;
  const source = await fs.readFile(new URL('./send_daily_reply_xlsx_to_wechat.mjs', import.meta.url), 'utf8');
  assert.ok(source.indexOf('await checkDailyAttachmentAttempts(') < source.indexOf('await run(python, args()'));
  assert.ok(source.includes('if (!attemptGuard.ok)')); tests++;
  console.log(JSON.stringify({ ok: true, tests, sendAttempts: 0, productionWrites: 0 }));
} finally { await fs.rm(ledger, { recursive: true, force: true }); }
