#!/usr/bin/env node
/** 诊断9：互动行为卡的时间控件类型 + 全页时间控件清单 */
import { session, sleep } from '../scripts/lib/cdp.mjs';

const s = await session({ port: 9230, width: 1440, height: 1500 });
await s.rearm();
const r = await s.ctxForFrame(/melody-stats-next/);
if (r.err) { console.log('CTX_ERR=' + JSON.stringify(r)); process.exit(1); }
const ev = s.frameEval(r.id);
console.log('URL=' + await ev('location.href'));

const map = await ev(`(()=>{
  const docY=(n)=>{const r=n.getBoundingClientRect();return Math.round(r.y+window.scrollY)};
  const cards=[...document.querySelectorAll('.card-border')];
  const owner=(n)=>{for(const c of cards){if(c.contains(n))return (c.className||'').toString().replace('card-border','').trim()}return '?'};
  const ctrls=[];
  document.querySelectorAll('*').forEach(n=>{
    const t=(n.innerText||'').trim();
    if(!/^(近7日|近30日|近90日)$/.test(t)) return;
    if(n.children.length>0) return;
    const cs=getComputedStyle(n);
    if(cs.display==='none'||cs.visibility==='hidden') return;
    const rc=n.getBoundingClientRect();
    if(!rc.width) return;
    // 只保留看起来像控件的：自身或祖先有 select / radio
    let p=n, chain=[], isCtrl=false;
    for(let i=0;i<5&&p;i++,p=p.parentElement){
      const cls=(p.className||'').toString();
      chain.push(cls.split(' ')[0]);
      if(/ant-select|ant-radio-button-wrapper|\\bselect\\b|one_option|time_select/.test(cls)) isCtrl=true;
    }
    if(!isCtrl) return;
    ctrls.push({card:owner(n),tag:n.tagName,chain:chain.join('<'),docY:docY(n),x:Math.round(rc.x),t});
  });
  // 互动行为卡内部结构
  const ib=document.querySelector('.interactive_behavior');
  const ibDump=ib?[...ib.querySelectorAll('*')].filter(n=>{
    const rc=n.getBoundingClientRect();
    return rc.width>0&&rc.height>0&&(n.innerText||'').trim().length<14&&n.children.length<=1;
  }).slice(0,14).map(n=>({t:(n.innerText||'').trim().replace(/\\s+/g,'|'),cls:(n.className||'').toString().slice(0,40),docY:docY(n),x:Math.round(n.getBoundingClientRect().x)})):null;
  return JSON.stringify({ctrls,ibDump},null,1);
})()`);
console.log(map);
s.cdp.close();
process.exit(0);
