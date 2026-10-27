#!/usr/bin/env node
// Read only collection from the dedicated, already running Jinsha Chrome.
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const { chromium } = require('/Users/ddt/work/projects/ai_agent/aos-platform/plugins/browser/isolated-persistent-playwright/node_modules/playwright-core');
// 2026-09-30 S2b 金鲨岗转正：采集前必须持有金鲨工位租约（posts/jinsha-post），
// 与 jinsha 日报/差评分析共用同一把锁（/tmp/zhensi-jinsha-cua-exam.lock）⇒ 工位互斥。
// busy 时本轮 blocked，daemon 下轮重试；锁 TTL 30min 自愈。
import { acquireJinshaLease, releaseJinshaLease } from '../../../posts/jinsha-post/scripts/lease.mjs';
const ORIGIN = 'https://data.guoshuyufen.com';
const REALTIME_URL = `${ORIGIN}/#/businessData/realTimeData`;
const PORT = 'http://127.0.0.1:9232';
const MAX_PAGES = 100;

export function eligibleDays(value) {
  const match = /^\s*([0-3])\s*天\s*$/.exec(value || '');
  return match ? Number(match[1]) : null;
}

export function parseTotal(value) {
  const match = /^共\s*(\d+)\s*条$/.exec((value || '').trim());
  if (!match) throw new Error('pagination-total-invalid');
  return Number(match[1]);
}

async function state(page) {
  return page.evaluate(() => {
    const rows = [...document.querySelectorAll('.el-table__body tbody tr.el-table__row')];
    const activeTab = [...document.querySelectorAll('.cutli')]
      .find(e => ['美团', '淘宝'].includes(e.innerText.trim()) && e.classList.contains('pitchOn'))?.innerText.trim();
    const firstStore = rows[0]?.querySelectorAll('td')[1]?.innerText || '';
    const selected = activeTab || (firstStore.includes('淘宝闪购预算') ? '淘宝' :
      firstStore.includes('美团预算') ? '美团' : undefined);
    const group = [...document.querySelectorAll('.overviewTLi .el-checkbox-group')]
      .find(e => e.previousElementSibling?.innerText.trim() === '新店');
    return {
      selected,
      newStoreChecked: group ? !!group.querySelector('label.is-checked') : null,
      size: document.querySelector('.el-pagination__sizes input')?.value || '',
      totalText: document.querySelector('.el-pagination__total')?.innerText || '',
      activePage: Number(document.querySelector('.el-pager li.active')?.innerText || 1),
      rowCount: rows.length,
      first: rows[0]?.querySelectorAll('td')[1]?.innerText.split('\n')[0].trim() || '',
      last: rows.at(-1)?.querySelectorAll('td')[1]?.innerText.split('\n')[0].trim() || '',
      nextDisabled: !!document.querySelector('.el-pagination .btn-next')?.disabled,
    };
  });
}

async function readRows(page) {
  return page.evaluate(() => [...document.querySelectorAll('.el-table__body tbody tr.el-table__row')].map((row, index) => {
    const cells = row.querySelectorAll('td');
    const name = (cells[1]?.innerText || '').split('\n')[0].trim();
    const avatar = cells[2]?.innerText || '';
    const days = avatar.match(/开业天数[:：]\s*([^\n]+)/)?.[1]?.trim() || '';
    // 暂停营业（suspended）店铺不渲染开业天数，属确定性非新店：不应计入
    // 「开业天数缺失/待核对」，也不应阻断发送；单独标记便于报告透明展示。
    const suspended = !days && avatar.includes('暂停营业');
    const identityHints=[];
    const label=/(?:门店|店铺|商户)(?:ID|id|编号)[:：]\s*([0-9]{4,20})/g;
    for(const hit of (row.innerText||'').matchAll(label)) identityHints.push({source:'visible-id-label',value:hit[1]});
    for(const node of [row,...row.querySelectorAll('[data-shop-id],[data-store-id],[data-merchant-id]')]) {
      for(const attr of ['data-shop-id','data-store-id','data-merchant-id']) {
        const value=node.getAttribute(attr);
        if(value && /^[0-9]{4,20}$/.test(value)) identityHints.push({source:attr,value});
      }
    }
    return { row: index + 1, name, days, suspended, identityHints };
  }));
}

