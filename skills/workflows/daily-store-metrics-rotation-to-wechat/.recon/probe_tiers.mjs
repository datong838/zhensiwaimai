#!/usr/bin/env node
/**
 * 探测：同一家店用不同层级关键词搜索，平台返回什么
 * 用法: node probe_tiers.mjs "关键词1" "关键词2" ...
 */
import { session, sleep } from '../scripts/lib/cdp.mjs';

const kws = process.argv.slice(2);
if (!kws.length) { console.error('need keywords'); process.exit(2); }

const s = await session({ port: 9230, width: 1440, height: 1500 });
await s.rearm();

const INPUT_SEL = `[...document.querySelectorAll('input')].find(n=>n.placeholder==='搜索店铺名称/ID')`;
const popupOpen = () => s.mainEval(`(()=>{
  const d=[...document.querySelectorAll('.cook-select-dropdown')].map(n=>{const r=n.getBoundingClientRect();return {w:Math.round(r.width),h:Math.round(r.height)}});
  return d.some(x=>x.w>100&&x.h>10);
})()`);

// 确保弹层打开
if (!(await popupOpen())) {
  const SW = JSON.parse(await s.mainEval(`(()=>{const n=document.querySelector('[class*=shop-name__]');if(!n)return 'nf';const r=n.getBoundingClientRect();return JSON.stringify({x:r.x+r.width/2,y:r.y+r.height/2})})()`));
  if (SW === 'nf') { console.error('FAIL switcher-not-found'); process.exit(4); }
  await s.clickAt(SW.x, SW.y);
  await sleep(1600);
}
if (!(await popupOpen())) { console.error('FAIL popup-not-open'); process.exit(4); }

// 等输入框可见
const ipRect = await s.waitFor(async () => {
  const r = await s.mainEval(`(()=>{const n=${INPUT_SEL};if(!n)return null;const r=n.getBoundingClientRect();return r.width>100?JSON.stringify({x:r.x+r.width/2,y:r.y+r.height/2}):null})()`);
  return r ? JSON.parse(r) : null;
}, { timeout: 10000, interval: 500, label: 'input' });
if (!ipRect) { console.error('FAIL input-not-visible'); process.exit(4); }

const setVal = (v) => s.mainEval(`(()=>{
  const n=${INPUT_SEL};
  const setter=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
  n.focus();
  setter.call(n, ${JSON.stringify(v)});
  n.dispatchEvent(new Event('input',{bubbles:true}));
  return n.value;
})()`);

const readRows = () => s.mainEval(`(()=>{
  const dd=[...document.querySelectorAll('.cook-select-dropdown')].find(n=>n.getBoundingClientRect().height>10);
  if(!dd) return JSON.stringify({err:'no-dd'});
  const STATUS=/营业中|已下线|暂停营业|已打烊/;
  const cands=[...dd.querySelectorAll('div,a,li')].filter(n=>{
    if(/cook-cascader-menu-item/.test((n.className||'').toString())) return false;
    const t=(n.innerText||'').trim();
    const rc=n.getBoundingClientRect();
    if(!t || !STATUS.test(t)) return false;
    if(rc.width<150 || rc.height<20 || rc.height>90) return false;
    if(n.children.length>5) return false;
    return true;
  });
  const seen=new Set(); const out=[];
  for(const n of cands){
    const t=(n.innerText||'').replace(/\\s+/g,'|').trim();
    if(seen.has(t)) continue;
    seen.add(t);
    const rc=n.getBoundingClientRect();
    out.push({t, x:Math.round(rc.x+rc.width/2), y:Math.round(rc.y+rc.height/2)});
  }
  // 是否出现「暂无数据 / 无搜索结果」
  const raw=dd.innerText.replace(/\\s+/g,' ').slice(0,200);
  return JSON.stringify({n:out.length, rows:out.slice(0,10), raw});
})()`);

for (const kw of kws) {
  await setVal(kw);
  await sleep(3200);
  const r = JSON.parse(await readRows());
  console.log('=== KW=' + JSON.stringify(kw) + ' ===');
  console.log(JSON.stringify(r, null, 1));
}

s.cdp.close();
process.exit(0);
