#!/usr/bin/env node
// probe_shoplist.mjs —— 在金鲨(9232)当前页面上用**同源 fetch** 探店铺列表参数组合
// 纪律：不导航、不点页面、不新开标签。纯 fetch，只读。
// 目标：找到「淘宝闪购 tab + 营业中 + 是会员」对应的参数组合（期望 total=492）

import process from 'node:process';

const PORT = 9232;
const API = 'https://data.guoshuyufen.com/api//shop/list?pageNo=1&pageSize=200';

function makeClient(wsUrl) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(String(wsUrl).replace('localhost', '127.0.0.1'));
    const pending = new Map(); let seq = 0;
    ws.addEventListener('open', () => resolve({
      send(method, params, timeout = 60000) {
        const id = ++seq;
        return new Promise((res, rej) => {
          const t = setTimeout(() => { pending.delete(id); rej(new Error('timeout:' + method)); }, timeout);
          pending.set(id, { res, rej, t });
          ws.send(JSON.stringify({ id, method, params: params || {} }));
        });
      },
      close() { try { ws.close(); } catch {} },
    }));
    ws.addEventListener('error', () => reject(new Error('ws-error')));
    ws.addEventListener('message', ev => {
      let d; try { d = JSON.parse(ev.data); } catch { return; }
      if (d.id && pending.has(d.id)) {
        const p = pending.get(d.id); pending.delete(d.id); clearTimeout(p.t);
        d.error ? p.rej(new Error(d.error.message)) : p.res(d.result);
      }
    });
    setTimeout(() => reject(new Error('ws-open-timeout')), 8000);
  });
}

const base = {
  pageNo: 1, pageSize: 200, shopName: '', city: '', orderByColumn: '', isAsc: '',
  businessStatus: '', isInvalid: 0, isMember: 1, isShopStatus: 1,
};

const COMBOS = [
  ['A 会员+营业+未移除', { ...base }],
  ['B 会员+营业+未移除+platformType1', { ...base, platformType: 1 }],
  ['C 会员+营业+全部移除态', { ...base, isInvalid: -1 }],
  ['D 会员+营业+全部移除态+platformType1', { ...base, isInvalid: -1, platformType: 1 }],
  ['E 会员+全部状态+未移除+platformType1', { ...base, isShopStatus: undefined, platformType: 1 }],
  ['F 全部+营业+未移除', { ...base, isMember: -1 }],
  ['G 会员+营业+已移除+platformType1', { ...base, isInvalid: 1, platformType: 1 }],
];

async function main() {
  const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`, { signal: AbortSignal.timeout(5000) })).json();
  const page = list.find(t => t.type === 'page' && /guoshuyufen\.com/.test(t.url || ''));
  if (!page) throw new Error('no-jinsha-page');
  console.log('page:', page.url);
  const c = await makeClient(page.webSocketDebuggerUrl);
  await c.send('Runtime.enable');

  const expr = `(async()=>{
    const API=${JSON.stringify(API)};
    const combos=${JSON.stringify(COMBOS.map(([n, p]) => [n, Object.fromEntries(Object.entries(p).filter(([, v]) => v !== undefined))]))};
    const out=[];
    for(const [name,body] of combos){
      try{
        const r=await fetch(API,{method:'POST',headers:{'Content-Type':'application/json'},credentials:'include',body:JSON.stringify(body)});
        const j=await r.json();
        out.push({name,total:j?.data?.total,got:(j?.data?.list||[]).length,first:(j?.data?.list||[])[0]?.shopName||null});
      }catch(e){ out.push({name,err:String(e).slice(0,120)}); }
    }
    const r2=await fetch(API,{method:'POST',headers:{'Content-Type':'application/json'},credentials:'include',body:JSON.stringify(${JSON.stringify({ ...base, platformType: 1 })})});
    const j2=await r2.json();
    const row=(j2?.data?.list||[])[0]||{};
    return JSON.stringify({combos:out, keys:Object.keys(row), sample:row}, null, 1);
  })()`;

  const r = await c.send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true }, 120000);
  if (r.exceptionDetails) { console.error(JSON.stringify(r.exceptionDetails).slice(0, 500)); c.close(); process.exit(3); }
  const res = JSON.parse(r.result.value);
  console.log('\n=== 组合命中 ===');
  for (const x of res.combos) console.log(`${String(x.total).padStart(5)}  ${x.name}${x.err ? '  ERR ' + x.err : ''}`);
  console.log('\n=== 行字段 ===\n' + res.keys.join(','));
  console.log('\n=== 样例行 ===\n' + JSON.stringify(res.sample, null, 1));
  c.close();
}

main().then(() => process.exit(0)).catch(e => { console.error('ERR', e.message); process.exit(4); });
