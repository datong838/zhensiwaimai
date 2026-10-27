#!/usr/bin/env node
/** 诊断19：正确输入后截图，看搜索到底有没有过滤 */
import fs from 'node:fs';
import { session, sleep } from '../scripts/lib/cdp.mjs';

const ID = process.argv[2] || '694471';
const s = await session({ port: 9230, width: 1440, height: 1500 });
await s.rearm();
fs.mkdirSync('.recon/evidence', { recursive: true });

const SEL = `[...document.querySelectorAll('input')].find(n=>n.placeholder==='搜索店铺名称/ID')`;
const rect = async () => await s.mainEval(`(()=>{const n=${SEL};if(!n)return null;const r=n.getBoundingClientRect();return r.width>100?JSON.stringify({x:r.x+r.width/2,y:r.y+r.height/2,w:Math.round(r.width),v:n.value}):null})()`);

let r = await rect();
if (!r) {
  const SW = JSON.parse(await s.mainEval(`(()=>{const n=document.querySelector('[class*=shop-name__]');const b=n.getBoundingClientRect();return JSON.stringify({x:b.x+b.width/2,y:b.y+b.height/2})})()`));
  await s.clickAt(SW.x, SW.y);
  await sleep(2000);
  r = await rect();
}
console.log('INPUT=' + r);
if (!r) { console.log('input still hidden'); process.exit(2); }
const R = JSON.parse(r);
await s.clickAt(R.x, R.y);
await sleep(400);
await s.mainEval(`(()=>{
  const n=${SEL};
  const setter=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
  n.focus(); setter.call(n, ${JSON.stringify(ID)});
  n.dispatchEvent(new Event('input',{bubbles:true}));
  return n.value;
})()`);
await sleep(3500);
console.log('AFTER=' + await rect());
console.log('DD_TEXT=' + await s.mainEval(`(()=>{const dd=[...document.querySelectorAll('.cook-select-dropdown')].find(n=>n.getBoundingClientRect().height>10);return dd?dd.innerText.replace(/\\s+/g,' ').slice(0,400):'none'})()`));
const d = await s.cdp.send('Page.captureScreenshot', { format: 'png' });
fs.writeFileSync('.recon/evidence/sw_search_state.png', Buffer.from(d.data, 'base64'));
s.cdp.close();
process.exit(0);
