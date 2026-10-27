#!/usr/bin/env node
/** 证据截图：单店 business-analysis 上下半页，确认时间口径都是近30日 */
import fs from 'node:fs';
import { session, sleep } from '../scripts/lib/cdp.mjs';

const TAG = process.argv[2] || 'verify30';
const s = await session({ port: 9230, width: 1440, height: 1500 });
await s.rearm();
const r = await s.ctxForFrame(/melody-stats-next/);
if (r.err) { console.log('CTX_ERR'); process.exit(1); }
const ev = s.frameEval(r.id);
const box = JSON.parse(await s.mainEval(`(()=>{const f=[...document.querySelectorAll('iframe')].find(i=>i.clientWidth>300);const b=f.getBoundingClientRect();return JSON.stringify({x:b.x,y:b.y,w:b.width,h:b.height})})()`));
fs.mkdirSync('.recon/evidence', { recursive: true });

const shotAt = async (scrollY, name) => {
  await ev(`window.scrollTo(0, ${scrollY})`);
  await sleep(1600);
  const d = await s.cdp.send('Page.captureScreenshot', { format: 'png', clip: { x: box.x, y: box.y, width: box.w, height: box.h, scale: 1 } });
  fs.writeFileSync(`.recon/evidence/${name}.png`, Buffer.from(d.data, 'base64'));
  console.log('saved ' + name);
};

await shotAt(0, TAG + '_A_top');
await shotAt(1050, TAG + '_B_mid');
await shotAt(1900, TAG + '_C_bottom');

// 文本快照：所有时间控件现值
console.log('CTRL_VALUES=' + await ev(`JSON.stringify([...document.querySelectorAll('.ant-select-selection-item,.one_option')].filter(n=>/^近\\d+日$/.test((n.innerText||'').trim())&&n.getBoundingClientRect().width>0).map(n=>({t:n.innerText.trim(),docY:Math.round(n.getBoundingClientRect().y+window.scrollY)})))`));
console.log('TOP=' + await s.mainEval(`(()=>{const n=document.querySelector('[class*=shop-name__]');return n?n.innerText.trim():''})()`));
s.cdp.close();
process.exit(0);
