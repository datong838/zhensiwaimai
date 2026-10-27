#!/usr/bin/env node
/**
 * 只读探针：URL 直达是否只是「换了店名没换数据」的假通过？
 *
 * 判据：对两家不同的店直达同一页面，取 iframe 内的关键数字（下单顾客 / 复购率）。
 *   - 数字随店铺变化 ⇒ 直达真生效
 *   - 数字完全相同 ⇒ iframe 仍停在 chain 汇总视图，直达无效（capture_metric 的 /single/ 校验是对的）
 *
 * 同时输出 iframe 作用域（chain / single）作为机制解释。
 */
import { session, sleep } from './lib/cdp.mjs';

const CHAIN_HOME = 'https://melody.shop.ele.me/app/chain/95708808/stats__center#app.chainshop.stats.center';
const CASES = [
  { id: '694471', name: '李当家汉派猪蹄饭(一清路店)' },
  { id: '2260213', name: '集佰坊大众饭堂(航头店)' },
];

const s = await session({ port: 9230 });

async function probe(shopId) {
  await s.cdp.send('Page.navigate', { url: `https://melody.shop.ele.me/app/shop/${shopId}/customerStats#app.shop.customerStats` });
  await sleep(3600);
  await s.rearm();
  const r = await s.ctxForFrame(/melody-stats-next/);
  if (!r.id) return { shopId, err: 'frame ' + JSON.stringify(r).slice(0, 120) };
  const ev = s.frameEval(r.id);
  const href = await ev('location.href').catch(() => '');
  const txt = String(await ev('document.body.innerText').catch(() => '')).replace(/\s+/g, ' ');
  const g = (re) => { const m = txt.match(re); return m ? m[1] : null; };
  return {
    shopId,
    name: await s.mainEval(`(()=>{const n=document.querySelector('[class*=shop-name__]');return n?n.innerText.trim():''})()`),
    scope: /\/single\//.test(href) ? 'single' : /\/chain\//.test(href) ? 'chain' : 'other',
    orders: g(/下单顾客\s*([\d,]+)/),
    repeat: g(/复购率\s*([\d.]+%)/),
    repeatN: g(/复购人数\s*([\d,]+)/),
  };
}

if (process.argv.includes('--warmup')) {
  await s.cdp.send('Page.navigate', { url: 'https://melody.shop.ele.me/app/shop/694471/customerStats#app.shop.customerStats' });
  await sleep(4500);
  await s.rearm();
  const wr = await s.ctxForFrame(/melody-stats-next/);
  const wh = wr.id ? String(await s.frameEval(wr.id)('location.href').catch(() => '')) : '';
  console.log('WARMUP scope=' + (/\/single\//.test(wh) ? 'single' : /\/chain\//.test(wh) ? 'chain' : 'none'));
}

const out = [];
for (const c of CASES) {
  const r = await probe(c.id);
  out.push(r);
  console.log(`shop=${c.id} name="${r.name}" scope=${r.scope} 下单顾客=${r.orders} 复购率=${r.repeat} 复购人数=${r.repeatN}`);
}

const same = out.length === 2 && out[0].orders && out[0].orders === out[1].orders;
console.log(`\nVERDICT data_changed=${same ? 'NO' : 'YES'} ⇒ ${same ? 'URL 直达只是换了店名，数据仍是同一份（chain 汇总），不可用' : '数据随店铺变化，直达可用'}`);

await s.cdp.send('Page.navigate', { url: CHAIN_HOME });
await sleep(3500);
console.log('RESTORE=' + (await s.mainEval('location.href')));
process.exit(0);
