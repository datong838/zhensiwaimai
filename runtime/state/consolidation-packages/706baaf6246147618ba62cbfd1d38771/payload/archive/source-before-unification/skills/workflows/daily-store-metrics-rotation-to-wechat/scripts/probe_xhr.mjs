#!/usr/bin/env node
/**
 * 只读探针：验证「指标数据能否绕过页面渲染直取」
 *
 * 目的（回答 P2 问题，见 REQUIREMENTS §4.5）：
 *   1. customerStats 页一次加载，里面到底有几个指标区块？（证明 M02–M06 是否同页可一次截完）
 *   2. 这页的数据是哪个 XHR 接口给的？能否被脚本直接重放？
 *   3. 一次页面加载到首个指标可截，实际耗时多少？（替代人工 33/79/64s 的估算锚点）
 *
 * 安全边界：
 *   - 复用已开页（session() 内部禁新开标签），只读 GET，**不发送任何消息**
 *   - 结束后导航回连锁首页（CHAIN_HOME），避免把工位留在单店视图（E55 教训）
 *
 * 用法：node probe_xhr.mjs [--shop-id 694471] [--wait 22] [--keep]
 * 退出码：0 正常；2 参数/连接错；3 页面未到业务态
 */
import { session, sleep } from './lib/cdp.mjs';

function arg(n, d = null) {
  const i = process.argv.indexOf('--' + n);
  return i > 0 && process.argv[i + 1] ? process.argv[i + 1] : d;
}

const SHOP = arg('shop-id', '694471');
const WAIT = Number(arg('wait', '22'));
const KEEP = process.argv.includes('--keep');
const URL = `https://melody.shop.ele.me/app/shop/${SHOP}/customerStats#app.shop.customerStats`;
const CHAIN_HOME = 'https://melody.shop.ele.me/app/chain/95708808/stats__center#app.chainshop.stats.center';

const s = await session({ port: 9230 });

const reqs = new Map();
s.cdp.on('Network.requestWillBeSent', (p) => {
  if (!/XHR|Fetch/i.test(p.type || '')) return;
  reqs.set(p.requestId, { url: p.request.url, method: p.request.method, status: null, bytes: 0, mime: '' });
});
s.cdp.on('Network.responseReceived', (p) => {
  const r = reqs.get(p.requestId);
  if (!r) return;
  r.status = p.response.status;
  r.mime = p.response.mimeType || '';
});
// 响应体长度只有在 loadingFinished 才准确（responseReceived 阶段 encodedDataLength 常为 0）
s.cdp.on('Network.loadingFinished', (p) => {
  const r = reqs.get(p.requestId);
  if (!r) return;
  r.bytes = p.encodedDataLength || 0;
});

await s.cdp.send('Network.enable', { maxTotalBufferSize: 40000000, maxResourceBufferSize: 10000000 });

const t0 = Date.now();
await s.cdp.send('Page.navigate', { url: URL });
console.log('NAVIGATE=' + URL);

// 等 iframe 里出现业务区块
let ready = false;
let readyAt = 0;
for (let i = 0; i < WAIT; i++) {
  await sleep(1000);
  const ctx = await s.ctxForFrame(/melody-stats-next/);
  if (!ctx.id) continue;
  const ok = await s.frameEval(ctx.id)(`(()=>{
    const txt = document.body ? document.body.innerText : '';
    return txt.length > 200 && /顾客分析|下单行为|顾客特征/.test(txt);
  })()`).catch(() => false);
  if (ok) { ready = true; readyAt = Date.now() - t0; break; }
}

console.log(`READY=${ready} ready_ms=${readyAt} wall_ms=${Date.now() - t0}`);

let blocks = null;
if (ready) {
  const ctx = await s.ctxForFrame(/melody-stats-next/);
  blocks = await s.frameEval(ctx.id)(`(()=>{
    const heads = [...document.querySelectorAll('h1,h2,h3,h4,[class*=title],[class*=Title]')]
      .map(e => (e.innerText||'').trim()).filter(t => t && t.length < 24);
    const cards = [...document.querySelectorAll('[class*=card],[class*=Card]')]
      .map(e => (e.className||'').toString().slice(0,60));
    return {
      texts: [...new Set(heads)].slice(0, 40),
      cardClassCount: cards.length,
      bodyLen: document.body.innerText.length,
      scrollH: document.documentElement.scrollHeight,
      viewportH: window.innerHeight
    };
  })()`).catch((e) => ({ err: String(e) }));
}

await sleep(3000);

const list = [...reqs.values()]
  .filter((r) => /shop\.ele\.me|ele\.me/.test(r.url) && !/\.(png|jpg|jpeg|gif|svg|woff2?|css|js)(\?|$)/i.test(r.url))
  .sort((a, b) => b.bytes - a.bytes);

console.log('\n=== XHR/Fetch（按响应字节降序，top 25）===');
for (const r of list.slice(0, 25)) {
  const p = r.url.replace(/^https?:\/\/[^/]+/, '');
  console.log(`${String(r.status ?? '--').padStart(3)} ${String((r.bytes / 1024).toFixed(1)).padStart(7)}KB ${r.method.padEnd(6)} ${p.slice(0, 190)}`);
}
console.log(`XHR_TOTAL=${list.length} BIG_OVER_8K=${list.filter((r) => r.bytes > 8192).length}`);

console.log('\n=== 页面区块（证明同页含多指标）===');
console.log(JSON.stringify(blocks, null, 1));

if (!KEEP) {
  await s.cdp.send('Page.navigate', { url: CHAIN_HOME });
  await sleep(4000);
  const back = await s.mainEval('location.href').catch(() => '');
  console.log('\nRESTORE=' + (/stats__center|app\.chainshop/.test(String(back)) ? 'OK chain-home' : 'WARN ' + String(back).slice(0, 90)));
}
process.exit(ready ? 0 : 3);
