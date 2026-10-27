import { session, sleep } from '../scripts/lib/cdp.mjs';
const s = await session({ port: 9230, width: 1440, height: 1500 });
await s.rearm();
const r = await s.ctxForFrame(/melody-stats-next/);
const ev = s.frameEval(r.id);
console.log('TAB=' + await ev(`(()=>{const q=location.hash.split('?')[1]||'';return new URLSearchParams(q).get('tab')})()`));
console.log(await ev(`(()=>{
  const docY=(n)=>Math.round(n.getBoundingClientRect().y+window.scrollY);
  const out={radios:[],groups:[],selects:[]};
  out.radios=[...document.querySelectorAll('.ant-radio-button-wrapper')].map(n=>{
    const r=n.getBoundingClientRect();
    return {t:(n.innerText||'').trim(),ck:/checked/.test((n.className||'').toString()),docY:docY(n),x:Math.round(r.x)};
  });
  out.selects=[...document.querySelectorAll('.ant-select-selection-item')].map(n=>{
    const r=n.getBoundingClientRect();
    return {t:(n.innerText||'').trim(),docY:docY(n),x:Math.round(r.x)};
  });
  return JSON.stringify(out,null,1);
})()`));
s.cdp.close(); process.exit(0);
