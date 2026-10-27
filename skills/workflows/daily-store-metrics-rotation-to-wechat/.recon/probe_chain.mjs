#!/usr/bin/env node
/**
 * 诊断2：模块标题的祖先链 + 每个祖先内的 select 情况
 * 目的：用「容器包含关系」锚定模块自己的时间选择器，而不是靠 y 坐标
 */
const PORT = 9230;
function connect(url) {
  return new Promise((res, rej) => {
    const ws = new WebSocket(url);
    const P = new Map(); const H = new Map(); let seq = 0;
    ws.addEventListener('open', () => res({
      send: (method, params = {}, timeout = 60000) => {
        const id = ++seq;
        return new Promise((r, j) => {
          const t = setTimeout(() => { P.delete(id); j(new Error('timeout:' + method)); }, timeout);
          P.set(id, { r, j, t });
          ws.send(JSON.stringify({ id, method, params }));
        });
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
await c.send('Runtime.enable');
await c.send('Page.enable');
await c.send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1500, deviceScaleFactor: 1, mobile: false });
await c.send('Runtime.disable'); await c.send('Runtime.enable');
await sleep(2000);
const ctx = ctxs.filter((x) => /melody-stats-next/.test(x.origin || '')).pop();
if (!ctx) { console.error('no iframe ctx'); process.exit(1); }
const CTX = ctx.id;
const ev = async (expr) => (await c.send('Runtime.evaluate', { expression: expr, returnByValue: true, contextId: CTX }, 60000)).result?.value;

const TITLE = process.argv[2] || '下单时段';

const out = await ev(`(()=>{
  const T=${JSON.stringify(TITLE)};
  const all=[...document.querySelectorAll('*')].filter(x=>(x.innerText||'').trim()===T);
  const res={candidates:[]};
  for(const n of all){
    if(n.children.length>1) continue;
    const r=n.getBoundingClientRect();
    const chain=[];
    let p=n, d=0;
    while(p && d<9){
      const pr=p.getBoundingClientRect();
      const sels=[...p.querySelectorAll('.ant-select')].map(s=>{
        const sr=s.getBoundingClientRect();
        return {y:Math.round(sr.y),x:Math.round(sr.x),t:(s.innerText||'').trim().slice(0,10)};
      });
      chain.push({d,tag:p.tagName,cls:(p.className||'').toString().slice(0,60),rect:[Math.round(pr.x),Math.round(pr.y),Math.round(pr.width),Math.round(pr.height)],selCount:sels.length,sels:sels.slice(0,4)});
      p=p.parentElement; d++;
    }
    res.candidates.push({tag:n.tagName,cls:(n.className||'').toString().slice(0,60),rect:[Math.round(r.x),Math.round(r.y),Math.round(r.width),Math.round(r.height)],scrollY:window.scrollY,chain});
  }
  return JSON.stringify(res,null,1);
})()`);
console.log('TITLE_CHAIN=' + out);
c.close(); process.exit(0);
