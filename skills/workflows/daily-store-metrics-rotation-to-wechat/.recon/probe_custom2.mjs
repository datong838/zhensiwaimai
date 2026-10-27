#!/usr/bin/env node
/** 诊断11：点击自定义时间控件后截图取证 */
import fs from 'node:fs';
import { session, sleep } from '../scripts/lib/cdp.mjs';

const s = await session({ port: 9230, width: 1440, height: 1500 });
await s.rearm();
const r = await s.ctxForFrame(/melody-stats-next/);
if (r.err) { console.log('CTX_ERR=' + JSON.stringify(r)); process.exit(1); }
const ev = s.frameEval(r.id);

await ev(`(()=>{const n=document.querySelector('.interactive_behavior');n.scrollIntoView({block:'center'});return 1})()`);
await sleep(1200);
const pos = JSON.parse(await ev(`(()=>{const n=document.querySelector('.interactive_behavior .one_option');const r=n.getBoundingClientRect();return JSON.stringify({x:r.x+r.width/2,y:r.y+r.height/2,docY:Math.round(r.y+window.scrollY)})})()`));
const box = JSON.parse(await s.mainEval(`(()=>{const f=[...document.querySelectorAll('iframe')].find(i=>i.clientWidth>300);const b=f.getBoundingClientRect();return JSON.stringify({x:b.x,y:b.y,w:b.width,h:b.height})})()`));
console.log('POS=' + JSON.stringify(pos) + ' BOX=' + JSON.stringify(box));

const grab = async (name) => {
  const d = await s.cdp.send('Page.captureScreenshot', { format: 'png', clip: { x: box.x, y: box.y, width: box.w, height: Math.min(box.h, 900), scale: 1 } });
  fs.writeFileSync(`.recon/evidence/${name}.png`, Buffer.from(d.data, 'base64'));
  console.log('saved ' + name);
};
fs.mkdirSync('.recon/evidence', { recursive: true });

await grab('custom_before');
await s.clickAt(pos.x + box.x, pos.y + box.y);
await sleep(1500);
await grab('custom_after_click');

// 看 .select 的 class 变化 + 是否有新增 absolute 层
const st = await ev(`(()=>{
  const sel=document.querySelector('.interactive_behavior .one_option').parentElement;
  const nodes=[...document.querySelectorAll('.interactive_behavior *')];
  const abs=nodes.filter(n=>{const cs=getComputedStyle(n);return (cs.position==='absolute'||cs.position==='fixed')&&n.getBoundingClientRect().width>30&&n.getBoundingClientRect().height>20});
  return JSON.stringify({selCls:sel.className,selHTML:sel.outerHTML.slice(0,500),absCount:abs.length,abs:abs.slice(0,3).map(n=>({cls:(n.className||'').toString().slice(0,40),txt:(n.innerText||'').trim().replace(/\\s+/g,'|').slice(0,40)}))},null,1);
})()`);
console.log('STATE=' + st);
s.cdp.close();
process.exit(0);
