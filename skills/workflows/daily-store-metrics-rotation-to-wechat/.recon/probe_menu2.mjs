import { session, sleep } from '../scripts/lib/cdp.mjs';
const s = await session({ port: 9230, width: 1440, height: 1500 });
await s.rearm();
const dump = await s.mainEval(`(()=>{
  const lis=[...document.querySelectorAll('li.cook-menu-item, li[class*=menuItem]')].map(n=>{
    const r=n.getBoundingClientRect();
    return {t:(n.innerText||'').trim().replace(/\\s+/g,'|'),y:Math.round(r.y),x:Math.round(r.x),w:Math.round(r.width),cls:(n.className||'').toString().slice(0,40)};
  }).filter(o=>o.w>50);
  return JSON.stringify(lis,null,1);
})()`);
console.log(dump);
s.cdp.close(); process.exit(0);
