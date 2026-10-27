import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { eligibleDays, parseTotal, loadKnownAnnouncements, recordAnnouncementHit, duplicateHits } from '../scripts/collector.mjs';

test('only stores opened within three days qualify', () => {
  for (const day of [0, 1, 2, 3]) assert.equal(eligibleDays(`${day}天`), day);
  for (const value of ['4天', '24天', '1年2天', '', '未知', '3天前'])
    assert.equal(eligibleDays(value), null);
});

test('pagination total must be explicit', () => {
  assert.equal(parseTotal('共 629 条'), 629);
  assert.equal(parseTotal('共 0 条'), 0);
  assert.throws(() => parseTotal('629'), /pagination-total-invalid/);
});

// ---- P0-2 公告白名单外置（2026-10-03）----

function withConfig(body) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ann-'));
  const cfgPath = path.join(dir, 'known-announcements.json');
  if (body !== undefined) fs.writeFileSync(cfgPath, typeof body === 'string' ? body : JSON.stringify(body));
  return cfgPath;
}

test('loadKnownAnnouncements: 外置等价 / 兜底 / 非法回退', () => {
  // 与内置等价的合法配置
  assert.deepEqual(loadKnownAnnouncements(withConfig({ items: ['新功能上线', 'AI运营智能体上线'] })),
    ['新功能上线', 'AI运营智能体上线']);
  // 新增条目生效
  assert.deepEqual(loadKnownAnnouncements(withConfig({ items: ['新功能上线', 'V5.7新版公告'] })),
    ['新功能上线', 'V5.7新版公告']);
  // 文件不存在 → 静默回退内置
  assert.deepEqual(loadKnownAnnouncements(path.join(os.tmpdir(), 'no-such-ann.json')),
    ['新功能上线', 'AI运营智能体上线']);
  // JSON 非法 → 回退内置
  assert.deepEqual(loadKnownAnnouncements(withConfig('not-json{')), ['新功能上线', 'AI运营智能体上线']);
  // items 非数组/为空/含非字符串 → 回退内置
  assert.deepEqual(loadKnownAnnouncements(withConfig({ items: 'bad' })), ['新功能上线', 'AI运营智能体上线']);
  assert.deepEqual(loadKnownAnnouncements(withConfig({ items: [] })), ['新功能上线', 'AI运营智能体上线']);
  assert.deepEqual(loadKnownAnnouncements(withConfig({ items: ['ok', 42, null] })), ['ok']);
});

test('recordAnnouncementHit: 命中计数原子更新且不改 items', () => {
  const cfgPath = withConfig({ items: ['新功能上线'], hits: {} });
  recordAnnouncementHit('新功能上线', cfgPath, '2026-10-03T23:00:00+08:00');
  recordAnnouncementHit('新功能上线', cfgPath, '2026-10-03T23:10:00+08:00');
  const raw = JSON.parse(fs.readFileSync(cfgPath, 'utf8'));
  assert.equal(raw.hits['新功能上线'].hits, 2);
  assert.equal(raw.hits['新功能上线'].firstHitAt, '2026-10-03T23:00:00+08:00');
  assert.equal(raw.hits['新功能上线'].lastHitAt, '2026-10-03T23:10:00+08:00');
  assert.deepEqual(raw.items, ['新功能上线']); // 白名单本体绝不被记账改动
  // 无残留 tmp 文件
  assert.equal(fs.existsSync(`${cfgPath}.tmp`), false);
});

test('recordAnnouncementHit: 配置异常时不抛出、不写坏文件', () => {
  const cfgPath = withConfig('not-json{');
  assert.doesNotThrow(() => recordAnnouncementHit('x', cfgPath));
  assert.equal(fs.readFileSync(cfgPath, 'utf8'), 'not-json{'); // 原文件未被破坏
  // items 缺失 → 拒绝记账
  const cfgPath2 = withConfig({ hits: {} });
  assert.doesNotThrow(() => recordAnnouncementHit('x', cfgPath2));
  assert.deepEqual(JSON.parse(fs.readFileSync(cfgPath2, 'utf8')).hits, {});
});

test('duplicate evidence preserves both physical rows without treating another channel as a duplicate',()=>{
  const first={channel:'淘宝',name:'同名店',days:'1天',page:1,row:3};
  const second={...first,page:2,row:4};
  const other={...first,channel:'美团'};
  assert.deepEqual(duplicateHits([first,other]),[]);
  assert.deepEqual(duplicateHits([first,second,other]),[first,second]);
});
