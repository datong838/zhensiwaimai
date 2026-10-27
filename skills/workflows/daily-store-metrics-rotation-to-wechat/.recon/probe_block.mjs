#!/usr/bin/env node
/** 诊断5：只查『街区』『商圈』字样 + 卡片清单，输出压到最小 */
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
const ctxs = []; c.on('Runtime.executionContextCreated', (p) => ctxs.push(p.context));
await c.send('Runtime.enable'); await c.send('Page.enable');
await c.send('Runtime.disable'); await c.send('Runtime.enable');
await sleep(2000);
const ctx = ctxs.filter((x) => /melody-stats-next/.test(x.origin || '')).pop();
const CTX = ctx.id;
const ev = async (e) => (await c.send('Runtime.evaluate', { expression: e, returnByValue: true, contextId: CTX }, 60000)).result?.value;

console.log('URL=' + await ev('location.href'));
console.log('CARDS=' + await ev(`JSON.stringify([...document.querySelectorAll('.card-border')].map(n=>((n.className||'').toString().replace('card-border','').trim())+' h='+Math.round(n.getBoundingClientRect().height)))`));
console.log('BLOCK_CNT=' + await ev(`String((document.body.innerText.match(/街区/g)||[]).length)`));
console.log('BIZ_CNT=' + await ev(`String((document.body.innerText.match(/商圈/g)||[]).length)`));
console.log('BIZ_SAMPLE=' + await ev(`JSON.stringify([...new Set([...document.querySelectorAll('*')].filter(x=>x.children.length<=1&&/商圈/.test(x.innerText||'')).map(x=>x.innerText.trim()))].slice(0,8))`));
// 顾客分析卡片的 tab 结构（顾客分析 / 粉丝分析）
console.log('TABS=' + await ev(`JSON.stringify([...document.querySelectorAll('[class*=tab]')].filter(n=>n.getBoundingClientRect().width>0&&n.getBoundingClientRect().width<200&&(n.innerText||'').trim().length<12).map(n=>({cls:(n.className||'').toString().slice(0,40),t:n.innerText.trim().replace(/\\s+/g,'|')})).slice(0,20))`));
c.close(); process.exit(0);
