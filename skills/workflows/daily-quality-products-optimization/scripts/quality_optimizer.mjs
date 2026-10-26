import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {FLOW,COMPANY,METRIC,compact,digest,validateMerchants,validateProducts,submissionKey,reconcileProducts,maySubmit,aggregate,segmentDeadline,canStartStore,shanghaiClock,safeRetryEligible} from './quality_core.mjs';
const BASE=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const ROOT=path.resolve(BASE,'../../..');
const HOME='https://open.shop.ele.me/manager/base/home';
const POST=path.join(ROOT,'skills/posts/taobao-svc-post');
const atomic=async(file,value)=>{await fs.mkdir(path.dirname(file),{recursive:true,mode:0o700});const tmp=file+'.tmp';await fs.writeFile(tmp,JSON.stringify(value,null,2),{mode:0o600});await fs.rename(tmp,file);};
const dayNow=()=>new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai'}).format(new Date());
export function merchantDom(){
 const text=e=>e?.textContent?.trim()||'';
 const radio=document.querySelector('input[value="material_quality_entree_proportion_rate"]');
 const label=radio?.closest('label');
 const total=Number((text(label).match(/优质商品率低\((\d+)\)/)||[])[1]);
 const rows=[...document.querySelectorAll('tbody tr.ant-table-row')].map(r=>{
  const c=[...r.querySelectorAll('td')].map(text);return {name:c[0],metric:c[1],current:c[2],target:c[3],status:c[4],action:c[5]};
 });
 return {total,selected:!!radio?.checked,status:[...document.querySelectorAll('.ant-select-selection-item')].map(text).filter(t=>['未完成','已完成','全部'].includes(t)),filter:document.querySelector('input[placeholder="按组织/城市查找"]')?.value,
  page:Number(text(document.querySelector('ul.ant-pagination .ant-pagination-item-active')))||1,
  hasNext:!!document.querySelector('ul.ant-pagination li.ant-pagination-next:not(.ant-pagination-disabled)'),rows,
  loading:!!document.querySelector('.ant-spin-spinning')};
}
export function productDom(){
 const text=e=>e?.textContent?.trim()||'';
 const tab=[...document.querySelectorAll('[role=tab][aria-selected=true]')].find(e=>text(e).startsWith('类目详情问题'));
 const total=Number((text(tab).match(/类目详情问题\((\d+)\)/)||[])[1]);
 const products=[];let item;
 for(const row of document.querySelectorAll('tbody tr.ant-table-row')){
  const cells=[...row.querySelectorAll('td')];
  const start=row.querySelector('td.goodInfoTd');
  if(start){
   const operator=row.querySelector('td.operatorSingleTd');
   const ids=[...new Set([...operator?.querySelectorAll('[data-ltracker-datalist]')||[]].map(e=>(e.getAttribute('data-ltracker-datalist').match(/(?:^|[&;,\s])commodity_taskid=(\d+)/)||[])[1]).filter(Boolean))];
   item={taskId:ids.length===1?ids[0]:'',name:text(start.querySelector('p[class*=name]')),hasSuggestion:[...operator?.querySelectorAll('button')||[]].some(b=>text(b)==='采纳建议'&&!b.disabled),issues:[]};products.push(item);
  }
  if(item){const content=cells.filter(c=>!c.classList.contains('goodInfoTd')&&!c.classList.contains('operatorSingleTd'));if(content.length===3)item.issues.push({kind:text(content[0]),current:text(content[1]),suggestion:text(content[2])});}
 }
 return {total,products,page:Number(text(document.querySelector('ul.ant-pagination .ant-pagination-item-active')))||1,
  hasNext:!!document.querySelector('ul.ant-pagination li.ant-pagination-next:not(.ant-pagination-disabled)'),loading:!!document.querySelector('.ant-spin-spinning'),
  headers:[...document.querySelectorAll('thead th')].map(text),empty:[...document.querySelectorAll('.ant-empty-description')].map(text)};
}
async function integrity(){
 let codeVersion;
 for(const manifestPath of [path.join(POST,'dependencies.json'),path.join(BASE,'runtime-policy.json')]){
  const m=JSON.parse(await fs.readFile(manifestPath,'utf8'));const folder=path.dirname(manifestPath);
  if(manifestPath===path.join(BASE,'runtime-policy.json'))codeVersion=digest(m.files);
  for(const [name,sha] of Object.entries(m.files)){if(digestBytes(await fs.readFile(path.join(folder,name)))!==sha)throw Error('quality-code-integrity-drift:'+name);}
 }
 return codeVersion;
}
function digestBytes(bytes){return cryptoHash(bytes);}
import crypto from 'node:crypto';
const cryptoHash=b=>crypto.createHash('sha256').update(b).digest('hex');
function budget(deadline,maximum=8000){const ms=Math.min(maximum,deadline-Date.now());if(ms<1000)throw Error('quality-segment-yield');return ms;}
async function bounded(promise,deadline,reason='quality-ui-stage-timeout'){let timer;try{return await Promise.race([promise,new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error(reason)),Math.max(1,deadline-Date.now()));})]);}finally{clearTimeout(timer);}}
const rowSignature=v=>JSON.stringify(v.rows||v.products||[]);
async function stable(subject,fn,deadline,{previousPage=null,previousSignature=null,previousRowsSignature=null}={}){
 let last='';
 while(Date.now()<deadline){
  const v=await bounded(subject.evaluate(fn),Math.min(deadline,Date.now()+5000));const signature=JSON.stringify(v);
  if(!v.loading&&v.page!==previousPage&&signature!==previousSignature&&rowSignature(v)!==previousRowsSignature&&signature===last)return v;
  last=signature;await new Promise(r=>setTimeout(r,250));
 }
 throw Error('quality-ui-stage-timeout');
}
export async function changePage(subject,locator,fn,deadline,before){
 const owner=typeof subject.page==='function'?subject.page():subject;
 const frame=owner===subject?owner.mainFrame():subject;
 const responseP=owner.waitForResponse(response=>{
  if(fn===merchantDom)return response.url().includes('pageQueryOpenTaskMerchantList');
  try{
   const request=response.request(),url=new URL(response.url());
   return request.frame()===frame&&['xhr','fetch'].includes(request.resourceType())
    &&(/(^|\.)ele\.me$/.test(url.hostname)||/(^|\.)taobao\.com$/.test(url.hostname))
    &&String(response.headers()['content-type']||'').includes('json');
  }catch{return false;}
 },{timeout:budget(deadline,15000)});
 responseP.catch(()=>{});
 await locator.click({timeout:budget(deadline)});
 const response=await responseP;if(response.status()!==200)throw Error('quality-pagination-response-not-ok');
 await bounded(response.finished(),Math.min(deadline,Date.now()+15000));
 return await stable(subject,fn,Math.min(deadline,Date.now()+15000),{previousPage:before.page,previousRowsSignature:rowSignature(before)});
}
async function goFirst(subject,deadline,fn){
 const before=await stable(subject,fn,Math.min(deadline,Date.now()+15000));
 const first=subject.locator('ul.ant-pagination li.ant-pagination-item[title="1"]');
 if(await first.count()&&!(await first.getAttribute('class')).includes('ant-pagination-item-active'))return await changePage(subject,first,fn,deadline,before);
 return before;
}
export async function allPages(subject,fn,deadline,validate){
 let page=await goFirst(subject,deadline,fn);let rows=[];const totals=[];const visited=new Set();
 for(let n=0;n<1000;n++){
  if(visited.has(page.page))throw Error('quality-pagination-cycle');visited.add(page.page);totals.push(page.total);
  rows.push(...(page.rows||page.products));
  if(!page.hasNext)break;
  page=await changePage(subject,subject.locator('ul.ant-pagination li.ant-pagination-next:not(.ant-pagination-disabled)'),fn,deadline,page);
  if(n===999)throw Error('quality-pagination-limit');
 }
 if(new Set(totals).size!==1)throw Error('quality-list-changed-during-pagination');
 const snapshot=page.rows?{total:totals[0],rows}:{total:totals[0],products:rows};return validate(snapshot);
}
async function guardService(page){
 const {assertOrigin,assertAuthenticated}=await import(path.join(POST,'scripts/auth.mjs'));assertOrigin(page.url());assertAuthenticated(await page.locator('body').innerText({timeout:5000}));
}
async function navigate(page,deadline){
 await page.goto(HOME,{waitUntil:'domcontentloaded',timeout:budget(deadline,20000)});await guardService(page);
 await page.locator('[class*=header-userinfo] .ant-dropdown-trigger').hover({timeout:budget(deadline)});
 await page.getByRole('menuitem',{name:'账号中心',exact:true}).click({timeout:budget(deadline)});
 await page.getByText('zhangyanru188',{exact:true}).waitFor({state:'visible',timeout:budget(deadline,15000)});
 if(new URL(page.url()).pathname!=='/account')throw Error('quality-account-page-mismatch');
 await page.goto(HOME,{waitUntil:'domcontentloaded',timeout:budget(deadline,15000)});await guardService(page);
 const all=page.locator('.ant-select-selection-item').filter({hasText:/^全部门店[（(]\d+家[）)]$/});
 await all.waitFor({state:'visible',timeout:budget(deadline,15000)});
 if(await all.count()!==1)throw Error('quality-account-all-stores-scope-unverified');
 const accountLabel='zhangyanru188:全部门店';
 if(!await page.getByText('经营任务',{exact:true}).isVisible())await page.getByText('数据中心',{exact:true}).click({timeout:budget(deadline)});
 await page.getByText('经营任务',{exact:true}).click({timeout:budget(deadline)});
 const metric=page.locator('label').filter({has:page.locator('input[value="'+METRIC+'"]')});
 await metric.waitFor({state:'visible',timeout:budget(deadline,15000)});await metric.click({timeout:budget(deadline)});
 let v;
 while(Date.now()<deadline){v=await bounded(page.evaluate(merchantDom),Math.min(deadline,Date.now()+5000));if(!v.loading&&v.selected&&v.rows.every(r=>r.metric==='优质商品率低')&&(v.total===0||v.rows.length>0))break;await new Promise(r=>setTimeout(r,250));}
 if(!v||!v.selected||v.filter!==''||v.status.length!==1||v.status[0]!=='未完成')throw Error('quality-merchant-filter-scope-invalid');
 return accountLabel;
}
async function openStore(page,store,deadline){
 let current=await goFirst(page,deadline,merchantDom);
 for(let n=0;n<1000;n++){
  const rows=await page.locator('tbody tr.ant-table-row').evaluateAll(es=>es.map(e=>e.querySelector('td')?.textContent?.trim()));
  const indexes=rows.flatMap((name,i)=>compact(name)===compact(store.name)?[i]:[]);
  if(indexes.length>1)throw Error('quality-store-identity-ambiguous');
  if(indexes.length===1){const row=page.locator('tbody tr.ant-table-row').nth(indexes[0]);const popup=page.waitForEvent('popup',{timeout:budget(deadline,10000)});await row.getByRole('button',{name:'去完成',exact:true}).click({timeout:budget(deadline)});return await popup;}
  if(!current.hasNext)return null;
  current=await changePage(page,page.locator('ul.ant-pagination li.ant-pagination-next:not(.ant-pagination-disabled)'),merchantDom,deadline,current);
 }
 throw Error('quality-store-search-limit');
}
async function productFrame(detail,store,deadline){
 while(Date.now()<deadline){
  const u=new URL(detail.url());const id=u.origin==='https://melody.shop.ele.me'&&u.pathname.match(/^\/app\/shop\/(\d+)\/food-rectify$/)?.[1];
  if(id){
   if(store.shopId&&store.shopId!==id)throw Error('quality-store-id-changed');
   if(compact(await bounded(detail.title(),Math.min(deadline,Date.now()+5000)))!==compact(store.name))throw Error('quality-store-name-changed');
   store.shopId=id;
   const frames=detail.frames().filter(f=>{try{const v=new URL(f.url());return v.origin==='https://r.ele.me'&&v.pathname==='/napos-goods-quality-pc/rectify/home';}catch{return false;}});
   if(frames.length>1)throw Error('quality-product-frame-ambiguous');
   if(frames.length===1){await frames[0].getByText('商品整改',{exact:true}).waitFor({state:'visible',timeout:budget(deadline,10000)});return frames[0];}
  }
  await new Promise(r=>setTimeout(r,250));
 }
 throw Error('quality-store-rectify-loading-timeout');
}
async function noModal(frame){if(await frame.locator('.ant-modal:visible,.ant-popover:visible').count())throw Error('quality-unrecognized-modal');}
export async function refreshFinalRoster(page,deadline,accountLabel,{navigateToScope=navigate,readPages=allPages}={}){
 const finalAccount=await navigateToScope(page,deadline);if(finalAccount!==accountLabel)throw Error('quality-final-account-scope-changed');
 return await readPages(page,merchantDom,deadline,validateMerchants);
}
export async function acquireSegmentLease(acquire,runId){
 try{return await acquire(runId);}catch(error){if(/(?:post[-:]9231[-:]lease[-:]busy|post-lease-busy|service-post-busy)/.test(String(error.message||error)))return null;throw error;}
}
export async function runSegment({execute=false}={}){
 const codeVersion=await integrity(),day=dayNow(),folder=path.join(BASE,'.runtime/days',day),stateFile=path.join(folder,'state.json');
 let state;try{state=JSON.parse(await fs.readFile(stateFile,'utf8'));}catch(e){if(e.code!=='ENOENT')throw e;state={schemaVersion:2,day,workflowId:FLOW,stores:[],scopeFinished:false,cursor:{round:1,page:1,row:0,newShops:0,rowsVisited:0,noNewRounds:0}};}
 if(state.day!==day||state.workflowId!==FLOW)throw Error('quality-state-binding-invalid');
 if(!state.cursor)throw Error('quality-old-state-requires-read-only-migration');
 if(!execute)return {ok:true,mode:'inspect-state-only',summary:aggregate(state),browserActions:0,sendAttempts:0};
 const clock=shanghaiClock();if(clock.hour<17)return {ok:false,reason:'quality-not-due',sendAttempts:0};
 const deadline=segmentDeadline(),closingPriority=clock.hour===18&&clock.minute>=30&&clock.minute<35;
 if(closingPriority||!canStartStore(deadline))return {ok:false,reason:'quality-yield-to-fixed-duty',continuation:true,summary:aggregate(state),sendAttempts:0};
 if(aggregate(state).ok)return {ok:true,summary:aggregate(state),stateFile,runtimeModelDecisions:0,sendAttempts:0};
 const {acquirePostLease,releasePostLease}=await import(path.join(POST,'scripts/lease.mjs'));
 const lease=await acquireSegmentLease(acquirePostLease,'quality-segment-'+crypto.randomUUID());if(!lease)return {ok:false,reason:'quality-post-busy',continuation:true,summary:aggregate(state),sendAttempts:0};
 let browser,page,originalUrl,detail;
 const save=()=>atomic(stateFile,state);
 try{
  const conn=await(await import(path.join(POST,'scripts/connect.mjs'))).connectToPost();browser=conn.browser;
  const pages=conn.context.pages().filter(p=>p.url().startsWith('https://open.shop.ele.me/manager/'));if(pages.length!==1)throw Error('quality-service-page-not-unique');page=pages[0];originalUrl=page.url();
  const label=await navigate(page,deadline);if(state.accountLabel&&state.accountLabel!==label)throw Error('quality-account-scope-changed');state.accountLabel=label;
  let current=await goFirst(page,deadline,merchantDom);
  while(current.page<state.cursor.page&&current.hasNext)current=await changePage(page,page.locator('ul.ant-pagination li.ant-pagination-next:not(.ant-pagination-disabled)'),merchantDom,deadline,current);
  if(current.page!==state.cursor.page){state.cursor.page=current.page;state.cursor.row=0;}
  let visited=0;
  while(canStartStore(deadline)&&visited<40&&!state.scopeFinished){
   state.latestTotal=current.total;if(state.firstTotal===undefined)state.firstTotal=current.total;
   if(state.cursor.row>=current.rows.length){
    if(current.hasNext){current=await changePage(page,page.locator('ul.ant-pagination li.ant-pagination-next:not(.ant-pagination-disabled)'),merchantDom,deadline,current);state.cursor.page=current.page;state.cursor.row=0;await save();continue;}
    state.rounds=state.rounds||[];state.rounds.push({round:state.cursor.round,newShops:state.cursor.newShops,rowsVisited:state.cursor.rowsVisited,platformTotal:current.total,finishedAt:new Date().toISOString()});
    state.cursor.noNewRounds=state.cursor.newShops===0?state.cursor.noNewRounds+1:0;
    const handled=aggregate(state).handled,reference=Math.min(state.firstTotal??current.total,current.total);
    if(state.cursor.noNewRounds>0&&(handled>=reference||state.cursor.noNewRounds>=2)){state.scopeFinished=true;state.finishedAt=new Date().toISOString();await save();break;}
    if(state.cursor.round>=20){state.roundLimitReached=true;await save();break;}
    state.cursor={...state.cursor,round:state.cursor.round+1,page:1,row:0,newShops:0,rowsVisited:0};current=await goFirst(page,deadline,merchantDom);await save();continue;
   }
   const rowIndex=state.cursor.row,expected=current.rows[rowIndex];visited++;let store;
   const storeDeadline=Math.min(deadline,Date.now()+60000);
   try{
    const row=page.locator('tbody tr.ant-table-row').nth(rowIndex);const popup=page.waitForEvent('popup',{timeout:budget(storeDeadline,10000)});await row.getByRole('button',{name:'去完成',exact:true}).click({timeout:budget(storeDeadline)});detail=await popup;
    const identity={name:expected.name};const frame=await productFrame(detail,identity,storeDeadline);
    store=state.stores.find(s=>s.shopId===identity.shopId);
    if(store&&!safeRetryEligible(store,codeVersion))continue;
    if(!store){store={shopId:identity.shopId,name:identity.name,state:'pending',firstSeenAt:new Date().toISOString()};state.stores.push(store);state.cursor.newShops++;}
    const intentFile=path.join(folder,'intents',store.shopId+'.json');
    try{const prior=JSON.parse(await fs.readFile(intentFile,'utf8'));if(prior.day!==day||prior.shopId!==store.shopId)throw Error('quality-day-intent-conflict');store.submission=prior;store.state='unknown';store.reason='same-day-prior-intent-read-only';continue;}catch(e){if(e.code!=='ENOENT')throw e;}
    store.attemptCount=(store.attemptCount||0)+1;store.attemptsForVersion=store.lastAttemptVersion===codeVersion?(store.attemptsForVersion||0)+1:1;store.lastAttemptVersion=codeVersion;
    await noModal(frame);const before=await stable(frame,productDom,Math.min(storeDeadline,Date.now()+10000));store.before={total:before.total,visibleProducts:before.products.length};
    const action=frame.getByRole('button',{name:'一键优化类目详情',exact:true});
    if(before.total===0||await action.count()===0||await action.isDisabled()){store.state='checked_no_action';store.reason='no-available-platform-optimization';store.completedAt=new Date().toISOString();continue;}
    await frame.locator('label').filter({hasText:'全选本页'}).locator('input[type=checkbox]').check({timeout:budget(storeDeadline)});
    await action.click({timeout:budget(storeDeadline)});const pop=frame.locator('.ant-popover.ant-popconfirm:visible');await pop.waitFor({state:'visible',timeout:budget(storeDeadline)});
    const prompt=compact(await pop.innerText());if(!prompt.includes('优化全部类目详情问题')||!prompt.includes('优化后，有建议的类目详情将自动采纳平台建议信息，其余的请手动优化'))throw Error('quality-optimization-confirmation-scope-invalid');
    store.submission={day,shopId:store.shopId,state:'attempted',eventId:day+'-quality-'+store.shopId,at:new Date().toISOString()};await fs.mkdir(path.dirname(intentFile),{recursive:true,mode:0o700});await fs.writeFile(intentFile,JSON.stringify(store.submission,null,2),{flag:'wx',mode:0o600});await save();
    await pop.getByRole('button',{name:'确认优化',exact:true}).click({timeout:budget(storeDeadline)});await pop.waitFor({state:'hidden',timeout:budget(storeDeadline,15000)});
    const after=await stable(frame,productDom,Math.min(storeDeadline,Date.now()+10000));
    const errors=await frame.locator('.ant-message-error:visible,.ant-notification-notice-error:visible,.ant-alert-error:visible').allTextContents();if(errors.length)throw Error('quality-platform-operation-error');
    store.after={total:after.total,visibleProducts:after.products.length};store.operation={confirmed:true,popoverClosed:true,uiStable:true,observedAt:new Date().toISOString()};store.state='completed';store.completedAt=store.operation.observedAt;
   }catch(e){
    if(!store){state.rowErrors=state.rowErrors||[];state.rowErrors.push({round:state.cursor.round,page:state.cursor.page,row:rowIndex,reason:String(e.message||e).slice(0,250),at:new Date().toISOString()});}
    else{store.state=store.submission?'unknown':'blocked';store.reason=String(e.message||e).slice(0,250);store.errors=store.errors||[];store.errors.push({at:new Date().toISOString(),reason:store.reason,attempt:store.attemptCount||0,codeVersion});if(!store.submission)store.retryAt=Date.now()+600000;}
   }finally{
    if(detail){await bounded(detail.close(),Date.now()+5000).catch(()=>{});detail=null;}
    state.cursor.row++;state.cursor.rowsVisited++;await save();
   }
  }
  await save();const summary=aggregate(state);return {ok:summary.ok,continuation:!state.scopeFinished&&!state.roundLimitReached,summary,stateFile,runtimeModelDecisions:0,sendAttempts:0};
 }finally{
  try{if(detail)await bounded(detail.close(),Date.now()+5000).catch(()=>{});if(page&&originalUrl&&!page.isClosed()&&page.url()!==originalUrl)await page.goto(originalUrl,{waitUntil:'domcontentloaded',timeout:10000}).catch(()=>{});}
  finally{if(browser)await bounded(browser.close(),Date.now()+5000).catch(()=>{});await releasePostLease(lease);}
 }
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
 try{if(process.argv.length!==3||!['--execute','--inspect'].includes(process.argv[2]))throw Error('usage: --execute|--inspect');const r=await runSegment({execute:process.argv[2]==='--execute'});console.log(JSON.stringify(r));process.exitCode=r.ok?0:1;}catch(e){console.log(JSON.stringify({ok:false,reason:String(e.message||e).slice(0,300),runtimeModelDecisions:0,sendAttempts:0}));process.exitCode=1;}
}
