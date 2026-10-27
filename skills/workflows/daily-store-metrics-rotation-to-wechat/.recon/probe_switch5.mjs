#!/usr/bin/env node
/** 诊断17：切店搜索为何无候选（打印输入值 + 下拉文本 + 截图） */
import fs from 'node:fs';
import { session, sleep } from '../scripts/lib/cdp.mjs';

const ID = process.argv[2] || '694471';
const s = await session({ port: 9230, width: 1440, height: 1500 });
await s.rearm();
fs.mkdirSync('.recon/evidence', { recursive: true });

const vis = async () => JSON.parse(await s.mainEval(`(()=>{
  const d=[...document.querySelectorAll('.cook-select-dropdown')].map(n=>{const r=n.getBoundingClientRect();return {w:Math.round(r.width),h:Math.round(r.height),txt:(n.innerText||'').replace(/\\s+/g,' ').slice(0,80)}});
  const i=document.querySelector('input.cook-input');
  const ir=i?i.getBoundingClientRect():null;
  return JSON.stringify({d,iv:ir?{x:Math.round(ir.x),y:Math.round(ir.y),w:Math.round(ir.width),v:i.value}:null,top:(document.querySelector('[class*=shop-name__]')||{}).innerText});
})()`));

console.log('BEFORE=' + JSON.stringify(await vis()));
let st = await vis();
if (!st.d.some((x) => x.w > 100 && x.h > 10)) {
  const SW = JSON.parse(await s.mainEval(`(()=>{const n=document.querySelector('[class*=shop-name__]');const r=n.getBoundingClientRect();return JSON.stringify({x:r.x+r.width/2,y:r.y+r.height/2})})()`));
  await s.clickAt(SW.x, SW.y); await sleep(1800);
}
console.log('OPENED=' + JSON.stringify(await vis()));

const ip = JSON.parse(await s.mainEval(`(()=>{const n=document.querySelector('input.cook-input');const r=n.getBoundingClientRect();return JSON.stringify({x:r.x+r.width/2,y:r.y+r.height/2})})()`));
await s.clickAt(ip.x, ip.y); await sleep(500);
// 先清空再逐字符输入
await s.mainEval(`(()=>{const n=document.querySelector('input.cook-input');n.focus();n.select&&n.select();return 1})()`);
await s.cdp.send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Backspace', code: 'Backspace', windowsVirtualKeyCode: 8 });
await s.cdp.send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Backspace', code: 'Backspace', windowsVirtualKeyCode: 8 });
await sleep(300);
for (const ch of ID) { await s.cdp.send('Input.dispatchKeyEvent', { type: 'char', text: ch }); await sleep(150); }
await sleep(3000);

console.log('AFTER_TYPE=' + JSON.stringify(await vis()));
const d = await s.cdp.send('Page.captureScreenshot', { format: 'png' });
fs.writeFileSync('.recon/evidence/sw_debug.png', Buffer.from(d.data, 'base64'));
s.cdp.close();
process.exit(0);
