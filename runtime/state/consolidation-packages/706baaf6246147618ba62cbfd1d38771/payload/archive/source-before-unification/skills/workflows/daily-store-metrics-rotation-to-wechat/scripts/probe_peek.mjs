#!/usr/bin/env node
/**
 * 只读探针：URL 直达单店页后，确认「页面内容是否真是这家店的数据」
 * 用于定性 /single/ 判据在直达路径下为何不成立（capture_metric.mjs 退出码 9 的误杀点）
 */
import { session, sleep } from './lib/cdp.mjs';

const CHAIN_HOME = 'https://melody.shop.ele.me/app/chain/95708808/stats__center#app.chainshop.stats.center';
const SHOP = process.argv[2] || '694471';

const s = await session({ port: 9230 });
await s.cdp.send('Page.navigate', { url: `https://melody.shop.ele.me/app/shop/${SHOP}/customerStats#app.shop.customerStats` });
await sleep(3500);
await s.rearm();

const r = await s.ctxForFrame(/melody-stats-next/);
console.log('CTX=' + (r.id ? 'ok' : JSON.stringify(r).slice(0, 240)));
if (r.id) {
  const ev = s.frameEval(r.id);
  console.log('HREF_FULL=' + (await ev('location.href')));
  console.log('TEXT=' + String(await ev('document.body.innerText')).replace(/\s+/g, ' ').slice(0, 200));
}
console.log('NAME=' + (await s.mainEval(`(()=>{const n=document.querySelector('[class*=shop-name__]');return n?n.innerText.trim():''})()`)));
console.log('MAIN_URL=' + (await s.mainEval('location.href')));

await s.cdp.send('Page.navigate', { url: CHAIN_HOME });
await sleep(3500);
console.log('RESTORE=' + (await s.mainEval('location.href')));
process.exit(0);
