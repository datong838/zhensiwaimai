#!/usr/bin/env node
/** 诊断13：右上角店铺切换器的 DOM 结构 */
import fs from 'node:fs';
import { session, sleep } from '../scripts/lib/cdp.mjs';

const s = await session({ port: 9230, width: 1440, height: 1500 });
await s.rearm();
fs.mkdirSync('.recon/evidence', { recursive: true });

const topName = await s.mainEval(`(()=>{const n=document.querySelector('[class*=shop-name__]');return n?n.innerText.trim():''})()`);
console.log('TOPNAME=' + topName);
const switcher = await s.mainEval(`(()=>{
  const n=document.querySelector('[class*=shop-name__]');
  if(!n) return 'nf';
  let p=n, chain=[];
  for(let i=0;i<5&&p;i++,p=p.parentElement) chain.push(((p.className||'').toString()||p.tagName).slice(0,50));
  const r=n.getBoundingClientRect();
  return JSON.stringify({x:r.x+r.width/2,y:r.y+r.height/2,rect:[Math.round(r.x),Math.round(r.y),Math.round(r.width),Math.round(r.height)],chain});
})()`);
console.log('SWITCHER=' + switcher);

const SW = JSON.parse(switcher);
await s.clickAt(SW.x, SW.y);
await sleep(1800);

const panel = await s.mainEval(`(()=>{
  const inputs=[...document.querySelectorAll('input')].map(n=>{
    const r=n.getBoundingClientRect();
    return {ph:n.placeholder||'',cls:(n.className||'').toString().slice(0,50),x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),vis:r.width>0};
  }).filter(x=>x.vis);
  const pops=[...document.querySelectorAll('*')].filter(n=>{
    const cs=getComputedStyle(n);
    const r=n.getBoundingClientRect();
    return (cs.position==='absolute'||cs.position==='fixed')&&r.width>200&&r.height>150&&r.height<900&&r.width<900&&r.y>=0;
  }).slice(0,5).map(n=>({cls:(n.className||'').toString().slice(0,60),rect:[Math.round(n.getBoundingClientRect().x),Math.round(n.getBoundingClientRect().y),Math.round(n.getBoundingClientRect().width),Math.round(n.getBoundingClientRect().height)],txt:(n.innerText||'').trim().replace(/\\s+/g,' ').slice(0,80)}));
  return JSON.stringify({inputs,pops},null,1);
})()`);
console.log('PANEL=' + panel);

const d = await s.cdp.send('Page.captureScreenshot', { format: 'png' });
fs.writeFileSync('.recon/evidence/switcher_open.png', Buffer.from(d.data, 'base64'));
console.log('saved switcher_open.png');
s.cdp.close();
process.exit(0);
