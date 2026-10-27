#!/usr/bin/env node
/**
 * 探切换器弹层的「运营组织」级联树：当前账号到底能切多少家店
 */
import { session, sleep } from '../scripts/lib/cdp.mjs';

const s = await session({ port: 9230, width: 1440, height: 1500 });
await s.rearm();

const INPUT_SEL = `[...document.querySelectorAll('input')].find(n=>n.placeholder==='搜索店铺名称/ID')`;
const open = () => s.mainEval(`(()=>[...document.querySelectorAll('.cook-select-dropdown')].some(n=>n.getBoundingClientRect().height>10))()`);

if (!(await open())) {
  const SW = JSON.parse(await s.mainEval(`(()=>{const n=document.querySelector('[class*=shop-name__]');const r=n.getBoundingClientRect();return JSON.stringify({x:r.x+r.width/2,y:r.y+r.height/2})})()`));
  await s.clickAt(SW.x, SW.y);
  await sleep(1800);
}
console.log('OPEN=' + await open());

// 清空搜索框，回到默认级联树视图
await s.mainEval(`(()=>{
  const n=${INPUT_SEL}; if(!n) return 'nf';
  const setter=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
  n.focus(); setter.call(n,''); n.dispatchEvent(new Event('input',{bubbles:true}));
  return 'cleared';
})()`);
await sleep(2500);

const dump = await s.mainEval(`(()=>{
  const dd=[...document.querySelectorAll('.cook-select-dropdown')].find(n=>n.getBoundingClientRect().height>10);
  if(!dd) return JSON.stringify({err:'no-dd'});
  const r=dd.getBoundingClientRect();
  const menus=[...dd.querySelectorAll('.cook-cascader-menu')].map((m,i)=>({
    i,
    items:[...m.querySelectorAll('.cook-cascader-menu-item')].map(n=>({
      t:(n.innerText||'').trim().replace(/\\s+/g,'|').slice(0,40),
      hasArrow:/cook-cascader-menu-item-expand/.test((n.className||'').toString()),
    })),
  }));
  return JSON.stringify({box:{x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),h:Math.round(r.height)},
    text:dd.innerText.replace(/\\s+/g,' ').slice(0,600), menus}, null, 1);
})()`);
console.log(dump);

// 顺带看页面顶部店名与「门店数」线索
const top = await s.mainEval(`(()=>{
  const names=[...document.querySelectorAll('[class*=shop-name__], [class*=chain], .cook-select-selection-item')].map(n=>(n.innerText||'').trim()).filter(t=>t&&t.length<40);
  return JSON.stringify([...new Set(names)].slice(0,10));
})()`);
console.log('TOPS=' + top);

s.cdp.close();
process.exit(0);
