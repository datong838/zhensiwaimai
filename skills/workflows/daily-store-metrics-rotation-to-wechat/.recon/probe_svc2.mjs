import { session, sleep } from '../scripts/lib/cdp.mjs';
const s = await session({ port: 9230, width: 1440, height: 1500 });
await s.rearm();
const r = await s.ctxForFrame(/melody-stats-next/);
const ev = s.frameEval(r.id);
console.log(await ev(`(()=>{
  const docY=(n)=>Math.round(n.getBoundingClientRect().y+window.scrollY);
  const out=[];
  document.querySelectorAll('*').forEach(n=>{
    const t=(n.innerText||'').trim();
    if(!/^(昨日|近7日|近30日|自定义|本周)$/.test(t)) return;
    if(n.children.length>0) return;
    const r=n.getBoundingClientRect();
    if(!r.width||r.width>90) return;
    if(docY(n)>1400) return;
    out.push({t,tag:n.tagName,cls:(n.className||'').toString().slice(0,46),docY:docY(n),x:Math.round(r.x),w:Math.round(r.width),color:getComputedStyle(n).color});
  });
  const seen=new Set();const u=[];
  for(const o of out){const k=o.t+o.docY+o.x;if(seen.has(k))continue;seen.add(k);u.push(o);}
  return JSON.stringify(u,null,1);
})()`));
s.cdp.close(); process.exit(0);