// 2026-09-30 金鲨 UI 改版：渠道切换 tab（美团/淘宝/京东）移入侧边栏容器
// （sidebar-container > cut），侧边栏收起时 .cutli 整体不在 DOM。采集前先
// 确保侧边栏展开：仅在 tab 缺失时点击汉堡按钮，落点由后续
// switchChannel 的 count!==1 闸门兜底，展开失败即 blocked。
// 实测（2026-09-30 21:18）：点击目标必须是 svg.hamburger（其外层
// hamburger-container 为 0 尺寸容器，点击无效）；父级容器在两种布局间
// 切换（.navbar 有无），故不绑定父级，按全局唯一性匹配。
async function ensureChannelTabsVisible(page) {
  await page.waitForFunction(() => !!document.querySelector('.app-wrapper'), null, { timeout: 30000 });
  await page.evaluate(() => window.scrollTo(0, 0));
  const present = await page.evaluate(() => document.querySelectorAll('.cutli').length > 0);
  if (present) return;
  const toggle = page.locator('.hamburger');
  if (await toggle.count() !== 1) throw new Error('sidebar-toggle-not-unique');
  await toggle.click();
  await page.waitForFunction(() => document.querySelectorAll('.cutli').length > 0, null, { timeout: 30000 });
}

async function switchChannel(page, name) {
  const before = await state(page);
  const target = page.locator('.cutli').filter({ hasText: new RegExp(`^\\s*${name}\\s*$`) });
  if (await target.count() !== 1) throw new Error(`channel-not-unique:${name}`);
  await target.click();
  await page.waitForFunction(([expected, previousChannel, previousFirst, previousTotal]) => {
    const item = [...document.querySelectorAll('.cutli')].find(e => e.innerText.trim() === expected);
    const first = document.querySelector('.el-table__body tbody tr.el-table__row td:nth-child(2)')?.innerText.split('\n')[0].trim();
    const total = document.querySelector('.el-pagination__total')?.innerText;
    return item?.classList.contains('pitchOn') && document.body.innerText.includes('今日实时数据') &&
      first && (previousChannel === expected || first !== previousFirst || total !== previousTotal);
  }, [name, before.selected, before.first, before.totalText], { timeout: 30000 });
  // The expanded sidebar can leave a drawer backdrop over the realtime controls.
  // Click that visible backdrop (the UI's normal outside-dismiss gesture) once;
  // the selected platform is then verified from its visible budget label.
  const backdrop = page.locator('.drawer-bg');
  const backdrops = await backdrop.count();
  if (backdrops > 1) throw new Error('sidebar-backdrop-not-unique');
  if (backdrops === 1 && await backdrop.isVisible()) {
    await backdrop.click();
    await page.waitForFunction(() => ![...document.querySelectorAll('.drawer-bg')]
      .some(e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length)), null, { timeout: 10000 });
  }
  await page.waitForFunction(expected => {
    const first = document.querySelector('.el-table__body tbody tr.el-table__row td:nth-child(2)')?.innerText || '';
    return expected === '淘宝' ? first.includes('淘宝闪购预算') : first.includes('美团预算');
  }, name, { timeout: 10000 });
}

