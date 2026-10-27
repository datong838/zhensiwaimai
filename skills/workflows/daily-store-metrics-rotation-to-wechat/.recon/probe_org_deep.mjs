import { session, sleep } from '../scripts/lib/cdp.mjs';

const path = (process.argv[2] || '刘欢/2').split('/');
const s = await session({ port: 9230, width: 1440, height: 1500 });
await s.rearm();

const isOpen = () => s.mainEval(`(()=>[...document.querySelectorAll('.cook-select-dropdown')].some(n=>n.getBoundingClientRect().height>10))()`);
if (!(await isOpen())) {
  const SW = JSON.parse(await s.mainEval(`(()=>{const n=document.querySelector('[class*=shop-name__]');const r=n.getBoundingClientRect();return JSON.stringify({x:r.x+r.width/2,y:r.y+r.height/2})})()`));
  await s.clickAt(SW.x, SW.y);
  await sleep(1800);
}
await s.mainEval(`(()=>{
  const n=[...document.querySelectorAll('input')].find(x=>x.placeholder==='搜索店铺名称/ID');
  if(!n) return 'nf';
  const set=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
  n.focus(); set.call(n,''); n.dispatchEvent(new Event('input',{bubbles:true})); return 'ok';
})()`);
await sleep(2200);

for (let depth = 0; depth < path.length; depth++) {
  const want = JSON.stringify(path[depth]);
  const hit = JSON.parse(await s.mainEval(`(()=>{
    const dd=[...document.querySelectorAll('.cook-select-dropdown')].find(n=>n.getBoundingClientRect().height>10);
    if(!dd) return JSON.stringify({found:false,why:'no-dd'});
    const cols=[...dd.querySelectorAll('.cook-cascader-menu')];
    const col=cols[${depth}];
    if(!col) return JSON.stringify({found:false,why:'no-col',cols:cols.length});
    const items=[...col.querySelectorAll('.cook-cascader-menu-item')];
    const toks=(n)=>(n.innerText||'').split(/\\s+/).map(t=>t.trim()).filter(Boolean);
    const item=items.find(n=>toks(n).some(t=>t===(${want})));
    if(!item) return JSON.stringify({found:false,why:'no-match',have:items.slice(0,8).map(n=>(n.innerText||'').replace(/\\s+/g,'|'))});
    const r=item.getBoundingClientRect();
    return JSON.stringify({found:true,x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)});
  })()`));
  if (!hit.found) { console.log('STEP_FAIL depth=' + depth + ' ' + JSON.stringify(hit)); s.cdp.close(); process.exit(1); }
  await s.clickAt(hit.x, hit.y);
  await sleep(2800);
  console.log('CLICKED depth=' + depth + ' -> ' + path[depth]);
}

// 读最后一列：数量、滚动高度、前几项
const info = await s.mainEval(`(()=>{
  const dd=[...document.querySelectorAll('.cook-select-dropdown')].find(n=>n.getBoundingClientRect().height>10);
  const cols=[...dd.querySelectorAll('.cook-cascader-menu')];
  const last=cols[cols.length-1];
  const items=[...last.querySelectorAll('.cook-cascader-menu-item')];
  const first=items[0];
  return JSON.stringify({
    colCount: cols.length,
    lastColItems: items.length,
    lastColScrollH: last.scrollHeight,
    lastColClientH: last.clientHeight,
    firstDv: first ? (first.getAttribute('data-value')||'').slice(-50) : null,
    firstText: first ? (first.innerText||'').replace(/\\s+/g,'|') : null,
    allCols: cols.map((c,i)=>({i, n:c.querySelectorAll('.cook-cascader-menu-item').length, sh:c.scrollHeight, ch:c.clientHeight}))
  }, null, 1);
})()`);
console.log(info);
s.cdp.close();
process.exit(0);
