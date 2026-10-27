import {withTaskPage} from '../../aos-platform/plugins/browser/control-background-dedicated-chrome/scripts/run_task.mjs';

const options={profile:'jinsha-business',port:'9232',instance:'04304cc1-7979-4f53-b14c-6008605c4c87','task-id':'negative-daily-20260914'};
const result=await withTaskPage(options,async({page})=>{
 const hamburger=page.locator('.hamburger-container:visible');
 if(await hamburger.count()!==1)throw Error(`hamburger-count:${await hamburger.count()}`);
 await hamburger.click();
 await page.waitForTimeout(500);
 const left=await page.locator('body *').evaluateAll(nodes=>nodes.map(el=>{
  const r=el.getBoundingClientRect();const style=getComputedStyle(el);
  return {tag:el.tagName,className:String(el.className||''),title:el.getAttribute('title'),ariaLabel:el.getAttribute('aria-label'),role:el.getAttribute('role'),x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),h:Math.round(r.height),display:style.display,visibility:style.visibility};
 }).filter(x=>x.w>=20&&x.h>=20&&x.x>=0&&x.x<130&&x.y>=0&&x.y<300).slice(0,80));
 const labels={};
 for(const label of ['外卖','团购','分账','美团','淘宝','京东']){
  const loc=page.getByText(label,{exact:true});const rows=[];
  for(let i=0;i<await loc.count();i++)rows.push(await loc.nth(i).evaluate(el=>{const p=el.parentElement,g=p?.parentElement,s=getComputedStyle(el),ps=p?getComputedStyle(p):null;return {tag:el.tagName,className:String(el.className||''),parentTag:p?.tagName||'',parentClass:String(p?.className||''),grandClass:String(g?.className||''),visible:!!(el.offsetWidth||el.offsetHeight||el.getClientRects().length),color:s.color,background:s.backgroundColor,parentBackground:ps?.backgroundColor||''};}));
  labels[label]=rows;
 }
 return {url:page.url(),title:await page.title(),left,labels};
});
console.log(JSON.stringify(result));
