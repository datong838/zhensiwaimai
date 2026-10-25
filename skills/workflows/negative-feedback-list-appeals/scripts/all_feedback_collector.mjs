// 负反馈列表 · 全量采集（Excel 明细的唯一事实源）
//
// 双模式（与 page_state 一致）：
//   • status  （美团）：先落未申诉页做导航门禁，再切「全部」状态分页全量；头部五维计数取 .status-btn。
//   • category（淘宝）：openFilteredPage 已落在「全部」分类视图，直接分页全量；
//                      头部维度计数取 .nav_li（全部 / 食品安全负反馈率 / 服务负反馈率）。
//
// 门禁：分页读到的行数必须等于页面「共 N 条」，否则 fail-closed 拒绝生成。
import {
  ALL_STATUS, PLATFORMS, assertJinshaEntry, clean, entryProbe, navigate, recentRange, sleep,
  stableRecordKey, HOME,
} from './jinsha.mjs';
import { openFilteredPage, readState } from './page_state.mjs';

export const snapshotSignature = state => JSON.stringify({
  total: state.totalNumber,
  page: state.pageActive,
  cards: state.cards.map(c => ({ store: c.store, date: c.date, orderNo: c.orderNo, category: c.category, preAppeal: c.preAppeal })),
});

/** 单状态/分类页快照必须自洽：total == 声明总数，且非零必须有卡片。 */
export function isCoherentSnapshot(state) {
  return Number.isInteger(state.totalNumber) && state.totalNumber >= 0
    && (state.totalNumber === 0 ? state.cards.length === 0 : state.cards.length > 0 && state.cards.length <= state.totalNumber);
}

/** 切到指定状态 tab 并等稳定（仅 status 模式，美团用）。 */
export async function selectStatusStable(cdp, gate, status, { attempts = 20, intervalMs = 400, pause = sleep } = {}) {
  await cdp.eval(`(()=>{const t=[...document.querySelectorAll('.status-btn')].filter(x=>x.offsetParent!==null&&x.innerText.trim().startsWith(${JSON.stringify(status)}));if(t.length!==1)throw Error('status-tab-count:'+t.length);t[0].click();return true})()`);
  let previous = null, last = null, lastCause = null;
  for (let attempt = 0; attempt < attempts; attempt++) {
    await pause(intervalMs);
    try {
      const state = await readState(cdp);
      if (state.status !== status || !isCoherentSnapshot(state)) {
        previous = null; lastCause = Error(`snapshot-not-coherent:${status}`); continue;
      }
      const signature = snapshotSignature(state);
      if (signature === previous) return state;
      previous = signature; lastCause = null;
    } catch (error) { previous = null; lastCause = error; }
  }
  throw Error(`feedback-status-not-stable:${status}` + (lastCause ? ` (cause: ${lastCause.message})` : ''));
}

export async function nextPage(cdp, gate, previousPage, previousFirstKey, { pause = sleep, read = readState } = {}) {
  await cdp.eval(`(()=>{const n=[...document.querySelectorAll('.el-pagination .btn-next')].filter(x=>x.offsetParent!==null);if(n.length!==1||n[0].classList.contains('disabled')||n[0].getAttribute('disabled')!==null)throw Error('pagination-next-unavailable');n[0].click();return true})()`);
  for (let attempt = 0; attempt < 20; attempt++) {
    await pause(400);
    const state = await read(cdp);
    const page = state.pageActive;
    if (page !== previousPage + 1 || state.cards.length === 0) continue;
    // 页码前进不够——内容必须真的换页（防「页码动了、列表还是旧页」的渲染竞态）：
    const firstKey = stableRecordKey({ platform: gate.platformKey, store: state.cards[0].store, date: state.cards[0].date, orderNo: state.cards[0].orderNo, category: state.cards[0].category });
    if (firstKey === previousFirstKey) continue;
    return { state, firstKey };
  }
  throw Error(`pagination-next-readback-mismatch:${gate.platformKey}:${previousPage}`);
}

/** 对当前已筛选视图分页全量采集（不依赖具体维度，status / category 通用）。
 *  行采集=物理行（与平台「共 N 条」一致；淘宝列表实测含完全重复条目，按平台口径如实入表）。
 *  防竞态靠 nextPage 的「页码前进且首页卡片必须变化」双条件，重复渲染不会被采入。 */
