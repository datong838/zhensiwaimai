#!/usr/bin/env node
/** 诊断10：自定义 .select>.one_option 时间控件的交互方式 */
import { session, sleep } from '../scripts/lib/cdp.mjs';

const s = await session({ port: 9230, width: 1440, height: 1500 });
await s.rearm();
const r = await s.ctxForFrame(/melody-stats-next/);
if (r.err) { console.log('CTX_ERR=' + JSON.stringify(r)); process.exit(1); }
const ev = s.frameEval(r.id);

const find = `(()=>{
  const docY=(n)=>{const r=n.getBoundingClientRect();return Math.round(r.y+window.scrollY)};
  const n=[...document.querySelectorAll('.interactive_behavior .one_option')][0];
  if(!n) return 'nf';
  const r=n.getBoundingClientRect();
  const box=[...document.querySelectorAll('iframe')].length?'':'' ;
  return JSON.stringify({x:r.x+r.width/2,y:r.y+r.height/2,docY:docY(n),t:n.innerText.trim(),html:n.parentElement.outerHTML.slice(0,400)});
})()`;
const p = await ev(find);
console.log('CTRL=' + p);
if (p === 'nf') process.exit(2);
const P = JSON.parse(p);

const box = JSON.parse(await s.mainEval(`(()=>{const f=[...document.querySelectorAll('iframe')].find(i=>i.clientWidth>300);const b=f.getBoundingClientRect();return JSON.stringify({x:b.x,y:b.y})})()`));
// 先滚到视野
await ev(`(()=>{const n=document.querySelector('.interactive_behavior');n.scrollIntoView({block:'center'});return 'ok'})()`);
await sleep(1200);
const p2 = JSON.parse(await ev(find));
await s.clickAt(p2.x + box.x, p2.y + box.y);
await sleep(1200);

const popup = await ev(`(()=>{
  const docY=(n)=>{const r=n.getBoundingClientRect();return Math.round(r.y+window.scrollY)};
  const out=[];
  document.querySelectorAll('*').forEach(n=>{
    const t=(n.innerText||'').trim();
    if(!/^(近7日|近30日|近90日)$/.test(t)) return;
    if(n.children.length>0) return;
    const rc=n.getBoundingClientRect();
    if(!rc.width) return;
    const cls=(n.className||'').toString().split(' ')[0];
    if(!/one_option|ant-select-item-option|option/.test(cls)) return;
    out.push({t,cls,docY:docY(n),x:Math.round(rc.x),y:Math.round(rc.y),w:Math.round(rc.width),h:Math.round(rc.height)});
  });
  // 弹层容器
  const ctrls=[...document.querySelectorAll('.one_option')].map(n=>({t:n.innerText.trim(),docY:docY(n),x:Math.round(n.getBoundingClientRect().x)}));
  return JSON.stringify({options:out,allOneOptions:ctrls},null,1);
})()`);
console.log('AFTER_CLICK=' + popup);
s.cdp.close();
process.exit(0);
