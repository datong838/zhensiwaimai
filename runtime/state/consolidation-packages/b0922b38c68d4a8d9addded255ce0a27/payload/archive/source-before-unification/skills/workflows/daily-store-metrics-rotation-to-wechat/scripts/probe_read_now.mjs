#!/usr/bin/env node
/**
 * 只读探针：读当前页 iframe 的作用域与关键数字（不做任何导航）
 * 用途：切店后立即取值，判断「数据是否真跟着店铺变」。
 */
import { session, sleep } from './lib/cdp.mjs';

const s = await session({ port: 9230 });
const r = await s.ctxForFrame(/melody-stats-next/);
if (!r.id) { console.log('ERR=no-frame'); process.exit(4); }
const ev = s.frameEval(r.id);
const href = String(await ev('location.href').catch(() => ''));
const txt = String(await ev('document.body.innerText').catch(() => '')).replace(/\s+/g, ' ');
const g = (re) => { const m = txt.match(re); return m ? m[1] : null; };
console.log('NAME=' + (await s.mainEval(`(()=>{const n=document.querySelector('[class*=shop-name__]');return n?n.innerText.trim():''})()`)));
console.log('SCOPE=' + (/\/single\//.test(href) ? 'single' : /\/chain\//.test(href) ? 'chain' : 'other'));
console.log(`DATA 下单顾客=${g(/下单顾客\s*([\d,]+)/)} 复购率=${g(/复购率\s*([\d.]+%)/)} 复购人数=${g(/复购人数\s*([\d,]+)/)}`);
if (process.argv.includes('--restore')) {
  await s.cdp.send('Page.navigate', { url: 'https://melody.shop.ele.me/app/chain/95708808/stats__center#app.chainshop.stats.center' });
  await sleep(4000);
  console.log('RESTORE=' + (await s.mainEval('location.href')));
}
process.exit(0);
