// 只读实机验证：走完导航门禁 + 候选采集，零申诉点击、零 md 写入、零消息发送。
// 双平台：美团走 status 模式（申诉类型=全部+状态=未申诉），淘宝走 category 模式（分类=全部）。
import { PLATFORMS, recentRange, businessDate, Cdp, navigate, HOME } from './jinsha.mjs';
import { openFilteredPage } from './page_state.mjs';

const win = recentRange();
const cdp = await Cdp.open();
const out = { ok: false, businessDate: businessDate(), window: win, platforms: {}, runtimeModelDecisions: 0 };
try {
  for (const spec of PLATFORMS) {
    const resolvedStatus = spec.mode === 'status' ? spec.appealStatus : undefined;
    const state = await openFilteredPage(cdp, { platformKey: spec.key, status: resolvedStatus, window: win });
    out.platforms[spec.key] = {
      label: spec.label,
      mode: spec.mode,
      url: state.url,
      platformTab: state.platform,
      timeTab: state.timeTab,
      dates: state.dates,
      appealFilter: state.appealFilter,
      status: state.status,
      statusCounts: state.statusCounts,
      category: state.category,
      categoryCounts: state.categoryCounts,
      total: state.totalNumber,
      cardsRead: state.cards.length,
      candidates: state.cards.filter(c => c.hasAppealBtn).map(c => ({
        store: c.store, date: c.date, orderNo: c.orderNo, category: c.category,
        passRate: c.passRate, preAppealLen: (c.preAppeal || '').length,
      })),
    };
  }
  out.ok = true;
} catch (error) {
  out.error = String(error.message || error);
  out.stack = String(error.stack || '').split('\n').slice(0, 6).join('\n');
} finally {
  try { await navigate(cdp, HOME, 1000); } catch { /* noop */ }
  cdp.close();
}
console.log(JSON.stringify(out, null, 1));
