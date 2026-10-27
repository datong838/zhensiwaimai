import { session, sleep } from '../scripts/lib/cdp.mjs';
const s = await session({ port: 9230, width: 1440, height: 1500 });
await s.rearm();

const isOpen = () => s.mainEval(`(()=>[...document.querySelectorAll('.cook-select-dropdown')].some(n=>n.getBoundingClientRect().height>10))()`);
if (!(await isOpen())) {
  const SW = JSON.parse(await s.mainEval(`(()=>{const n=document.querySelector('[class*=shop-name__]');const r=n.getBoundingClientRect();return JSON.stringify({x:r.x+r.width/2,y:r.y+r.height/2})})()`));
  await s.clickAt(SW.x, SW.y);
  await sleep(1800);
}
// 清空搜索框
await s.mainEval(`(()=>{
  const n=[...document.querySelectorAll('input')].find(x=>x.placeholder==='搜索店铺名称/ID');
  if(!n) return 'nf';
  const setter=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
  n.focus(); setter.call(n,''); n.dispatchEvent(new Event('input',{bubbles:true})); return 'ok';
})()`);
await sleep(2500);

const info = await s.mainEval(`(()=>{
  const dd=[...document.querySelectorAll('.cook-select-dropdown')].find(n=>n.getBoundingClientRect().height>10);
  if(!dd) return JSON.stringify({err:'no-dd'});
  const cols=[...dd.querySelectorAll('.cook-cascader-menu')];
  const r=dd.getBoundingClientRect();
  // 第一列：所有可点项
  const col0=cols[0]||dd;
  const items=[...col0.querySelectorAll('.cook-cascader-menu-item')].map(n=>{
    const rr=n.getBoundingClientRect();
    return {t:(n.innerText||'').replace(/\\s+/g,'|').slice(0,40),
            arrow:/expand/.test((n.className||'').toString()),
            x:Math.round(rr.x+rr.width/2), y:Math.round(rr.y+rr.height/2)};
  });
  // 第二列：取几个节点看 HTML 属性里有没有 id
  const col1=cols[1];
  const sample=col1?[...col1.querySelectorAll('.cook-cascader-menu-item')].slice(0,3).map(n=>({
    html:n.outerHTML.slice(0,400)
  })):[];
  return JSON.stringify({box:{x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),h:Math.round(r.height)},
    colCount:cols.length, orgCount:items.length, items:items.slice(0,25), sample}, null, 1);
})()`);
console.log(info);
s.cdp.close(); process.exit(0);
