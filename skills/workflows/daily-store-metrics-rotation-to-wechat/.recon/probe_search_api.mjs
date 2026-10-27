#!/usr/bin/env node
/**
 * 抓「切换器店铺搜索」的真实接口
 * 手法：注入 fetch/XHR hook → 触发一次搜索 → 读捕获
 */
import { session, sleep } from '../scripts/lib/cdp.mjs';

const kw = process.argv[2] || '孙记稻香世家';

const s = await session({ port: 9230, width: 1440, height: 1500 });
await s.rearm();

const INPUT_SEL = `[...document.querySelectorAll('input')].find(n=>n.placeholder==='搜索店铺名称/ID')`;
const open = () => s.mainEval(`(()=>[...document.querySelectorAll('.cook-select-dropdown')].some(n=>n.getBoundingClientRect().height>10))()`);

if (!(await open())) {
  const SW = JSON.parse(await s.mainEval(`(()=>{const n=document.querySelector('[class*=shop-name__]');const r=n.getBoundingClientRect();return JSON.stringify({x:r.x+r.width/2,y:r.y+r.height/2})})()`));
  await s.clickAt(SW.x, SW.y);
  await sleep(1800);
}

// 注入 hook（幂等）
await s.mainEval(`(()=>{
  if(window.__WB_NET__) return 'already';
  window.__WB_NET__=[];
  const rec=(o)=>window.__WB_NET__.push(o);
  const of=window.fetch;
  window.fetch=function(...a){
    const url = typeof a[0]==='string'?a[0]:(a[0]&&a[0].url);
    const opt = a[1]||{};
    const entry={kind:'fetch', url:String(url).slice(0,300), body:opt.body?String(opt.body).slice(0,600):null, method:opt.method||'GET', t:Date.now()};
    return of.apply(this,a).then(async(r)=>{
      try{const c=r.clone(); const txt=await c.text(); entry.status=r.status; entry.resp=txt.slice(0,1500);}catch(e){}
      rec(entry); return r;
    }).catch(e=>{entry.err=String(e); rec(entry); throw e;});
  };
  const oo=XMLHttpRequest.prototype.open, os=XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open=function(m,u){this.__wb={kind:'xhr',method:m,url:String(u).slice(0,300)};return oo.apply(this,arguments)};
  XMLHttpRequest.prototype.send=function(b){
    const e=this.__wb||{kind:'xhr'};
    e.body=b?String(b).slice(0,600):null;
    this.addEventListener('load',()=>{e.status=this.status; try{e.resp=String(this.responseText).slice(0,1500)}catch(_){} rec(e);});
    return os.apply(this,arguments);
  };
  return 'injected';
})()`);

await s.mainEval(`(()=>{
  const n=${INPUT_SEL};
  const setter=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
  n.focus(); setter.call(n, ${JSON.stringify(kw)}); n.dispatchEvent(new Event('input',{bubbles:true}));
  return n.value;
})()`);
await sleep(3500);

const net = await s.mainEval(`(()=>JSON.stringify(window.__WB_NET__||[]))()`);
const arr = JSON.parse(net);
console.log('CAPTURED=' + arr.length);
const seen = new Set();
for (const e of arr) {
  const key = (e.url || '') + '|' + (e.body || '');
  if (seen.has(key)) continue;
  seen.add(key);
  const u = e.url || '';
  if (!/shop|store|search|poi|org|tree|list/i.test(u)) continue;
  console.log('---');
  console.log(e.kind, e.method, e.status, u);
  if (e.body) console.log('  BODY=' + e.body);
  if (e.resp) console.log('  RESP=' + e.resp.slice(0, 400));
}

// 清掉 hook，避免污染
await s.mainEval(`(()=>{delete window.__WB_NET__; return 'cleared'})()`);
s.cdp.close();
process.exit(0);
