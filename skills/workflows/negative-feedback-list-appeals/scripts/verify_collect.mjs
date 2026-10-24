// 只读实机验证：双平台「全部」视图分页全量采集（不点击、不写 md、不发送）
import { PLATFORMS, recentRange, businessDate, Cdp, navigate, HOME } from './jinsha.mjs';
import { collectPlatform } from './all_feedback_collector.mjs';

const win = recentRange();
const cdp = await Cdp.open();
const out = { ok: false, businessDate: businessDate(), window: win, platforms: {}, runtimeModelDecisions: 0 };
try {
  for (const spec of PLATFORMS) {
    await navigate(cdp, HOME, 1200);
    const snap = await collectPlatform(cdp, spec.key, win);
    out.platforms[spec.key] = {
      label: snap.platformLabel,
      counts: snap.counts,
      total: snap.total,
      rows: snap.rows.length,
      coherent: snap.rows.length === snap.counts.全部 && snap.total === snap.rows.length,
      sample: snap.rows.slice(0, 2).map(r => ({ store: r.store, date: r.date, orderNo: r.orderNo, category: r.category })),
    };
  }
  out.ok = Object.values(out.platforms).every(p => p.coherent);
} catch (error) {
  out.error = String(error.message || error);
  out.stack = String(error.stack || '').split('\n').slice(0, 6).join('\n');
} finally {
  try { await navigate(cdp, HOME, 1000); } catch { /* noop */ }
  cdp.close();
}
console.log(JSON.stringify(out, null, 1));
