import { session, sleep } from '../scripts/lib/cdp.mjs';

const orgName = process.argv[2] || '孙记稻香世家';
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

const kw = JSON.stringify(orgName);
const hit = JSON.parse(await s.mainEval(`(()=>{
  const dd=[...document.querySelectorAll('.cook-select-dropdown')].find(n=>n.getBoundingClientRect().height>10);
  if(!dd) return JSON.stringify({found:false,why:'no-dd'});
  const item=[...dd.querySelectorAll('.cook-cascader-menu-item')].find(n=>(n.innerText||'').includes(${kw}));
  if(!item) return JSON.stringify({found:false,why:'no-item'});
  const r=item.getBoundingClientRect();
  return JSON.stringify({found:true,x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)});
})()`));

if (!hit.found) {
  console.log('ORG_NOT_FOUND ' + JSON.stringify(hit));
  s.cdp.close();
  process.exit(1);
}
await s.clickAt(hit.x, hit.y);
await sleep(2600);

const dump = await s.mainEval(`(()=>{
  const dd=[...document.querySelectorAll('.cook-select-dropdown')].find(n=>n.getBoundingClientRect().height>10);
  if(!dd) return JSON.stringify({err:'closed'});
  const cols=[...dd.querySelectorAll('.cook-cascader-menu')];
  const out=cols.map((c,i)=>({
    i,
    n:c.querySelectorAll('.cook-cascader-menu-item').length,
    items:[...c.querySelectorAll('.cook-cascader-menu-item')].slice(0,12).map(n=>({
      t:(n.innerText||'').replace(/\\s+/g,'|').slice(0,50),
      dv:(n.getAttribute('data-value')||'').slice(-72),
      arrow:/expand/.test((n.className||'').toString()),
      checked:n.getAttribute('aria-checked')
    }))
  }));
  return JSON.stringify({cols:out},null,1);
})()`);
console.log(dump);
s.cdp.close();
process.exit(0);
