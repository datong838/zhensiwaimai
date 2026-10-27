#!/usr/bin/env node
/** 诊断23：先展开「数据中心」→ 点「经营分析」→ 摸四个 tab */
import fs from 'node:fs';
import { session, sleep } from '../scripts/lib/cdp.mjs';

const s = await session({ port: 9230, width: 1440, height: 1500 });
await s.rearm();
fs.mkdirSync('.recon/evidence', { recursive: true });

// 1) 展开 数据中心
const dc = JSON.parse(await s.mainEval(`(()=>{
  const n=[...document.querySelectorAll('li.cook-menu-item')].find(x=>(x.innerText||'').trim()==='数据中心');
  if(!n) return 'null';
  const r=n.getBoundingClientRect();
  return JSON.stringify({x:r.x+r.width/2,y:r.y+r.height/2});
})()`));
console.log('数据中心 at ' + JSON.stringify(dc));
await s.clickAt(dc.x, dc.y);
await sleep(2000);

// 2) 找子菜单 经营分析
const sub = await s.mainEval(`(()=>{
  const cands=[...document.querySelectorAll('li,a,div,span')].filter(n=>{
    const t=(n.innerText||'').trim();
    const r=n.getBoundingClientRect();
    return (t==='经营分析'||t.indexOf('经营分析')===0) && r.width>40 && r.width<260 && r.height>14;
  }).map(n=>{const r=n.getBoundingClientRect();return {t:(n.innerText||'').trim(),x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),tag:n.tagName}});
  const seen=new Set();const out=[];
  for(const o of cands){const k=o.t+'|'+o.y;if(seen.has(k))continue;seen.add(k);out.push(o);}
  return JSON.stringify(out);
})()`);
console.log('SUBMENU=' + sub);
if (sub === '[]') { console.log('submenu-not-visible'); process.exit(1); }
const S = JSON.parse(sub)[0];
await s.clickAt(S.x + 40, S.y + 10);
await sleep(9000);
await s.rearm();

console.log('OUTER=' + await s.mainEval('location.href'));
const r = await s.ctxForFrame(/melody-stats-next/);
if (r.err) { console.log('CTX_ERR=' + JSON.stringify(r)); process.exit(1); }
const ev = s.frameEval(r.id);
console.log('INNER=' + await ev('location.href'));

const info = await ev(`(()=>{
  const docY=(n)=>{const r=n.getBoundingClientRect();return Math.round(r.y+window.scrollY)};
  const tabs=[...document.querySelectorAll('.ant-tabs-tab')].map(n=>({t:(n.innerText||'').trim(),act:/active/.test((n.className||'').toString()),docY:docY(n)}));
  const cards=[...document.querySelectorAll('.card-border')].map(n=>({cls:(n.className||'').toString().replace('card-border','').trim(),docY:docY(n),h:Math.round(n.getBoundingClientRect().height),head:(n.innerText||'').trim().replace(/\\s+/g,' ').slice(0,30)}));
  const sels=[...document.querySelectorAll('.ant-select-selection-item,.one_option')].map(n=>({t:(n.innerText||'').trim(),docY:docY(n)}));
  return JSON.stringify({scrollH:document.documentElement.scrollHeight,tabs,cards,sels,head:document.body.innerText.replace(/\\s+/g,' ').slice(0,400)},null,1);
})()`);
console.log('INFO=' + info);

const d = await s.cdp.send('Page.captureScreenshot', { format: 'png' });
fs.writeFileSync('.recon/evidence/biz_tab_overview.png', Buffer.from(d.data, 'base64'));
s.cdp.close();
process.exit(0);
