#!/usr/bin/env node
/** 诊断16：分步截图 + 下拉容器可见性真判据 */
import fs from 'node:fs';
import { session, sleep } from '../scripts/lib/cdp.mjs';

const s = await session({ port: 9230, width: 1440, height: 1500 });
await s.rearm();
fs.mkdirSync('.recon/evidence', { recursive: true });
const shot = async (n) => { const d = await s.cdp.send('Page.captureScreenshot', { format: 'png' }); fs.writeFileSync(`.recon/evidence/${n}.png`, Buffer.from(d.data, 'base64')); };

const state = async () => s.mainEval(`(()=>{
  const ds=[...document.querySelectorAll('.cook-select-dropdown,.orgTreePopup,[class*=orgTree]')].map(n=>{
    const r=n.getBoundingClientRect();const cs=getComputedStyle(n);
    return {cls:(n.className||'').toString().slice(0,60),x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),h:Math.round(r.height),disp:cs.display,vis:cs.visibility,op:cs.opacity,pe:cs.pointerEvents};
  });
  const inp=document.querySelector('input.cook-input');
  const ir=inp?inp.getBoundingClientRect():null;
  return JSON.stringify({dropdowns:ds,input:ir?{x:Math.round(ir.x),y:Math.round(ir.y),w:Math.round(ir.width),h:Math.round(ir.height),val:inp.value}:null});
})()`);

await shot('sw_0_before');
console.log('S0=' + await state());

const SW = JSON.parse(await s.mainEval(`(()=>{const n=document.querySelector('[class*=shop-name__]');const r=n.getBoundingClientRect();return JSON.stringify({x:r.x+r.width/2,y:r.y+r.height/2})})()`));
await s.clickAt(SW.x, SW.y);
await sleep(2000);
await shot('sw_1_clicked');
console.log('S1=' + await state());

// 找弹出的输入框并聚焦
const ip = JSON.parse(await s.mainEval(`(()=>{const n=document.querySelector('input.cook-input');const r=n.getBoundingClientRect();return JSON.stringify({x:r.x+r.width/2,y:r.y+r.height/2})})()`));
await s.clickAt(ip.x, ip.y);
await sleep(500);
for (const ch of '694471') { await s.cdp.send('Input.dispatchKeyEvent', { type: 'char', text: ch }); await sleep(120); }
await sleep(2500);
await shot('sw_2_typed');
console.log('S2=' + await state());
console.log('VAL=' + await s.mainEval(`document.querySelector('input.cook-input').value`));
console.log('POPUP_TXT=' + await s.mainEval(`(()=>{const n=document.querySelector('.cook-select-dropdown');return n?(n.innerText||'').replace(/\\s+/g,' ').slice(0,300):'none'})()`));
s.cdp.close();
process.exit(0);