async function collectCurrentPages(cdp, gate) {
  let state = await readState(cdp);
  const total = state.totalNumber, rows = [], seen = new Set();
  while (true) {
    const page = state.pageActive || (total === 0 ? 1 : 0);
    if (!page || seen.has(page)) {
      throw Error(`pagination-state-invalid:${gate.platformKey}:${page}:${rows.length}:${state.cards.length}:${total}`);
    }
    seen.add(page);
    rows.push(...state.cards.map(c => ({
      ...c, status: ALL_STATUS,
      key: stableRecordKey({ platform: gate.platformKey, store: c.store, date: c.date, orderNo: c.orderNo, category: c.category }),
    })));
    if (rows.length === total) return { rows, total };
    const hasNext = await cdp.eval(`(()=>{const n=[...document.querySelectorAll('.el-pagination .btn-next')].filter(x=>x.offsetParent!==null);return n.length===1&&!n[0].classList.contains('disabled')&&n[0].getAttribute('disabled')===null})()`);
    if (!hasNext) {
      if (rows.length !== total) {
        throw Error(`pagination-total-mismatch:${gate.platformKey}:rows=${rows.length}:total=${total}`);
      }
      return { rows, total };
    }
    const card = state.cards[0];
    const firstKey = card ? stableRecordKey({ platform: gate.platformKey, store: card.store, date: card.date, orderNo: card.orderNo, category: card.category }) : null;
    const next = await nextPage(cdp, gate, page, firstKey);
    state = next.state;
  }
}

export function assertSnapshot(snapshot) {
  if (!snapshot || !Array.isArray(snapshot.rows) || !snapshot.counts) throw Error('feedback-snapshot-invalid');
  if (snapshot.rows.length !== Number(snapshot.counts.全部)) {
    throw Error(`feedback-snapshot-row-count-mismatch:${snapshot.rows.length}:${snapshot.counts.全部}`);
  }
  if (snapshot.total !== snapshot.rows.length) throw Error(`feedback-snapshot-total-mismatch:${snapshot.rows.length}:${snapshot.total}`);
  if (snapshot.rows.some(r => !r.store || !r.date || !r.orderNo)) {
    throw Error('feedback-snapshot-required-field-missing');
  }
  // 明细行状态必须统一为「全部」（两平台采集时均打此标），防止混入其他状态页导致口径错乱
  if (snapshot.rows.some(r => r.status !== ALL_STATUS)) {
    throw Error('feedback-snapshot-status-must-be-all');
  }
  return true;
}

/** 采集单平台全量 + 维度计数。 */
export async function collectPlatform(cdp, platformKey, window = recentRange()) {
  const spec = PLATFORMS.find(p => p.key === platformKey);
  if (!spec) throw Error(`platform-key-invalid:${platformKey}`);

  if (spec.mode === 'status') {
    // 先落未申诉页完成导航门禁，再切「全部」全量
    await openFilteredPage(cdp, { platformKey, status: '未申诉', window });
    const gate = { platformKey, status: ALL_STATUS, window };
    await selectStatusStable(cdp, gate, ALL_STATUS);
    const { rows, total } = await collectCurrentPages(cdp, gate);
    const state = await readState(cdp);
    const counts = { 全部: rows.length };
    for (const key of ['未申诉', '申诉中', '申诉成功', '申诉失败']) counts[key] = Number(state.statusCounts?.[key] ?? 0);
    const snapshot = {
      platformKey, platformLabel: spec.label, businessWindow: window, counts, total, rows,
      collectedAt: new Date().toISOString(), runtimeModelDecisions: 0,
    };
    assertSnapshot(snapshot);
    return snapshot;
  }

  // category 模式（淘宝）：openFilteredPage 已落在「全部」分类视图
  const gate = { platformKey, status: undefined, window };
  const landed = await openFilteredPage(cdp, { platformKey, window });
  const categoryCounts = landed.categoryCounts || {};
  const { rows, total } = await collectCurrentPages(cdp, gate);
  const counts = { 全部: rows.length };
  for (const key of ['食品安全负反馈率', '服务负反馈率']) counts[key] = Number(categoryCounts?.[key] ?? 0);
  const snapshot = {
    platformKey, platformLabel: spec.label, businessWindow: window, counts, categoryCounts, total, rows,
    collectedAt: new Date().toISOString(), runtimeModelDecisions: 0,
  };
  assertSnapshot(snapshot);
  return snapshot;
}

/** 双平台采集。任一平台失败即整体失败（fail-closed，不做部分汇总）。 */
export async function collectAll({ platforms = PLATFORMS.map(p => p.key), window } = {}) {
  const win = window || recentRange();
  const { Cdp } = await import('./jinsha.mjs');
  const cdp = await Cdp.open();
  try {
    const out = { window: win, platforms: {}, runtimeModelDecisions: 0 };
    for (const platformKey of platforms) {
      await navigate(cdp, HOME, 1200);
      const entry = await cdp.eval(entryProbe);
      assertJinshaEntry(entry, { home: HOME });
      out.platforms[platformKey] = await collectPlatform(cdp, platformKey, win);
    }
    return out;
  } finally {
    try { await navigate(cdp, HOME, 900); } catch { /* noop */ }
    cdp.close();
  }
}