async function selectMeituanNewStore(page) {
  await page.waitForFunction(() => [...document.querySelectorAll('.overviewTLi .el-checkbox-group')]
    .some(e => e.previousElementSibling?.innerText.trim() === '新店'), { timeout: 30000 });
  // Resolve against the visible DOM order; the label follows the text "新店".
  const groups = page.locator('.overviewTLi .el-checkbox-group');
  const matches = await page.evaluate(() => [...document.querySelectorAll('.overviewTLi .el-checkbox-group')]
    .map((e, i) => e.previousElementSibling?.innerText.trim() === '新店' ? i : -1).filter(i => i >= 0));
  if (matches.length !== 1) throw new Error('new-store-control-ambiguous');
  const index = matches[0];
  const selected = groups.nth(index).locator('label');
  if (!(await selected.getAttribute('class'))?.includes('is-checked')) {
    const before = (await state(page)).totalText;
    await selected.click();
    await page.waitForFunction(previous =>
      document.querySelector('.el-pagination__total')?.innerText !== previous,
      before, { timeout: 30000 });
  }
  await page.waitForFunction(() => {
    const group = [...document.querySelectorAll('.overviewTLi .el-checkbox-group')]
      .find(e => e.previousElementSibling?.innerText.trim() === '新店');
    return group?.querySelector('label')?.classList.contains('is-checked');
  }, { timeout: 30000 });
}

async function selectTaobao50(page) {
  await page.locator('.el-pagination__sizes .el-input__inner').click();
  const option = page.locator('.el-select-dropdown__item').filter({ hasText: /^50条\/页$/ });
  if (await option.count() !== 1) throw new Error('page-size-50-not-unique');
  await option.click();
  await page.waitForFunction(() => document.querySelector('.el-pagination__sizes input')?.value === '50条/页',
    { timeout: 30000 });
}

async function firstPage(page, expectedRows) {
  const before = await state(page);
  if (before.activePage !== 1) {
    const first = page.locator('.el-pager li.number').filter({ hasText: /^1$/ });
    if (await first.count() !== 1) throw new Error('first-page-control-not-unique');
    await first.click();
  }
  await page.waitForFunction(([count, previous]) => {
    const rows = [...document.querySelectorAll('.el-table__body tbody tr.el-table__row')];
    const first = rows[0]?.querySelectorAll('td')[1]?.innerText.split('\n')[0].trim() || '';
    const active = Number(document.querySelector('.el-pager li.active')?.innerText || 1);
    return active === 1 && rows.length === count && (!previous || first !== previous);
  }, [expectedRows, before.activePage === 1 ? '' : before.first], { timeout: 30000 });
}

async function scanPass(page, channel) {
  const initial = await state(page);
  if (initial.selected !== channel) throw new Error(`wrong-channel:${channel}`);
  if (channel === '美团' && initial.newStoreChecked !== true) throw new Error('meituan-new-store-unchecked');
  if (channel === '淘宝' && initial.size !== '50条/页') throw new Error('taobao-page-size-not-50');
  const total = parseTotal(initial.totalText);
  const size = Number.parseInt(initial.size, 10);
  if (!Number.isInteger(size) || size < 1 || size > 200) throw new Error('page-size-invalid');
  const pages = Math.ceil(total / size);
  if (pages > MAX_PAGES) throw new Error('page-count-limit');
  const visited = [];
  if (!pages) {
    if (initial.rowCount !== 0) throw new Error('zero-total-has-rows');
    return { channel, total, size, pages: 0, visited, hits: [], unresolved: [] };
  }
  await firstPage(page, Math.min(size, total));
  for (let number = 1; number <= pages; number++) {
    if (number > 1) {
      const prior = visited.at(-1);
      await page.locator('.el-pagination .btn-next').click();
      const expected = Math.min(size, total - (number - 1) * size);
      await page.waitForFunction(([want, count, oldFirst, oldLast]) => {
        const rows = [...document.querySelectorAll('.el-table__body tbody tr.el-table__row')];
        const first = rows[0]?.querySelectorAll('td')[1]?.innerText.split('\n')[0].trim() || '';
        const last = rows.at(-1)?.querySelectorAll('td')[1]?.innerText.split('\n')[0].trim() || '';
        return Number(document.querySelector('.el-pager li.active')?.innerText) === want &&
          rows.length === count && (first !== oldFirst || last !== oldLast);
      }, [number, expected, prior.first, prior.last], { timeout: 30000 });
    }
    const current = await state(page);
    const rows = await readRows(page);
    const expected = Math.min(size, total - (number - 1) * size);
    if (current.selected !== channel || (channel === '美团' && current.newStoreChecked !== true) ||
        current.activePage !== number || parseTotal(current.totalText) !== total || rows.length !== expected ||
        rows.some(r => !r.name)) throw new Error(`page-incomplete:${channel}:${number}`);
    const hits = rows.filter(r => eligibleDays(r.days) !== null)
      .map(r => ({ channel, name: r.name, days: r.days, page: number, row: r.row, identityHints:r.identityHints }));
    const unresolved = rows.filter(r => !r.days && !r.suspended)
      .map(r => ({ channel, name: r.name, days: r.days, page: number, row: r.row, identityHints:r.identityHints }));
    const suspendedRows = rows.filter(r => r.suspended)
      .map(r => ({ channel, name: r.name, page: number, row: r.row }));
    visited.push({ page: number, count: rows.length, first: rows[0].name, last: rows.at(-1).name, hits, unresolved, suspendedRows });
  }
  if (!(await state(page)).nextDisabled) throw new Error('last-page-not-confirmed');
  return { channel, total, size, pages, visited,
    hits: visited.flatMap(v => v.hits), unresolved: visited.flatMap(v => v.unresolved),
    suspended: visited.flatMap(v => v.suspendedRows) };
}

