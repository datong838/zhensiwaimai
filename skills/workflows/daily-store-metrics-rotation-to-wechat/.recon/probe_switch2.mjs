#!/usr/bin/env node
/** 诊断14：在切换器里搜店铺 ID，看候选结构 */
import fs from 'node:fs';
import { session, sleep } from '../scripts/lib/cdp.mjs';

const SHOP_ID = process.argv[2] || '694471';
const s = await session({ port: 9230, width: 1440, height: 1500 });
await s.rearm();
fs.mkdirSync('.recon/evidence', { recursive: true });

// 打开切换器
const SW = JSON.parse(await s.mainEval(`(()=>{const n=document.querySelector('[class*=shop-name__]');const r=n.getBoundingClientRect();return JSON.stringify({x:r.x+r.width/2,y:r.y+r.height/2})})()`));
await s.clickAt(SW.x, SW.y);
await sleep(1500);

// 聚焦搜索框并输入
const inp = JSON.parse(await s.mainEval(`(()=>{const n=document.querySelector('input.cook-input');const r=n.getBoundingClientRect();return JSON.stringify({x:r.x+r.width/2,y:r.y+r.height/2})})()`));
await s.clickAt(inp.x, inp.y);
await sleep(400);
await s.mainEval(`(()=>{
  const n=document.querySelector('input.cook-input');
  const setter=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
  setter.call(n, ${JSON.stringify(SHOP_ID)});
  n.dispatchEvent(new Event('input',{bubbles:true}));
  return n.value;
})()`);
await sleep(2500);

const cands = await s.mainEval(`(()=>{
  const pop=document.querySelector('.orgTreePopup');
  if(!pop) return 'no-popup';
  const rows=[...pop.querySelectorAll('*')].filter(n=>{
    const t=(n.innerText||'').trim();
    return t && n.children.length<=2 && n.getBoundingClientRect().width>100 && n.getBoundingClientRect().height<60;
  }).slice(0,25).map(n=>{
    const r=n.getBoundingClientRect();
    return {cls:(n.className||'').toString().slice(0,45),t:t.replace(/\s+/g,'|').slice(0,40),x:Math.round(r.x),y:Math.round(r.y),h:Math.round(r.height)};
  });
  return JSON.stringify({txt:pop.innerText.replace(/\s+/g,' ').slice(0,300),rows},null,1);
})()`);
console.log('CANDS=' + cands);

const d = await s.cdp.send('Page.captureScreenshot', { format: 'png' });
fs.writeFileSync('.recon/evidence/switcher_search.png', Buffer.from(d.data, 'base64'));
console.log('saved switcher_search.png');
s.cdp.close();
process.exit(0);
