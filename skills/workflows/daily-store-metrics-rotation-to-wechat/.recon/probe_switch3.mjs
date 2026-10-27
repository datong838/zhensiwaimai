#!/usr/bin/env node
/** 诊断15：状态感知地打开切换器 → 搜 ID → 列候选 */
import fs from 'node:fs';
import { session, sleep } from '../scripts/lib/cdp.mjs';

const SHOP_ID = process.argv[2] || '694471';
const s = await session({ port: 9230, width: 1440, height: 1500 });
await s.rearm();
fs.mkdirSync('.recon/evidence', { recursive: true });

const hasPopup = async () => !!(await s.mainEval(`!!document.querySelector('.orgTreePopup')`));

if (!(await hasPopup())) {
  const SW = JSON.parse(await s.mainEval(`(()=>{const n=document.querySelector('[class*=shop-name__]');const r=n.getBoundingClientRect();return JSON.stringify({x:r.x+r.width/2,y:r.y+r.height/2})})()`));
  await s.clickAt(SW.x, SW.y);
  await sleep(1600);
}
console.log('POPUP_OPEN=' + await hasPopup());

const inp = JSON.parse(await s.mainEval(`(()=>{const n=document.querySelector('input.cook-input');if(!n)return 'nf';const r=n.getBoundingClientRect();return JSON.stringify({x:r.x+r.width/2,y:r.y+r.height/2,w:r.width})})()`));
console.log('INPUT=' + JSON.stringify(inp));
if (inp !== 'nf') {
  await s.clickAt(inp.x, inp.y);
  await sleep(300);
  await s.mainEval(`(()=>{
    const n=document.querySelector('input.cook-input');
    const setter=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
    n.focus(); setter.call(n, ${JSON.stringify(SHOP_ID)});
    n.dispatchEvent(new Event('input',{bubbles:true}));
    n.dispatchEvent(new KeyboardEvent('keyup',{bubbles:true,key:'1'}));
    return n.value;
  })()`);
  await sleep(3000);
}

const dump = await s.mainEval(`(()=>{
  const pop=document.querySelector('.orgTreePopup');
  if(!pop) return JSON.stringify({err:'popup-gone'});
  const items=[...pop.querySelectorAll('[class*=tree-node],[class*=cook-select-item],[class*=node]')].slice(0,12).map(n=>{
    const t=(n.innerText||'').trim().replace(/\s+/g,'|');
    const r=n.getBoundingClientRect();
    return {cls:(n.className||'').toString().slice(0,50),t:t.slice(0,40),x:Math.round(r.x),y:Math.round(r.y),h:Math.round(r.height)};
  }).filter(x=>x.t);
  return JSON.stringify({txt:pop.innerText.replace(/\s+/g,' ').slice(0,400),items},null,1);
})()`);
console.log('DUMP=' + dump);
const d = await s.cdp.send('Page.captureScreenshot', { format: 'png' });
fs.writeFileSync('.recon/evidence/switcher_search2.png', Buffer.from(d.data, 'base64'));
s.cdp.close();
process.exit(0);
