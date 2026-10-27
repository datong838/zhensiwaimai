import { session, sleep } from '../scripts/lib/cdp.mjs';
const s = await session({ port: 9230, width: 1440, height: 1500 });
await s.rearm();
console.log('OUTER=' + await s.mainEval('location.href'));
const dump = await s.mainEval(`(()=>{
  const items=[...document.querySelectorAll('a,li,span,div')].filter(n=>{
    const r=n.getBoundingClientRect();
    return r.width>20&&r.width<220&&r.height>14&&r.height<50&&r.x<220&&r.y>0;
  }).map(n=>({t:(n.innerText||'').trim().replace(/\\s+/g,'|'),x:Math.round(n.getBoundingClientRect().x),y:Math.round(n.getBoundingClientRect().y),tag:n.tagName,cls:(n.className||'').toString().slice(0,30)}))
   .filter(o=>o.t&&o.t.length<12);
  const seen=new Set();const out=[];
  for(const o of items){const k=o.t+'|'+o.y;if(seen.has(k))continue;seen.add(k);out.push(o);}
  return JSON.stringify(out,null,1);
})()`);
console.log(dump);
s.cdp.close(); process.exit(0);