function hitIdentity(hit) { return `${hit.channel}\u0000${hit.name}\u0000${hit.days}`; }
export function duplicateHits(hits) {
  const counts=new Map();for(const hit of hits) counts.set(hitIdentity(hit),(counts.get(hitIdentity(hit))||0)+1);
  return hits.filter(hit=>counts.get(hitIdentity(hit))>1);
}
function hitSet(pass) { return [...new Set(pass.hits.map(hitIdentity))].sort(); }
function unresolvedSet(pass) {
  return [...new Set((pass.unresolved || []).map(row => `${row.channel}\u0000${row.name}`))].sort();
}

// 公告弹窗白名单：站点不定期推送新版公告（2026-09-30 21:50 实测推送 V5.6
// 「AI运营智能体上线」，文案与首版「新功能上线」不同），同属 .upload 公告
// 结构。命中白名单即按页面正常手势点 .close 关闭；白名单外的遮罩一律
// unknown-page-overlay 熔断，避免误点未知弹层。新公告出现时先用只读探针
// 确认内容再入名单。
// P0-2 外置（2026-10-03）：白名单读 config/known-announcements.json（items），
// 读取失败/为空/字段非法一律回退内置默认，行为与外置前等价；配置文件缺省
// （ENOENT）静默回退。命中记账只更新 hits 计数，绝不改写 items。
const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const ANNOUNCEMENT_CONFIG_PATH = path.join(SCRIPT_DIR, '..', 'config', 'known-announcements.json');
const DEFAULT_KNOWN_ANNOUNCEMENTS = ['新功能上线', 'AI运营智能体上线'];

export function loadKnownAnnouncements(cfgPath = ANNOUNCEMENT_CONFIG_PATH) {
  try {
    const raw = JSON.parse(fs.readFileSync(cfgPath, 'utf8'));
    const items = Array.isArray(raw?.items)
      ? raw.items.filter(item => typeof item === 'string' && item.length > 0)
      : [];
    return items.length > 0 ? items : [...DEFAULT_KNOWN_ANNOUNCEMENTS];
  } catch (err) {
    if (err?.code !== 'ENOENT') {
      console.warn(`[collector] known-announcements 配置无效，回退内置白名单: ${err?.message}`);
    }
    return [...DEFAULT_KNOWN_ANNOUNCEMENTS];
  }
}

let _knownAnnouncements = null;
function knownAnnouncements() {
  if (!_knownAnnouncements) _knownAnnouncements = loadKnownAnnouncements();
  return _knownAnnouncements;
}

