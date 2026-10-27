#!/usr/bin/env node
/**
 * 诊断：时间选择器下拉浮层的真实 DOM 结构
 * 只读 + 一次点击，不改业务数据
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
      if (d.id && P.has(d.id)) {
        const p = P.get(d.id); P.delete(d.id); clearTimeout(p.t);
        if (d.error) p.j(new Error(d.error.message)); else p.r(d.result);
      } else if (d.method && H.has(d.method)) {
        for (const f of H.get(d.method)) { try { f(d.params); } catch {} }
      }
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
await sleep(2500);

const ctx = ctxs.filter((x) => /melody-stats-next/.test(x.origin || '')).pop();
if (!ctx) { console.error('no iframe ctx'); process.exit(1); }
const CTX = ctx.id;
const ev = async (expr) => (await c.send('Runtime.evaluate', { expression: expr, returnByValue: true, contextId: CTX }, 60000)).result?.value;
const evm = async (expr) => (await c.send('Runtime.evaluate', { expression: expr, returnByValue: true }, 60000)).result?.value;
const clickAt = async (x, y) => { for (const type of ['mousePressed', 'mouseReleased']) await c.send('Input.dispatchMouseEvent', { type, x, y, button: 'left', clickCount: 1 }); };

// 滚到 下单时段
await ev(`(()=>{const n=[...document.querySelectorAll('*')].find(x=>(x.innerText||'').trim()==='下单时段'&&x.children.length<=1&&x.getBoundingClientRect().width>0); if(n){n.scrollIntoView({block:'start'});window.scrollBy(0,-100);return 'ok'} return 'nf'})()`);
await sleep(1500);

const pick = await ev(`(()=>{
  const nodes=[...document.querySelectorAll('*')];
  const tn=nodes.find(x=>(x.innerText||'').trim()==='下单时段'&&x.children.length<=1&&x.getBoundingClientRect().width>0);
  if(!tn) return 'title-nf';
  const tr=tn.getBoundingClientRect();
  let best=null;
  for(const n of nodes){
    const t=(n.innerText||'').trim();
    if(!/^(近7日|近30日|近90日)$/.test(t)) continue;
    if(n.children.length>1) continue;
    const r=n.getBoundingClientRect();
    if(!r.width||r.width>120) continue;
    if(Math.abs(r.y-tr.y)>45||r.x<tr.x) continue;
    if(!best||r.x>best.x) best={x:r.x+r.width/2,y:r.y+r.height/2,text:t,tag:n.tagName,cls:n.className};
  }
  return best?JSON.stringify(best):'picker-nf';
})()`);
console.log('PICKER=', pick);
if (pick === 'picker-nf' || pick === 'title-nf') process.exit(2);
const P = JSON.parse(pick);

const box = JSON.parse(await evm(`(()=>{const f=[...document.querySelectorAll('iframe')].find(i=>i.clientWidth>300);const b=f.getBoundingClientRect();return JSON.stringify({x:b.x,y:b.y,w:b.width,h:b.height})})()`));
console.log('IFRAME_BOX=', JSON.stringify(box));

await clickAt(P.x + box.x, P.y + box.y);
await sleep(1200);

const dump = await ev(`(()=>{
  const nodes=[...document.querySelectorAll('*')];
  const out=[];
  for(const n of nodes){
    const t=(n.innerText||'').trim();
    if(!/^近(7|30|90)日$/.test(t)) continue;
    const r=n.getBoundingClientRect();
    if(!r.width && !r.height) continue;
    out.push({tag:n.tagName,cls:(n.className&&n.className.baseVal!==undefined?n.className.baseVal:n.className||'').toString().slice(0,80),
      text:t,x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),h:Math.round(r.height),
      vis:n.offsetParent!==null, pe:getComputedStyle(n).pointerEvents, depth:(()=>{let d=0,p=n;while(p=p.parentElement)d++;return d})()});
  }
  return JSON.stringify(out,null,1);
})()`);
console.log('OPTION_NODES=', dump);

// 找浮层容器
const pop = await ev(`(()=>{
  const nodes=[...document.querySelectorAll('*')];
  const hosts=nodes.filter(n=>{
    const cs=getComputedStyle(n);
    return (cs.position==='absolute'||cs.position==='fixed') && n.getBoundingClientRect().width>60 && n.getBoundingClientRect().height>40
      && /近30日/.test(n.innerText||'') && n.getBoundingClientRect().height<400;
  }).slice(0,4).map(n=>({tag:n.tagName,cls:(n.className||'').toString().slice(0,100),html:n.outerHTML.slice(0,900)}));
  return JSON.stringify(hosts,null,1);
})()`);
console.log('POPUP_HOSTS=', pop);

c.close();
process.exit(0);
