import assert from 'node:assert/strict';
import { assertSnapshot, isCoherentStatusSnapshot, readSelectedChannel, readStableStatusSnapshot, stableReviewKey, sumCounts } from './appeal_collector.mjs';

const row = { store: '门店A', date: '2026-09-23', comment: '评价内容', score: 1, status: '申诉中' };
assert.equal(stableReviewKey(row), stableReviewKey({ ...row, score: 3 }));
assert.equal(sumCounts({ 全部: 15 }), 15);
assert.equal(assertSnapshot({ total: 1, counts: { 全部: 1 }, rows: [{ ...row, status: '全部' }] }), true);
assert.equal(assertSnapshot({ total: 1, counts: { 全部: 1, 申诉成功: 8, 申诉失败: 2, 申诉中: 3, 未申诉: 4 }, rows: [{ ...row, status: '全部' }] }), true);
assert.throws(() => assertSnapshot({ total: 2, counts: { 全部: 1 }, rows: [{ ...row, status: '全部' }] }), /total-mismatch/);
const empty = { total: 0, statusCounts: { 全部: 0 }, page: [], cards: [] };
assert.equal(isCoherentStatusSnapshot(empty, '全部'), true);
let emptyReads = 0;
assert.equal((await readStableStatusSnapshot(async () => { emptyReads++; return empty; }, '全部', { attempts: 2, intervalMs: 0, pause: async () => {} })).total, 0);
assert.equal(emptyReads, 2);
const populated = { total: 1, statusCounts: { 全部: 1 }, page: ['1'], cards: [row] };
let transientReads = 0;
assert.equal((await readStableStatusSnapshot(async () => [empty, populated, populated][transientReads++], '全部', { attempts: 3, intervalMs: 0, pause: async () => {} })).total, 1);
assert.equal(transientReads, 3);
assert.equal(isCoherentStatusSnapshot({ ...empty, total: 0, statusCounts: { 全部: 1 } }, '全部'), false);
assert.equal(isCoherentStatusSnapshot({ ...populated, cards: [] }, '全部'), false);
let changingReads = 0;
await assert.rejects(readStableStatusSnapshot(async () => ({ ...populated, total: changingReads++ % 2, statusCounts: { 全部: changingReads % 2 } }), '全部', { attempts: 3, intervalMs: 0, pause: async () => {} }), /not-stable/);
{
  // D13：点击后菜单自动收起（可见 0 项）⇒ 显式重展开一次后读回成功
  let calls = 0, expands = 0;
  const probe = async () => { calls++; return calls === 1 ? { visible: 0, pitch: [], menu: 1 } : { visible: 2, pitch: ['淘宝'], menu: 1 }; };
  const reexpand = async () => { expands++; };
  assert.equal(await readSelectedChannel(probe, reexpand, '淘宝', { attempts: 5, intervalMs: 0, pause: async () => {} }), '淘宝');
  assert.equal(expands, 1);
  // D13：菜单持续收起 ⇒ 每轮都重展开，尝试耗尽仍 fail-closed（错误字面量不变）
  let stuckExpands = 0;
  await assert.rejects(readSelectedChannel(async () => ({ visible: 0, pitch: [], menu: 1 }), async () => { stuckExpands++; }, '淘宝', { attempts: 3, intervalMs: 0, pause: async () => {} }), /channel-context-readback-mismatch/);
  assert.equal(stuckExpands, 2);
  // 选错渠道（可见但 pitchOn 非目标）⇒ 不误判成功
  await assert.rejects(readSelectedChannel(async () => ({ visible: 2, pitch: ['美团'], menu: 1 }), async () => {}, '淘宝', { attempts: 2, intervalMs: 0, pause: async () => {} }), /channel-context-readback-mismatch/);
}
console.log(JSON.stringify({ ok: true, tests: 13, runtimeModelDecisions: 0 }));