// 命中记账：原子更新 hits[marker]（hits 计数 + firstHitAt/lastHitAt），
// 任何异常都只告警不抛出——记账失败绝不能影响采集主链路。
export function recordAnnouncementHit(marker, cfgPath = ANNOUNCEMENT_CONFIG_PATH, now = new Date().toISOString()) {
  try {
    const raw = JSON.parse(fs.readFileSync(cfgPath, 'utf8'));
    if (!raw || typeof raw !== 'object' || !Array.isArray(raw.items)) return;
    const hits = (raw.hits && typeof raw.hits === 'object' && !Array.isArray(raw.hits)) ? { ...raw.hits } : {};
    const entry = (hits[marker] && typeof hits[marker] === 'object' && !Array.isArray(hits[marker])) ? { ...hits[marker] } : {};
    entry.hits = (Number.isInteger(entry.hits) ? entry.hits : 0) + 1;
    if (!entry.firstHitAt) entry.firstHitAt = now;
    entry.lastHitAt = now;
    hits[marker] = entry;
    raw.hits = hits;
    const tmp = `${cfgPath}.tmp`;
    fs.writeFileSync(tmp, JSON.stringify(raw, null, 2) + '\n');
    fs.renameSync(tmp, cfgPath);
  } catch (err) {
    console.warn(`[collector] 公告命中记账失败（不影响主流程）: ${err?.message}`);
  }
}

async function dismissAnnouncement(page) {
  const announcement = page.locator('.upload .content');
  if (await announcement.count() === 1 && await announcement.isVisible()) {
    const text = await announcement.innerText();
    const matched = knownAnnouncements().find(marker => text.includes(marker));
    if (!matched) throw new Error('unknown-page-overlay');
    const close = announcement.locator('.close');
    if (await close.count() !== 1) throw new Error('announcement-close-not-unique');
    await close.click();
    await page.waitForFunction(() => !document.querySelector('.upload') ||
      getComputedStyle(document.querySelector('.upload')).display === 'none', null, { timeout: 10000 });
    recordAnnouncementHit(matched);
  }
}

async function collect(page) {
  await ensureChannelTabsVisible(page);
  await switchChannel(page, '美团');
  await selectMeituanNewStore(page);
  await page.waitForFunction(() => {
    const group = [...document.querySelectorAll('.overviewTLi .el-checkbox-group')]
      .find(e => e.previousElementSibling?.innerText.trim() === '新店');
    return group?.querySelector('label.is-checked') && document.querySelector('.el-pagination__total')?.innerText;
  }, { timeout: 30000 });
  const meituan = await scanPass(page, '美团');
  await switchChannel(page, '淘宝');
  await selectTaobao50(page);
  const passes = [];
  for (let attempt = 1; attempt <= 3; attempt++) {
    const pass = await scanPass(page, '淘宝');
    passes.push(pass);
    if (passes.length >= 2) {
      const previous = passes.at(-2);
      if (previous.total === pass.total && JSON.stringify(hitSet(previous)) === JSON.stringify(hitSet(pass)) &&
          JSON.stringify(unresolvedSet(previous)) === JSON.stringify(unresolvedSet(pass))) break;
    }
  }
  if (passes.length < 2 || passes.at(-2).total !== passes.at(-1).total ||
      JSON.stringify(hitSet(passes.at(-2))) !== JSON.stringify(hitSet(passes.at(-1))) ||
      JSON.stringify(unresolvedSet(passes.at(-2))) !== JSON.stringify(unresolvedSet(passes.at(-1))))
    throw new Error('taobao-real-time-unstable');
  const taobao = passes.at(-1);
  const hits = [...meituan.hits, ...taobao.hits];
  if (new Set(hits.map(hitIdentity)).size !== hits.length) {
    const error=new Error('duplicate-hit-identity');
    error.evidence={duplicateHits:duplicateHits(hits),
      meituan:{total:meituan.total,pages:meituan.pages},taobao:{total:taobao.total,pages:taobao.pages},
      taobaoPasses:passes.map(pass=>({total:pass.total,pages:pass.pages,hits:pass.hits}))};
    throw error;
  }
  const unresolved = [...(meituan.unresolved || []), ...(taobao.unresolved || [])];
  const suspended = [...(meituan.suspended || []), ...(taobao.suspended || [])];
  return { meituan, taobao,
    taobaoPasses: passes.map(p => ({ total: p.total, pages: p.pages, hits: p.hits, unresolved: p.unresolved || [] })),
    hits, unresolved, suspended };
}

