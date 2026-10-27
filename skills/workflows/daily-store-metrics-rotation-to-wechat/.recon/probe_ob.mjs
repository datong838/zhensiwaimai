#!/usr/bin/env node
/** 诊断12：下单行为/下单时段的表头控件外观 + hover 行为 */
import fs from 'node:fs';
import { session, sleep } from '../scripts/lib/cdp.mjs';

const s = await session({ port: 9230, width: 1440, height: 1500 });
await s.rearm();
const r = await s.ctxForFrame(/melody-stats-next/);
if (r.err) { console.log('CTX_ERR=' + JSON.stringify(r)); process.exit(1); }
const ev = s.frameEval(r.id);
const box = JSON.parse(await s.mainEval(`(()=>{const f=[...document.querySelectorAll('iframe')].find(i=>i.clientWidth>300);const b=f.getBoundingClientRect();return JSON.stringify({x:b.x,y:b.y,w:b.width,h:b.height})})()`));

await ev(`(()=>{window.scrollTo(0,700);return window.scrollY})()`);
await sleep(1200);

// 表头区域截图
let d = await s.cdp.send('Page.captureScreenshot', { format: 'png', clip: { x: box.x, y: box.y + 60, width: box.w, height: 220, scale: 1 } });
fs.writeFileSync('.recon/evidence/distribution_header.png', Buffer.from(d.data, 'base64'));
console.log('saved header');

// 控件 DOM 细节：是否有下拉箭头、是否 disabled、父链 class
const info = await ev(`(()=>{
  const docY=(n)=>{const r=n.getBoundingClientRect();return Math.round(r.y+window.scrollY)};
  const out=[];
  document.querySelectorAll('.one_option,.time_select,.select_date').forEach(n=>{
    const rc=n.getBoundingClientRect();
    const p=n.parentElement;
    out.push({
      cls:(n.className||'').toString(),t:n.innerText.trim(),docY:docY(n),x:Math.round(rc.x),w:Math.round(rc.width),
      parentCls:(p.className||'').toString(),
      parentHTML:p.outerHTML.slice(0,220),
      nextSib:n.nextElementSibling?((n.nextElementSibling.className||'').toString()):null,
      cursor:getComputedStyle(n).cursor,
      listeners:typeof getEventListeners!=='undefined'?'n/a':'n/a'
    });
  });
  return JSON.stringify(out,null,1);
})()`);
console.log('CTRL_INFO=' + info);

// hover 下单行为的 one_option
const p1 = JSON.parse(await ev(`(()=>{const n=[...document.querySelectorAll('.order_behavior .one_option')][0];const r=n.getBoundingClientRect();return JSON.stringify({x:r.x+r.width/2,y:r.y+r.height/2})})()`));
await s.cdp.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: p1.x + box.x, y: p1.y + box.y });
await sleep(1000);
d = await s.cdp.send('Page.captureScreenshot', { format: 'png', clip: { x: box.x, y: box.y + 60, width: box.w, height: 260, scale: 1 } });
fs.writeFileSync('.recon/evidence/orderbehavior_hover.png', Buffer.from(d.data, 'base64'));
console.log('saved hover');
const afterHover = await ev(`JSON.stringify([...document.querySelectorAll('*')].filter(n=>{const cs=getComputedStyle(n);return (cs.position==='absolute'||cs.position==='fixed')&&n.getBoundingClientRect().height>20&&n.getBoundingClientRect().width>40&&n.getBoundingClientRect().height<300&&/近/.test(n.innerText||'')}).map(n=>({cls:(n.className||'').toString().slice(0,40),t:(n.innerText||'').trim().replace(/\\s+/g,'|').slice(0,40)})))`);
console.log('HOVER_POPUP=' + afterHover);
s.cdp.close();
process.exit(0);
