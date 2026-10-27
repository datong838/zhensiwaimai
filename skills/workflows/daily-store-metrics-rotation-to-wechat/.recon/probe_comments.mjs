#!/usr/bin/env node
/** 诊断21：单店 顾客评价页（comments）结构取证 */
import fs from 'node:fs';
import { session, sleep } from '../scripts/lib/cdp.mjs';

const SHOP = process.argv[2] || '694471';
const s = await session({ port: 9230, width: 1440, height: 1500 });
await s.rearm();

const before = await s.mainEval('location.href');
console.log('BEFORE=' + before);

// 换路由：path 不同 ⇒ 会真重载；再补一次硬刷新保证 iframe 作用域重建
await s.mainEval(`location.href = 'https://melody.shop.ele.me/app/shop/${SHOP}/comments#app.shop.comments'`);
await sleep(9000);
await s.cdp.send('Page.reload', { ignoreCache: true });
await sleep(14000);
await s.rearm();

console.log('AFTER=' + await s.mainEval('location.href'));
console.log('TOP=' + await s.mainEval(`(()=>{const n=document.querySelector('[class*=shop-name__]');return n?n.innerText.trim():''})()`));
const frames = JSON.parse(await s.mainEval(`JSON.stringify([...document.querySelectorAll('iframe')].map(i=>({src:(i.src||'').slice(0,90),w:i.clientWidth})))`));
console.log('FRAMES=' + JSON.stringify(frames));

const r = await s.ctxForFrame(/melody-comment/);
if (r.err) { console.log('CTX_ERR=' + JSON.stringify(r)); process.exit(1); }
const ev = s.frameEval(r.id);
console.log('INNER=' + await ev('location.href'));
console.log('READY=' + await ev(`String(document.readyState)`));

// 弹窗 / 展开
console.log('POPUP=' + await ev(`(()=>{const b=[...document.querySelectorAll('button')].find(x=>(x.innerText||'').trim()==='知道了');if(b){b.click();return 'closed'}return 'none'})()`));
await sleep(1200);

const struct = await ev(`(()=>{
  const docY=(n)=>{const r=n.getBoundingClientRect();return Math.round(r.y+window.scrollY)};
  const cards=[...document.querySelectorAll('.card-border,[class*=card]')].filter(n=>n.getBoundingClientRect().width>500&&n.getBoundingClientRect().height>60);
  const uniq=[];const seen=new Set();
  for(const c of cards){const k=(c.className||'').toString()+'|'+Math.round(c.getBoundingClientRect().height);if(seen.has(k))continue;seen.add(k);
    uniq.push({cls:(c.className||'').toString().slice(0,45),docY:docY(c),h:Math.round(c.getBoundingClientRect().height)});}
  const tabs=[...document.querySelectorAll('[class*=tab]')].filter(n=>{const t=(n.innerText||'').trim();return t&&t.length<10&&n.getBoundingClientRect().width>0&&n.getBoundingClientRect().width<200}).map(n=>(n.innerText||'').trim()).slice(0,12);
  const bodyLen=document.body.innerText.length;
  const head=document.body.innerText.replace(/\\s+/g,' ').slice(0,220);
  return JSON.stringify({scrollH:document.documentElement.scrollHeight,cards:uniq.slice(0,12),tabs,bodyLen,head},null,1);
})()`);
console.log('STRUCT=' + struct);

const d = await s.cdp.send('Page.captureScreenshot', { format: 'png' });
fs.mkdirSync('.recon/evidence', { recursive: true });
fs.writeFileSync('.recon/evidence/comments_' + SHOP + '.png', Buffer.from(d.data, 'base64'));
console.log('saved comments_' + SHOP + '.png');
s.cdp.close();
process.exit(0);
