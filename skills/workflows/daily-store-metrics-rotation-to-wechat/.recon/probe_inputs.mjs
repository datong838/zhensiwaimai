#!/usr/bin/env node
/** 诊断18：列出所有输入框（含 rect/placeholder/value）+ 当前截图 */
import fs from 'node:fs';
import { session, sleep } from '../scripts/lib/cdp.mjs';

const s = await session({ port: 9230, width: 1440, height: 1500 });
await s.rearm();
const all = await s.mainEval(`(()=>{
  const out=[...document.querySelectorAll('input')].map(n=>{
    const r=n.getBoundingClientRect();
    return {ph:n.placeholder||'',cls:(n.className||'').toString().slice(0,40),val:n.value,
      x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),vis:r.width>0&&r.height>0};
  });
  const dds=[...document.querySelectorAll('.cook-select-dropdown')].map(n=>{const r=n.getBoundingClientRect();return {w:Math.round(r.width),h:Math.round(r.height),x:Math.round(r.x),y:Math.round(r.y)}});
  return JSON.stringify({inputs:out,dropdowns:dds},null,1);
})()`);
console.log(all);
const d = await s.cdp.send('Page.captureScreenshot', { format: 'png' });
fs.writeFileSync('.recon/evidence/sw_inputs.png', Buffer.from(d.data, 'base64'));
s.cdp.close();
process.exit(0);
