import { session, sleep } from '../scripts/lib/cdp.mjs';
const s = await session({ port: 9230, width: 1440, height: 1600 });
await s.rearm();
const colIdx = 0;
const expr = `(()=>{
 try{
  const dd=[...document.querySelectorAll('.cook-select-dropdown')].find(n=>n.getBoundingClientRect().height>10);
  if(!dd) return JSON.stringify({ok:false,why:'no-dropdown'});
  const cols=[...dd.querySelectorAll('.cook-cascader-menu')];
  const col=cols[${colIdx}];
  if(!col) return JSON.stringify({ok:false,why:'no-col',cols:cols.length});
  const items=[...col.querySelectorAll('.cook-cascader-menu-item')];
  const rows=items.map((n,i)=>{
    const toks=(n.innerText||'').split(/\\n|\\s{2,}/).map(t=>t.trim()).filter(Boolean);
    const isOrg = toks[0] === '运营组织';
    return { i, name:(isOrg?toks.slice(1).join(' '):toks[0]||'').trim(), status:(isOrg?'':(toks[1]||'')).trim(),
      dv:n.getAttribute('data-value')||'', arrow:/expand/.test(n.className)||!!n.querySelector('[class*=arrow],[class*=Arrow]'), checked:n.getAttribute('aria-checked')==='true' };
  });
  return JSON.stringify({ok:true,cols:cols.length,rows:rows.slice(0,3),n:rows.length});
 }catch(e){return JSON.stringify({err:e.message,stack:(e.stack||'').slice(0,200)})}
})()`;
console.log(await s.mainEval(expr));
s.cdp.close(); process.exit(0);
