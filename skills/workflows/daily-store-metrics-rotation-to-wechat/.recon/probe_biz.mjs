#!/usr/bin/env node
/** 诊断22：进入 数据中心 > 经营分析，摸清 总览/流量/商品/服务 四个 tab 的结构 */
import fs from 'node:fs';
import { session, sleep } from '../scripts/lib/cdp.mjs';

const s = await session({ port: 9230, width: 1440, height: 1500 });
await s.rearm();
fs.mkdirSync('.recon/evidence', { recursive: true });

// 复用已开页 + 左侧菜单点击（不新开标签）
const menu = await s.mainEval(`(()=>{
  const cands=[...document.querySelectorAll('a,li,div,span')].filter(n=>{
    const t=(n.innerText||'').trim();
    return t==='经营分析' && n.children.length<=1 && n.getBoundingClientRect().width>0;
  });
  if(!cands.length) return 'nf';
  const r=cands[0].getBoundingClientRect();
  return JSON.stringify({x:r.x+r.width/2,y:r.y+r.height/2,txt:cands[0].innerText.trim()});
})()`);
console.log('MENU=' + menu);
if (menu === 'nf') { console.log('menu-not-found'); process.exit(1); }
const M = JSON.parse(menu);
await s.clickAt(M.x, M.y);
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
  const cards=[...document.querySelectorAll('.card-border')].map(n=>({cls:(n.className||'').toString().replace('card-border','').trim(),docY:docY(n),h:Math.round(n.getBoundingClientRect().height),head:(n.innerText||'').trim().replace(/\\s+/g,' ').slice(0,26)}));
  const sels=[...document.querySelectorAll('.ant-select-selection-item')].map(n=>({t:(n.innerText||'').trim(),docY:docY(n)}));
  return JSON.stringify({scrollH:document.documentElement.scrollHeight,tabs,cards,sels,head:document.body.innerText.replace(/\\s+/g,' ').slice(0,300)},null,1);
})()`);
console.log('INFO=' + info);

const d = await s.cdp.send('Page.captureScreenshot', { format: 'png' });
fs.writeFileSync('.recon/evidence/biz_overview.png', Buffer.from(d.data, 'base64'));
console.log('saved biz_overview.png');
s.cdp.close();
process.exit(0);
