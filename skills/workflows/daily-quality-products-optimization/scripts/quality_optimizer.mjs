import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {FLOW,COMPANY,METRIC,compact,digest,validateMerchants,validateProducts,submissionKey,reconcileProducts,maySubmit,aggregate,segmentDeadline,canStartStore,priorSubmission,shanghaiClock,safeRetryEligible} from './quality_core.mjs';
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
async function stable(subject,fn,deadline,{previousPage=null,previousSignature=null}={}){
 let last='';
 while(Date.now()<deadline){
  const v=await bounded(subject.evaluate(fn),Math.min(deadline,Date.now()+5000));const signature=JSON.stringify(v);
  if(!v.loading&&v.page!==previousPage&&signature!==previousSignature&&signature===last)return v;
  last=signature;await new Promise(r=>setTimeout(r,250));
 }
 throw Error('quality-ui-stage-timeout');
}
async function goFirst(subject,deadline){
 const first=subject.locator('ul.ant-pagination li.ant-pagination-item[title="1"]');
 if(await first.count()&&!(await first.getAttribute('class')).includes('ant-pagination-item-active'))await first.click({timeout:budget(deadline)});
}
export async function allPages(subject,fn,deadline,validate){
 await goFirst(subject,deadline);let page=await stable(subject,fn,Math.min(deadline,Date.now()+15000));let rows=[];const totals=[];const visited=new Set();
 for(let n=0;n<1000;n++){
  if(visited.has(page.page))throw Error('quality-pagination-cycle');visited.add(page.page);totals.push(page.total);
  rows.push(...(page.rows||page.products));
  if(!page.hasNext)break;
  const previousPage=page.page;
  await subject.locator('ul.ant-pagination li.ant-pagination-next:not(.ant-pagination-disabled)').click({timeout:budget(deadline)});
  page=await stable(subject,fn,Math.min(deadline,Date.now()+15000),{previousPage});
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
 await goFirst(page,deadline);let current=await stable(page,merchantDom,Math.min(deadline,Date.now()+15000));
 for(let n=0;n<1000;n++){
  const rows=await page.locator('tbody tr.ant-table-row').evaluateAll(es=>es.map(e=>e.querySelector('td')?.textContent?.trim()));
  const indexes=rows.flatMap((name,i)=>compact(name)===compact(store.name)?[i]:[]);
  if(indexes.length>1)throw Error('quality-store-identity-ambiguous');
  if(indexes.length===1){const row=page.locator('tbody tr.ant-table-row').nth(indexes[0]);const popup=page.waitForEvent('popup',{timeout:budget(deadline,10000)});await row.getByRole('button',{name:'去完成',exact:true}).click({timeout:budget(deadline)});return await popup;}
  if(!current.hasNext)return null;
  const previousPage=current.page;await page.locator('ul.ant-pagination li.ant-pagination-next:not(.ant-pagination-disabled)').click({timeout:budget(deadline)});current=await stable(page,merchantDom,Math.min(deadline,Date.now()+15000),{previousPage});
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
 const codeVersion=await integrity();const day=dayNow();const folder=path.join(BASE,'.runtime/days',day),stateFile=path.join(folder,'state.json');
 let state;try{state=JSON.parse(await fs.readFile(stateFile,'utf8'));}catch(e){if(e.code!=='ENOENT')throw e;state={schemaVersion:1,day,workflowId:FLOW,snapshotComplete:false,stores:[],total:null,finalReconciled:false};}
 if(state.day!==day||state.workflowId!==FLOW)throw Error('quality-state-binding-invalid');
 if(!execute)return {ok:true,mode:'inspect-state-only',summary:aggregate(state),browserActions:0,sendAttempts:0};
 const clock=shanghaiClock();if(clock.hour<17)return {ok:false,reason:'quality-not-due',sendAttempts:0};const closingPriority=clock.hour===18&&clock.minute>=30&&clock.minute<35;
 const deadline=segmentDeadline();if(closingPriority||!canStartStore(deadline))return {ok:false,reason:'quality-yield-to-fixed-duty',continuation:true,summary:aggregate(state),sendAttempts:0};
 if(aggregate(state).ok)return {ok:true,summary:aggregate(state),stateFile,runtimeModelDecisions:0,sendAttempts:0};
 const {acquirePostLease,releasePostLease}=await import(path.join(POST,'scripts/lease.mjs'));
 const lease=await acquireSegmentLease(acquirePostLease,'quality-segment-'+crypto.randomUUID());if(!lease)return {ok:false,reason:'quality-post-busy',continuation:true,sendAttempts:0};
 let browser,page,originalUrl,detail;
 try{
  const conn=await(await import(path.join(POST,'scripts/connect.mjs'))).connectToPost();browser=conn.browser;
  const pages=conn.context.pages().filter(p=>p.url().startsWith('https://open.shop.ele.me/manager/'));
  if(pages.length!==1)throw Error('quality-service-page-not-unique');page=pages[0];originalUrl=page.url();
  const accountLabel=await navigate(page,deadline);
  if(state.accountLabel&&state.accountLabel!==accountLabel)throw Error('quality-account-scope-changed');state.accountLabel=accountLabel;
  if(!state.snapshotComplete){const snapshot=await allPages(page,merchantDom,deadline,validateMerchants);state={...state,snapshotComplete:true,total:snapshot.total,snapshotAt:new Date().toISOString(),stores:snapshot.rows.map(s=>({...s,state:'pending'}))};await atomic(stateFile,state);}
  let count=0;
  const candidates=[...state.stores.filter(s=>safeRetryEligible(s,codeVersion)).sort((a,b)=>(a.state==='pending'?0:1)-(b.state==='pending'?0:1)),...state.stores.filter(s=>s.state==='unknown'&&s.submission).sort((a,b)=>(a.lastCheckedAt||'').localeCompare(b.lastCheckedAt||''))];
  for(const store of candidates){
   if(count>=20||!canStartStore(deadline))break;
   const storeDeadline=Math.min(deadline,Date.now()+60000);count++;
   if(!store.submission){store.attemptCount=(store.attemptCount||0)+1;store.attemptsForVersion=store.lastAttemptVersion===codeVersion?(store.attemptsForVersion||0)+1:1;store.lastAttemptVersion=codeVersion;store.lastAttemptAt=new Date().toISOString();await atomic(stateFile,state);}
   try{
    detail=await openStore(page,store,storeDeadline);if(!detail){store.state='blocked';store.reason='merchant-no-longer-in-unfinished-list';continue;}
    const frame=await productFrame(detail,store,storeDeadline);await noModal(frame);
    const current=await allPages(frame,productDom,storeDeadline,validateProducts);
    if(store.submission){
     const verdict=reconcileProducts(store.before,current);store.after=current;store.state=verdict.state;store.reason=verdict.reason;store.remaining=verdict.remaining;store.lastCheckedAt=new Date().toISOString();store.reconciliation={mode:'read-only',submissionKey:store.submission.key,observedAt:store.lastCheckedAt,state:verdict.state};if(verdict.state==='completed')store.completedAt=store.lastCheckedAt;continue;
    }
    const before=current;store.before=before;
    const submissionsDir=path.join(BASE,'.runtime/submissions');await fs.mkdir(submissionsDir,{recursive:true,mode:0o700});
    const history=[];for(const filename of await fs.readdir(submissionsDir)){if(filename.startsWith(store.shopId+'-')&&filename.endsWith('.json'))history.push(JSON.parse(await fs.readFile(path.join(submissionsDir,filename),'utf8')));}
    const prior=priorSubmission(history,store.shopId,current);
    if(prior){store.before=prior.before;store.submission={state:'unknown',key:prior.key,at:prior.at,taskIds:prior.taskIds,sourceFile:path.join(submissionsDir,store.shopId+'-'+prior.key+'.json')};const verdict=reconcileProducts(prior.before,current);store.after=current;store.state=verdict.state;store.reason='prior-day-or-prior-segment-submission-read-only:'+verdict.reason;store.lastCheckedAt=new Date().toISOString();store.reconciliation={mode:'read-only',submissionKey:prior.key,observedAt:store.lastCheckedAt,state:verdict.state};continue;}
    if(before.total===0){store.state='completed';store.reason='platform-has-no-product-problems';store.completedAt=new Date().toISOString();continue;}
    if(before.products.every(p=>!p.hasSuggestion)){store.state='manual_required';store.reason='no-platform-suggestion';store.remaining=before.total;continue;}
    await goFirst(frame,storeDeadline);
    await frame.locator('label').filter({hasText:'全选本页'}).locator('input[type=checkbox]').check({timeout:budget(storeDeadline)});
    await frame.getByRole('button',{name:'一键优化类目详情',exact:true}).click({timeout:budget(storeDeadline)});
    const pop=frame.locator('.ant-popover.ant-popconfirm:visible');await pop.waitFor({state:'visible',timeout:budget(storeDeadline)});
    const text=compact(await pop.innerText());if(!text.includes('优化全部类目详情问题')||!text.includes('优化后，有建议的类目详情将自动采纳平台建议信息，其余的请手动优化'))throw Error('quality-optimization-confirmation-scope-invalid');
    if(!maySubmit(store))throw Error('quality-submission-already-attempted');
    store.submission={state:'attempted',key:submissionKey(store.shopId,before),at:new Date().toISOString(),taskIds:before.products.map(p=>p.taskId)};
    const intentFile=path.join(submissionsDir,store.shopId+'-'+store.submission.key+'.json');
    await atomic(intentFile,{schemaVersion:1,day,shopId:store.shopId,before,...store.submission});store.submission.sourceFile=intentFile;await atomic(stateFile,state);
    await pop.getByRole('button',{name:'确认优化',exact:true}).click({timeout:budget(storeDeadline)});
    await pop.waitFor({state:'hidden',timeout:budget(storeDeadline,15000)});
    let after=await allPages(frame,productDom,storeDeadline,validateProducts),verdict=reconcileProducts(before,after);
    while(verdict.state==='unknown'&&Date.now()<storeDeadline-1500){await new Promise(r=>setTimeout(r,500));after=await allPages(frame,productDom,storeDeadline,validateProducts);verdict=reconcileProducts(before,after);}
    store.after=after;store.state=verdict.state;store.reason=verdict.reason;store.remaining=verdict.remaining;store.submission.state=verdict.state==='completed'||verdict.state==='manual_required'?'observed':'unknown';store.completedAt=verdict.state==='completed'?new Date().toISOString():null;
   }catch(e){store.state=store.submission?'unknown':'blocked';store.reason=String(e.message||e).slice(0,250);store.errors=store.errors||[];store.errors.push({at:new Date().toISOString(),reason:store.reason,attempt:store.attemptCount||0,codeVersion});if(!store.submission)store.retryAt=Date.now()+600000;}
   finally{if(detail){await bounded(detail.close(),Date.now()+5000).catch(()=>{});detail=null;}await atomic(stateFile,state);}
  }
  if(state.stores.every(s=>s.state==='completed')){
   const remaining=await refreshFinalRoster(page,deadline,state.accountLabel);
   const known=new Set(state.stores.map(s=>compact(s.name)));
   const added=remaining.rows.filter(s=>!known.has(compact(s.name)));
   if(added.length){state.stores.push(...added.map(s=>({...s,state:'pending'})));state.total=state.stores.length;state.finalReconciled=false;}
   else{state.finalReconciled=true;state.finalReconciledAt=new Date().toISOString();}
  }
  await atomic(stateFile,state);return {ok:aggregate(state).ok,continuation:state.stores.some(s=>['pending','unknown'].includes(s.state)),summary:aggregate(state),stateFile,runtimeModelDecisions:0,sendAttempts:0};
 }finally{
  try{if(detail)await bounded(detail.close(),Date.now()+5000).catch(()=>{});if(page&&originalUrl&&!page.isClosed()&&page.url()!==originalUrl)await page.goto(originalUrl,{waitUntil:'domcontentloaded',timeout:10000}).catch(()=>{});}
  finally{if(browser)await bounded(browser.close(),Date.now()+5000).catch(()=>{});await releasePostLease(lease);}
 }
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
 try{if(process.argv.length!==3||!['--execute','--inspect'].includes(process.argv[2]))throw Error('usage: --execute|--inspect');const r=await runSegment({execute:process.argv[2]==='--execute'});console.log(JSON.stringify(r));process.exitCode=r.ok?0:1;}catch(e){console.log(JSON.stringify({ok:false,reason:String(e.message||e).slice(0,300),runtimeModelDecisions:0,sendAttempts:0}));process.exitCode=1;}
}
