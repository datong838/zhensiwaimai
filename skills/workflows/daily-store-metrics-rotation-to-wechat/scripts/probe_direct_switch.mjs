#!/usr/bin/env node
/**
 * 只读探针：验证「URL 直达能否替代切换器降级链」
 *
 * 背景：切店一直是最大固定成本（降级链每级去抖 3s ⇒ 估 30s/店）。
 *       若直接 Page.navigate 到 /app/shop/<shopId>/<page> 能让页面真正落到该店，
 *       切店成本就从 30s 降到「一次导航」。
 *
 * 判据（三判据齐才算通过，缺一不可）：
 *   1. 顶部店名 == 期望店名（正对照）
 *   2. 换一家店店名跟着变（负对照：排除「页面根本没刷新」的假通过）
 *   3. iframe href 含 /single/（页面作用域真在单店，非连锁视图）
 *
 * 全程只读 GET，不发送任何消息；结束复位连锁首页（E55 教训）。
 * 用法：node probe_direct_switch.mjs
 */
import { session, sleep } from './lib/cdp.mjs';

const CHAIN_HOME = 'https://melody.shop.ele.me/app/chain/95708808/stats__center#app.chainshop.stats.center';
const CASES = [
  { id: '694471', name: '李当家汉派猪蹄饭(一清路店)' },
  { id: '2260213', name: '集佰坊大众饭堂(航头店)' },
];

const s = await session({ port: 9230 });

async function goto(shopId) {
  const t0 = Date.now();
  await s.cdp.send('Page.navigate', {
    url: `https://melody.shop.ele.me/app/shop/${shopId}/customerStats#app.shop.customerStats`,
  });
  await sleep(300);
  await s.rearm(); // SPA 导航后必须重放 executionContext，否则拿到旧 context（本库第 3 条纪律）
  let href = '';
  let name = '';
  let navMs = 0;
  for (let i = 0; i < 30; i++) {
    const r = await s.ctxForFrame(/melody-stats-next/).catch(() => ({}));
    if (r && r.id) href = (await s.frameEval(r.id)('location.href').catch(() => '')) || href;
    const n = await s.mainEval(`(()=>{const x=document.querySelector('[class*=shop-name__]');return x?x.innerText.trim():''})()`).catch(() => '');
    if (n) name = n;
    if (/\/single\//.test(String(href)) && name) { navMs = Date.now() - t0; break; }
    await sleep(500);
  }
  const single = /\/single\//.test(String(href)) && String(href).includes(String(shopId));
  return { shopId, name, href, navMs, single };
}

await s.cdp.send('Page.navigate', { url: CHAIN_HOME });
await sleep(2500);
await s.rearm();

const out = [];
for (const c of CASES) {
  const t0 = Date.now();
  const r = await goto(c.id);
  const got = r.name.replace(/\s+/g, '');
  const want = c.name.replace(/\s+/g, '');
  const matched = got === want;
  out.push({ ...r, want: c.name, matched, totalMs: Date.now() - t0 });
  console.log(`${matched && r.single ? 'PASS' : 'FAIL'} shop=${c.id} matched=${matched} single=${r.single} navMs=${r.navMs} got="${got}"`);
  console.log(`     href_tail=...${String(r.href).slice(-70)}`);
}

const changed = out.length === 2 && out[0].name && out[1].name && out[0].name !== out[1].name;
const allMatch = out.every((x) => x.matched && x.single);
console.log(`\nVERDICT direct_switch=${allMatch && changed ? 'OK' : 'NG'} allMatch=${allMatch} nameChanged=${changed}`);
console.log(`NAV_COST avg=${Math.round(out.reduce((a, x) => a + x.navMs, 0) / out.length)}ms max=${Math.max(...out.map((x) => x.navMs))}ms`);

await s.cdp.send('Page.navigate', { url: CHAIN_HOME });
await sleep(4000);
const back = await s.mainEval('location.href').catch(() => '');
console.log('RESTORE=' + (/stats__center|app\.chainshop/.test(String(back)) ? 'OK chain-home' : 'WARN ' + String(back).slice(0, 90)));

process.exit(allMatch && changed ? 0 : 5);
