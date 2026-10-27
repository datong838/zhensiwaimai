#!/usr/bin/env node
/**
 * 诊断4：整页滚动到底，穷举所有卡片 + 搜索「街区/商圈」字样
 * 目的：确认 下单热门街区 / 商圈顾客动态 到底在不在 customerStats
 */
const PORT = 9230;
function connect(url) {
  return new Promise((res, rej) => {
    const ws = new WebSocket(url);
    const P = new Map(); const H = new Map(); let seq = 0;
    ws.addEventListener('open', () => res({
      send: (m, params = {}, timeout = 60000) => {
        const id = ++seq;
        return new Promise((r, j) => { const t = setTimeout(() => { P.delete(id); j(new Error('timeout:' + m)); }, timeout); P.set(id, { r, j, t }); ws.send(JSON.stringify({ id, method: m, params })); });
      },
      on: (k, f) => H.set(k, (H.get(k) || []).concat([f])),
      close: () => ws.close(),
    }));
    ws.addEventListener('message', (e) => {
      const d = JSON.parse(e.data);
      if (d.id && P.has(d.id)) { const p = P.get(d.id); P.delete(d.id); clearTimeout(p.t); if (d.error) p.j(new Error(d.error.message)); else p.r(d.result); }
      else if (d.method && H.has(d.method)) { for (const f of H.get(d.method)) { try { f(d.params); } catch {} } }
    });
    ws.addEventListener('error', () => rej(new Error('ws error')));
    setTimeout(() => rej(new Error('connect timeout')), 8000);
  });
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
const page = list.find((t) => t.type === 'page');
const c = await connect(page.webSocketDebuggerUrl);
const ctxs = [];
c.on('Runtime.executionContextCreated', (p) => ctxs.push(p.context));
await c.send('Runtime.enable'); await c.send('Page.enable');
await c.send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1500, deviceScaleFactor: 1, mobile: false });
await c.send('Runtime.disable'); await c.send('Runtime.enable');
await sleep(2000);
const ctx = ctxs.filter((x) => /melody-stats-next/.test(x.origin || '')).pop();
if (!ctx) { console.error('no iframe ctx'); process.exit(1); }
const CTX = ctx.id;
const ev = async (expr) => (await c.send('Runtime.evaluate', { expression: expr, returnByValue: true, contextId: CTX }, 60000)).result?.value;

// 逐屏滚动，每屏记录卡片数与街区字样命中
const trace = [];
for (let i = 0; i < 8; i++) {
  const r = await ev(`(()=>{
    const cards=[...document.querySelectorAll('.card-border')].map(n=>{
      const r=n.getBoundingClientRect();
      return {cls:(n.className||'').toString().replace('card-border','').trim().slice(0,40),docY:Math.round(r.y+window.scrollY),h:Math.round(r.height),
        head:(n.innerText||'').trim().replace(/\\s+/g,' ').slice(0,28)};
    });
    const hasBlock=[...document.querySelectorAll('*')].filter(x=>/街区/.test((x.innerText||''))&&x.children.length<=1).map(x=>(x.innerText||'').trim()).slice(0,5);
    const hasBiz=[...document.querySelectorAll('*')].filter(x=>/商圈/.test((x.innerText||''))&&x.children.length<=1).map(x=>(x.innerText||'').trim()).slice(0,5);
    return JSON.stringify({scrollY:Math.round(window.scrollY),sh:document.documentElement.scrollHeight,cards,hasBlock,hasBiz});
  })()`);
  trace.push(JSON.parse(r));
  await ev(`window.scrollBy(0,1200)`);
  await sleep(1200);
}
console.log(JSON.stringify(trace, null, 1));

// 全文兜底：找 街区/商圈
const hits = await ev(`(()=>{
  const t=document.body.innerText;
  const idx=[];let i=-1;
  while((i=t.indexOf('街区',i+1))>=0) idx.push(t.slice(Math.max(0,i-40),i+40).replace(/\\s+/g,' '));
  const idx2=[];i=-1;
  while((i=t.indexOf('商圈',i+1))>=0) idx2.push(t.slice(Math.max(0,i-40),i+40).replace(/\\s+/g,' '));
  return JSON.stringify({blockHits:idx.slice(0,6),bizHits:idx2.slice(0,6),bodyLen:t.length},null,1);
})()`);
console.log('TEXT_HITS=' + hits);
c.close(); process.exit(0);
