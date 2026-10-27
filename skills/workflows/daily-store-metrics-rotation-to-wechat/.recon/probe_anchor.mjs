#!/usr/bin/env node
/**
 * 诊断3：批量验证「标题 → 最小含 select 祖先」锚定法
 * 输出每个模块的：标题 rect / 锚定容器 cls / select rect / 当前值
 */
const PORT = 9230;
function connect(url) {
  return new Promise((res, rej) => {
    const ws = new WebSocket(url);
    const P = new Map(); const H = new Map(); let seq = 0;
    ws.addEventListener('open', () => res({
      send: (m, params = {}, timeout = 60000) => {
        const id = ++seq;
        return new Promise((r, j) => {
          const t = setTimeout(() => { P.delete(id); j(new Error('timeout:' + m)); }, timeout);
          P.set(id, { r, j, t });
          ws.send(JSON.stringify({ id, method: m, params }));
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
await c.send('Runtime.enable'); await c.send('Page.enable');
await c.send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1500, deviceScaleFactor: 1, mobile: false });
await c.send('Runtime.disable'); await c.send('Runtime.enable');
await sleep(2000);
const ctx = ctxs.filter((x) => /melody-stats-next/.test(x.origin || '')).pop();
if (!ctx) { console.error('no iframe ctx'); process.exit(1); }
const CTX = ctx.id;
const ev = async (expr) => (await c.send('Runtime.evaluate', { expression: expr, returnByValue: true, contextId: CTX }, 60000)).result?.value;

const TITLES = ['顾客概览', '顾客分布', '下单行为', '下单时段', '下单热门街区', '顾客特征', '商圈顾客动态', '互动行为', '顾客画像'];

// 1) 页面顶层结构：.customer 的直接子块
const topo = await ev(`(()=>{
  const root=document.querySelector('.customer');
  if(!root) return 'no-customer-root';
  const kids=[...root.children].map((n,i)=>{
    const r=n.getBoundingClientRect();
    return {i,tag:n.tagName,cls:(n.className||'').toString().slice(0,50),y:Math.round(r.y),h:Math.round(r.height),
      txt:(n.innerText||'').trim().replace(/\\s+/g,' ').slice(0,60), sels:[...n.querySelectorAll('.ant-select')].length};
  });
  return JSON.stringify({scrollY:window.scrollY,kids},null,1);
})()`);
console.log('TOPO=' + topo);

// 2) 每个标题的锚定结果
const anchor = await ev(`(()=>{
  const TITLES=${JSON.stringify(TITLES)};
  const out=[];
  for(const T of TITLES){
    const cands=[...document.querySelectorAll('*')].filter(x=>(x.innerText||'').trim()===T && x.children.length<=1 && x.getBoundingClientRect().width>0);
    if(!cands.length){ out.push({title:T,err:'title-not-found'}); continue; }
    const n=cands[0];
    const tr=n.getBoundingClientRect();
    // 向上找最小「含且仅含 1 个 .ant-select 且高度<700」的祖先
    let p=n, anchorEl=null;
    for(let d=0;d<8&&p;d++){
      const sels=[...p.querySelectorAll('.ant-select')];
      const pr=p.getBoundingClientRect();
      if(sels.length>=1 && pr.height<700){ anchorEl={el:p,sels,d}; break; }
      p=p.parentElement;
    }
    if(!anchorEl){ out.push({title:T,titleCls:(n.className||'').toString().slice(0,40),rect:[Math.round(tr.x),Math.round(tr.y)],err:'no-anchor'}); continue; }
    out.push({
      title:T,
      titleCls:(n.className||'').toString().slice(0,40),
      titleRect:[Math.round(tr.x),Math.round(tr.y),Math.round(tr.width),Math.round(tr.height)],
      anchorCls:(anchorEl.el.className||'').toString().slice(0,50),
      anchorD:anchorEl.d,
      anchorRect:[Math.round(anchorEl.el.getBoundingClientRect().x),Math.round(anchorEl.el.getBoundingClientRect().y),Math.round(anchorEl.el.getBoundingClientRect().width),Math.round(anchorEl.el.getBoundingClientRect().height)],
      sels:anchorEl.sels.slice(0,3).map(s=>{const sr=s.getBoundingClientRect();const it=s.querySelector('.ant-select-selection-item');
        return {x:Math.round(sr.x),y:Math.round(sr.y),w:Math.round(sr.width),val:it?it.innerText.trim():null};}),
    });
  }
  return JSON.stringify(out,null,1);
})()`);
console.log('ANCHORS=' + anchor);
c.close(); process.exit(0);
