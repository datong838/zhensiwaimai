// Original UI pagination under a caller-owned existing maintenance lease; no API data read.
import fs from 'node:fs/promises';
import {connectToPost} from '../../../skills/posts/taobao-svc-post/scripts/connect.mjs';
import {merchantDom,merchantListRequest,changePage} from '../../../skills/workflows/daily-quality-products-optimization/scripts/quality_optimizer.mjs';
const [targetId,ownerPid]=process.argv.slice(2);
if(!targetId||!/^\d+$/.test(ownerPid||''))throw Error('owned-target-and-pid-required');
const lease=JSON.parse(await fs.readFile('/tmp/zhensi-post-9231.lock','utf8'));
if(lease.pid!==Number(ownerPid)||!String(lease.runId).startsWith('night-precheck-'))throw Error('original-maintenance-lease-required');
process.kill(lease.pid,0);
const {browser,context}=await connectToPost();
try{
 const selected=[];
 for(const page of context.pages()){
  const url=new URL(page.url());
  if(url.origin!=='https://open.shop.ele.me'||url.pathname!=='/manager/base/abnormal-diagnosis')continue;
  const session=await context.newCDPSession(page);
  try{if((await session.send('Target.getTargetInfo')).targetInfo.targetId===targetId)selected.push(page);}finally{await session.detach();}
 }
 if(selected.length!==1)throw Error('exact-owned-service-page-not-unique');
 const page=selected[0],result={at:new Date().toISOString(),pages:[],events:[],sendAttempts:0,productSubmissions:0};
 const frame=page.mainFrame();let number=1;
 page.on('request',request=>{
  if(request.url().includes('pageQueryOpenTaskMerchantList')){
   const url=new URL(request.url());result.events.push({kind:'request',page:number+1,origin:url.origin,path:url.pathname,acceptedByExactGate:merchantListRequest(request,frame),at:Date.now()});
  }
 });
 page.on('response',response=>{
  const request=response.request();
  if(request.url().includes('pageQueryOpenTaskMerchantList')){
   const url=new URL(request.url());result.events.push({kind:'response',page:number+1,origin:url.origin,path:url.pathname,acceptedByExactGate:merchantListRequest(request,frame),status:response.status(),at:Date.now()});
  }
 });
 let current=await page.evaluate(merchantDom);
 if(!current.selected||current.filter!==''||JSON.stringify(current.status)!=='["未完成"]'||current.page!==1||current.loading||!current.rows.every(r=>r.metric==='优质商品率低'))throw Error('owned-service-scope-not-ready');
 for(let visited=0;visited<40;visited++){
  result.pages.push({page:current.page,total:current.total,hasNext:current.hasNext,rows:current.rows.map(r=>({name:r.name,metric:r.metric}))});
  if(!current.hasNext)break;
  current=await changePage(page,page.locator('li.ant-pagination-next:not(.ant-pagination-disabled)'),merchantDom,Date.now()+20000,current);
  number=current.page;
 }
 result.lastPageHasNext=current.hasNext;result.rowCount=result.pages.reduce((sum,p)=>sum+p.rows.length,0);
 result.uniqueNames=new Set(result.pages.flatMap(p=>p.rows.map(r=>r.name))).size;
 result.exactRequests=result.events.filter(e=>e.kind==='request'&&e.acceptedByExactGate).length;
 result.telemetryRejected=result.events.filter(e=>e.kind==='request'&&!e.acceptedByExactGate).length;
 if(result.lastPageHasNext!==false||result.exactRequests!==result.pages.length-1)throw Error('pagination-source-evidence-incomplete');
 console.log(JSON.stringify(result));
}finally{await browser.close();}