async function main() {
  const output = process.argv[2];
  if (!output || !path.isAbsolute(output)) throw new Error('absolute-output-path-required');
  const started = Date.now();
  let browser;
  let page;
  let receipt;
  let lease;
  try {
    lease = await acquireJinshaLease(`new-stores-${started}`);
    browser = await chromium.connectOverCDP(PORT);
    const contexts = browser.contexts();
    if (contexts.length !== 1) throw new Error('cdp-context-not-unique');
    const realtimeTabs = contexts[0].pages().filter(candidate => candidate.url() === REALTIME_URL);
    const jinshaTabs = contexts[0].pages().filter(candidate => candidate.url().startsWith(`${ORIGIN}/`));
    if (realtimeTabs.length > 1 || (!realtimeTabs.length && jinshaTabs.length !== 1))
      throw new Error(`jinsha-tab-ambiguous:${jinshaTabs.length}`);
    page = realtimeTabs[0] || jinshaTabs[0];
    if (!page) throw new Error('jinsha-tab-missing');
    await dismissAnnouncement(page);
    if (page.url() !== REALTIME_URL) {
      const menu = page.getByText('实时数据', { exact: true });
      if (await menu.count() !== 1) throw new Error('realtime-menu-ambiguous');
      if (await menu.first().isVisible()) {
        await menu.first().click();
      } else {
        // 2026-09-29：左侧菜单折叠时该 span 存在于 DOM 但不可见，直接 click 会
        // 稳定 30s 超时（locator.click: element is not visible）。同一 SPA 内的
        // 等价导航：切 hash 到同一路由，落点仍由下方 waitForFunction 严格校验
        // （origin + hash + 「今日实时数据」正文三者齐备），失败即 blocked。
        await page.evaluate(() => { location.hash = '#/businessData/realTimeData'; });
      }
    }
    await page.waitForFunction(() => location.origin === 'https://data.guoshuyufen.com' &&
      location.hash === '#/businessData/realTimeData' && document.body.innerText.includes('今日实时数据'),
      { timeout: 30000 });
    await dismissAnnouncement(page);
    receipt = { status: 'complete', checkedAt: new Date().toISOString(), leaseRunId: lease?.runId, ...await collect(page) };
  } catch (error) {
    receipt = { status: 'blocked', checkedAt: new Date().toISOString(), reason: String(error?.message || error), ...(error.evidence ? {diagnosticEvidence:error.evidence} : {}) };
  } finally {
    // 金鲨工位租约必须归还；释放失败不覆盖 receipt 原始 reason（原因为主，锁由 TTL 30min 自愈兜底）。
    if (lease) {
      try { await releaseJinshaLease(lease); receipt.leaseReleased = true; }
      catch (releaseError) { receipt.leaseReleased = false; receipt.leaseReleaseError = String(releaseError?.message || releaseError); }
    }
    receipt.elapsedMs = Date.now() - started;
    // The selected tab is user-owned. Never close it or the shared Chrome.
    fs.mkdirSync(path.dirname(output), { recursive: true });
    const temporary = `${output}.${process.pid}.tmp`;
    fs.writeFileSync(temporary, JSON.stringify(receipt, null, 2));
    fs.renameSync(temporary, output);
    fs.writeSync(process.stdout.fd, JSON.stringify({ status: receipt.status, receiptPath: output,
      hits: receipt.hits?.length ?? 0, reason: receipt.reason, elapsedMs: receipt.elapsedMs }) + '\n');
  }
  if (receipt.status !== 'complete') process.exitCode = 1;
}

if (process.argv[1] && path.resolve(process.argv[1]) === new URL(import.meta.url).pathname)
  main().then(() => process.exit(process.exitCode || 0), error => {
    process.stderr.write(`${error}\n`);
    process.exit(1);
  });
