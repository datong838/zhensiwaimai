#!/usr/bin/env node
/**
 * 诊断6：外层 /app/shop/26319/ 下，硬刷新后 iframe 到底是 shop 还是 chain 路由
 * 判据：iframe location.href 含 /shop/ 还是 /chain/；顾客概览下单顾客量级；卡片数
 */
const PORT = 9230;
function connect(url) {
  return new Promise((res, rej) => {
    const ws = new WebSocket(url);
    const P = new Map(); const H = new Map(); let seq = 0;
    ws.addEventListener('open', () => res({
      send: (m, params = {}, timeout = 90000) => {
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
const ctxs = []; c.on('Runtime.executionContextCreated', (p) => ctxs.push(p.context));
await c.send('Runtime.enable'); await c.send('Page.enable');
await c.send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1500, deviceScaleFactor: 1, mobile: false });
const evm = async (e) => (await c.send('Runtime.evaluate', { expression: e, returnByValue: true }, 60000)).result?.value;

const snapshot = async () => {
  const outer = await evm('location.href');
  const frames = JSON.parse(await evm(`JSON.stringify([...document.querySelectorAll('iframe')].map(i=>({src:(i.src||'').slice(0,140),w:i.clientWidth,h:i.clientHeight})))`));
  return { outer, frames };
};

console.log('BEFORE=' + JSON.stringify(await snapshot()));

// 硬刷新
await c.send('Page.reload', { ignoreCache: true });
await sleep(15000);
await c.send('Runtime.disable'); await c.send('Runtime.enable');
await sleep(3000);

const after = await snapshot();
console.log('AFTER=' + JSON.stringify(after));

// 进 iframe 读卡片与关键数字
let ctx = ctxs.filter((x) => /melody-stats-next/.test(x.origin || '')).pop();
if (!ctx) { console.log('NO_STATS_CTX'); c.close(); process.exit(0); }
const ev = async (e) => (await c.send('Runtime.evaluate', { expression: e, returnByValue: true, contextId: ctx.id }, 60000)).result?.value;
console.log('IFRAME_URL=' + await ev('location.href'));
console.log('CARDS=' + await ev(`JSON.stringify([...document.querySelectorAll('.card-border')].map(n=>(n.className||'').toString().replace('card-border','').trim()+' h='+Math.round(n.getBoundingClientRect().height)))`));
console.log('BLOCK_HIT=' + await ev(`String((document.body.innerText.match(/街区/g)||[]).length)`));
console.log('OVERVIEW=' + await ev(`(()=>{const n=document.querySelector('.customer_analysis');if(!n)return 'nf';const t=n.innerText.replace(/\\s+/g,' ');const i=t.indexOf('下单顾客');return t.slice(0,160)})()`));
console.log('LIST_ROWS=' + await ev(`String(document.querySelectorAll('.customer_list .ant-table-row').length)`));
c.close(); process.exit(0);
