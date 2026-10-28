// Read-only classification under an already-held original maintenance lease.
import fs from 'node:fs/promises';
import {connectToPost} from '../../../skills/posts/taobao-svc-post/scripts/connect.mjs';
import {dismissKnownBrandUpgrade,productDom,readyOptimization} from '../../../skills/workflows/daily-quality-products-optimization/scripts/quality_optimizer.mjs';
const [targetId,shopId,ownerPid]=process.argv.slice(2);
if(!targetId||!/^\d+$/.test(shopId||'')||!/^\d+$/.test(ownerPid||''))throw Error('exact-owned-target-required');
const lease=JSON.parse(await fs.readFile('/tmp/zhensi-post-9231.lock','utf8'));
if(lease.pid!==Number(ownerPid)||!String(lease.runId).startsWith('night-precheck-'))throw Error('original-maintenance-lease-required');
process.kill(lease.pid,0);
const {browser,context}=await connectToPost();
try{
 const selected=[];
 for(const page of context.pages()){
  let u;try{u=new URL(page.url());}catch{continue;}
  if(u.origin!=='https://melody.shop.ele.me'||u.pathname!=='/app/shop/'+shopId+'/food-rectify')continue;
  const session=await context.newCDPSession(page);
  try{if((await session.send('Target.getTargetInfo')).targetInfo.targetId===targetId)selected.push(page);}finally{await session.detach();}
 }
 if(selected.length!==1)throw Error('exact-maintenance-page-not-unique');
 const page=selected[0],notice=await dismissKnownBrandUpgrade(page,Date.now()+10000,shopId);
 const frames=page.frames().filter(f=>{try{const u=new URL(f.url());return u.origin==='https://r.ele.me'&&u.pathname==='/napos-goods-quality-pc/rectify/home';}catch{return false;}});
 const result={at:new Date().toISOString(),shopId,notice,frameCount:frames.length,productSubmissions:0,sendAttempts:0};
 if(frames.length===1){
  const frame=frames[0],samples=[];
  const observed={evaluate:async fn=>{const v=await frame.evaluate(fn);samples.push({total:v.total,page:v.page,hasNext:v.hasNext,loading:v.loading,
   products:v.products?.map(p=>({taskId:p.taskId,issueCount:p.issues?.length,hasSuggestion:p.hasSuggestion}))});return v;},getByRole:(...args)=>frame.getByRole(...args)};
  try{const ready=await readyOptimization(observed,Date.now()+10000);result.readiness=ready.disposition;}
  catch(error){result.readinessError=String(error.message).slice(0,1500);}
  result.samples=samples;
  result.last=await frame.evaluate(productDom);
  result.allButtons=await frame.locator('button').evaluateAll(es=>es.map(e=>({text:e.textContent?.trim(),className:e.className,ariaLabel:e.getAttribute('aria-label'),title:e.getAttribute('title'),disabled:e.disabled,display:getComputedStyle(e).display,visibility:getComputedStyle(e).visibility,width:e.getBoundingClientRect().width,height:e.getBoundingClientRect().height,html:e.outerHTML.slice(0,1000)})));
  result.structure=await frame.evaluate(()=>({
   tabs:[...document.querySelectorAll('[role="tab"]')].map(e=>({text:e.textContent?.trim(),selected:e.getAttribute('aria-selected')})),
   pagination:[...document.querySelectorAll('ul.ant-pagination')].map(e=>e.textContent?.trim()),
   rows:[...document.querySelectorAll('tbody tr.ant-table-row')].slice(0,2).map(r=>[...r.querySelectorAll('td')].map(c=>({className:c.className,text:c.textContent?.trim().slice(0,400)}))),
   buttons:[...document.querySelectorAll('button')].map(e=>({text:e.textContent?.trim(),disabled:e.disabled})).filter(e=>e.text)
  }));
  result.spinners=await frame.locator('.ant-spin-spinning').evaluateAll(es=>es.map(e=>({
   display:getComputedStyle(e).display,visibility:getComputedStyle(e).visibility,width:e.getBoundingClientRect().width,height:e.getBoundingClientRect().height,
   hiddenAncestors:[...function*(el){while(el){yield el;el=el.parentElement;}}(e)].filter(p=>getComputedStyle(p).display==='none'||getComputedStyle(p).visibility==='hidden').length})));
 }
 console.log(JSON.stringify(result));
}finally{await browser.close();}
