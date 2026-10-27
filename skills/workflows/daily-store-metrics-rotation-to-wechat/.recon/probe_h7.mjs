import { session, sleep } from '../scripts/lib/cdp.mjs';
const s = await session({ port: 9230, width: 1440, height: 1500 });
await s.rearm();
const r = await s.ctxForFrame(/melody-stats-next/);
const ev = s.frameEval(r.id);
console.log('TAB=' + await ev(`(()=>{const q=location.hash.split('?')[1]||'';return new URLSearchParams(q).get('tab')})()`));
const out = await ev(`(()=>{
  const docY=(n)=>Math.round(n.getBoundingClientRect().y+window.scrollY);
  const hits=[...document.querySelectorAll('*')].filter(n=>{
    const t=(n.innerText||'').trim();
    return t.indexOf('历史数据')>=0 && t.length<40 && n.getBoundingClientRect().width>0;
  }).map(n=>{
    const r=n.getBoundingClientRect();
    return {tag:n.tagName,cls:(n.className||'').toString().slice(0,40),txt:JSON.stringify(t=(n.innerText||'').trim()),kids:n.children.length,docY:docY(n),x:Math.round(r.x),w:Math.round(r.width),h:Math.round(r.height)};
  });
  const seen=new Set();const u=[];
  for(const o of hits){const k=o.txt+'|'+o.docY;if(seen.has(k))continue;seen.add(k);u.push(o);}
  return JSON.stringify(u.slice(0,10),null,1);
})()`);
console.log(out);
s.cdp.close(); process.exit(0);
