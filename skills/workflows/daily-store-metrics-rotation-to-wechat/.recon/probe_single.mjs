#!/usr/bin/env node
/**
 * 诊断8：单店 business-analysis 页的权威模块结构
 * 输出：每张大卡的 cls/docY/h + 内部块标题(h3/period_title/tabs) + 自带 select + 街区命中上下文
 */
import fs from 'node:fs';
import { session, sleep } from '../scripts/lib/cdp.mjs';

const s = await session({ port: 9230, width: 1440, height: 1500 });
await s.rearm();
let r = await s.ctxForFrame(/melody-stats-next/);
if (r.err) { console.log('CTX_ERR=' + JSON.stringify(r)); process.exit(1); }
let ev = s.frameEval(r.id);
let inner = await ev('location.href');
console.log('INNER_URL=' + inner);

if (/\/chain\//.test(inner)) {
  console.log('=> chain scope detected, hard reload');
  await s.cdp.send('Page.reload', { ignoreCache: true });
  await sleep(14000);
  await s.rearm();
  r = await s.ctxForFrame(/melody-stats-next/);
  ev = s.frameEval(r.id);
  console.log('INNER_URL2=' + await ev('location.href'));
}

const dump = await ev(`(()=>{
  const docY=(n)=>{const r=n.getBoundingClientRect();return Math.round(r.y+window.scrollY)};
  const cards=[...document.querySelectorAll('.card-border')].map(c=>{
    const cr=c.getBoundingClientRect();
    const titles=[...c.querySelectorAll('.h3,.period_title,.ant-tabs-tab')].filter(n=>{
      const t=(n.innerText||'').trim();
      return t && t.length<12 && t.indexOf('\\n')<0 && n.getBoundingClientRect().width>0;
    }).map(n=>({t:(n.innerText||'').trim(),cls:(n.className||'').toString().slice(0,40),docY:docY(n),x:Math.round(n.getBoundingClientRect().x)}));
    const sels=[...c.querySelectorAll('.ant-select')].map(n=>{
      const it=n.querySelector('.ant-select-selection-item');
      return {docY:docY(n),x:Math.round(n.getBoundingClientRect().x),val:it?it.innerText.trim():null};
    });
    const radios=[...c.querySelectorAll('.ant-radio-button-wrapper')].map(n=>({t:(n.innerText||'').trim(),checked:n.className.indexOf('checked')>=0,docY:docY(n)}));
    return {cls:(c.className||'').toString().replace('card-border','').trim(),docY:Math.round(cr.y+window.scrollY),h:Math.round(cr.height),titles,sels,radios};
  });
  // 街区命中上下文
  const hits=[];
  const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
  let n;
  while(n=walker.nextNode()){
    if(n.nodeValue && n.nodeValue.indexOf('街区')>=0){
      let p=n.parentElement, path=[];
      for(let i=0;i<5&&p;i++,p=p.parentElement) path.push((p.className||'').toString().split(' ')[0]);
      hits.push({txt:n.nodeValue.trim().slice(0,20),docY:docY(n.parentElement),path:path.join('<')});
    }
  }
  return JSON.stringify({scrollH:document.documentElement.scrollHeight,cards,hits:hits.slice(0,6)},null,1);
})()`);
fs.writeFileSync('.recon/single_structure.json', dump);
console.log(dump.slice(0, 6000));
s.cdp.close();
process.exit(0);
