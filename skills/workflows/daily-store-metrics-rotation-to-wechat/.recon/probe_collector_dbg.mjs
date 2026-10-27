import { session, sleep } from '../scripts/lib/cdp.mjs';
const s = await session({ port: 9230, width: 1440, height: 1600 });
await s.rearm();

const rawEval = async (expr) => {
  const r = await s.cdp.send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
  return r;
};

// 1. 清空搜索（复刻采集器）
const r1 = await rawEval(`(()=>{
  const n=[...document.querySelectorAll('input')].find(x=>x.placeholder==='搜索店铺名称/ID');
  if(!n) return 'nf';
  const set=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
  n.focus(); set.call(n,''); n.dispatchEvent(new Event('input',{bubbles:true}));
  return 'ok';
})()`);
console.log('CLEAR=', JSON.stringify(r1.result?.value), 'EX=', r1.exceptionDetails?.exception?.description?.slice(0, 200));
await sleep(1800);

// 2. 直接读列
const expr = `(()=>{try{
  const dd=[...document.querySelectorAll('.cook-select-dropdown')].find(n=>n.getBoundingClientRect().height>10);
  if(!dd) return JSON.stringify({ok:false,why:'no-dropdown'});
  const cols=[...dd.querySelectorAll('.cook-cascader-menu')];
  const col=cols[0];
  if(!col) return JSON.stringify({ok:false,why:'no-col',cols:cols.length});
  const items=[...col.querySelectorAll('.cook-cascader-menu-item')];
  return JSON.stringify({ok:true,cols:cols.length,n:items.length,first:(items[1]?.innerText||'').slice(0,20)});
}catch(e){return JSON.stringify({ok:false,why:'page-ex',detail:e.message})}})()`;
const r2 = await rawEval(expr);
console.log('READ=', JSON.stringify(r2.result?.value).slice(0, 300), 'EX=', r2.exceptionDetails?.exception?.description?.slice(0, 300));
s.cdp.close(); process.exit(0);
