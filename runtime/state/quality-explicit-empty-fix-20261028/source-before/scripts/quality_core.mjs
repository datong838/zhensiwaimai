import crypto from 'node:crypto';
export const FLOW='daily-quality-products-optimization';
export const NAME='淘宝闪购低优质商品的全部门店商品整改优化';
export const COMPANY='上海臻肆文化传播有限公司';
export const METRIC='material_quality_entree_proportion_rate';
export const compact=v=>String(v??'').replace(/\s+/g,'');
export const digest=v=>crypto.createHash('sha256').update(JSON.stringify(v)).digest('hex');
export const notification=n=>`淘宝闪购 优质商品率低 店铺全部店铺优化完成 （今日执行了 ${n} 家）`;
export function validateMerchants(snapshot){
 if(!Number.isSafeInteger(snapshot.total)||snapshot.total<0||!Array.isArray(snapshot.rows)||snapshot.rows.length!==snapshot.total)throw Error('quality-merchant-snapshot-incomplete');
 const names=snapshot.rows.map(r=>compact(r.name));
 if(names.some(n=>!n)||new Set(names).size!==names.length)throw Error('quality-merchant-identity-ambiguous');
 if(snapshot.rows.some(r=>r.metric!=='优质商品率低'||r.status!=='未完成'||!r.name))throw Error('quality-merchant-scope-invalid');
 return snapshot;
}
export function validateProducts(snapshot){
 if(!Number.isSafeInteger(snapshot.total)||snapshot.total<0||!Array.isArray(snapshot.products)||snapshot.products.length!==snapshot.total)throw Error('quality-product-snapshot-incomplete');
 const ids=snapshot.products.map(p=>p.taskId);
 if(ids.some(id=>!/^\d+$/.test(id))||new Set(ids).size!==ids.length)throw Error('quality-product-identity-ambiguous');
 for(const p of snapshot.products){if(!p.name||!Array.isArray(p.issues)||!p.issues.length||typeof p.hasSuggestion!=='boolean')throw Error('quality-product-schema-invalid');}
 return snapshot;
}
export function noExecutableSuggestions(snapshot){
 if(snapshot?.loading!==false||snapshot?.hasNext!==false||!(snapshot?.total>0))return false;
 try{validateProducts(snapshot);}catch{return false;}
 return snapshot.products.every(product=>product.hasSuggestion===false);
}
export function optimizationDisposition(snapshot,action){
 if(snapshot?.imageOnly!==undefined){
  const image=snapshot.imageOnly;
  if(!Number.isSafeInteger(snapshot.total)||snapshot.total<=0||snapshot.loading!==false
    ||snapshot.page!==1||snapshot.hasNext!==false||!Array.isArray(snapshot.products)
    ||snapshot.products.length!==snapshot.total||action?.count!==0||action.disabled!==null
    ||image?.rowStructureValid!==true||image.buttonCount!==0
    ||!Number.isSafeInteger(image.hiddenTabOverflowCount)||image.hiddenTabOverflowCount<0||image.hiddenTabOverflowCount>1
    ||!Array.isArray(image.tabs)||image.tabs.length!==1||image.tabs[0]?.selected!==true
    ||image.tabs[0].text!==`图片问题(${snapshot.total})`
    ||JSON.stringify(image.headers)!==JSON.stringify(['商品名称','图片问题','建议内容','操作'])
    ||!Array.isArray(image.operatorTexts)||image.operatorTexts.length!==snapshot.total
    ||image.operatorTexts.some(text=>compact(text)!=='手动优化申诉'))throw Error('quality-product-image-only-incomplete');
  validateProducts(snapshot);
  if(snapshot.products.some(product=>typeof product.taskId!=='string'||typeof product.name!=='string'||!product.name.trim()
    ||product.hasSuggestion!==false||product.issues.some(issue=>!issue||
    typeof issue.kind!=='string'||!issue.kind.trim()||issue.current!==''||issue.suggestion!=='暂无建议')))
   throw Error('quality-product-image-only-incomplete');
  return {action:'skip',reason:'image-only-no-automatic-suggestions'};
 }
 if(!Number.isSafeInteger(snapshot?.total)||snapshot.total<0||snapshot.loading!==false
   ||!Number.isSafeInteger(snapshot.page)||snapshot.page<1||typeof snapshot.hasNext!=='boolean'
   ||!Array.isArray(snapshot.products)||snapshot.products.length>snapshot.total
   ||(snapshot.total>0&&snapshot.products.length===0)
   ||(snapshot.total===0&&(snapshot.products.length!==0||snapshot.hasNext))
   ||(snapshot.page===1&&!snapshot.hasNext&&snapshot.products.length!==snapshot.total))throw Error('quality-product-readiness-invalid');
 validateProducts({total:snapshot.products.length,products:snapshot.products});
 if(!Number.isSafeInteger(action?.count)||action.count<0||(action.count===1&&typeof action.disabled!=='boolean'))throw Error('quality-product-action-not-ready');
 if(snapshot.total===0)return {action:'skip',reason:'no-available-platform-optimization'};
 if(noExecutableSuggestions(snapshot))return {action:'skip',reason:'no-executable-platform-suggestions'};
 if(action.count!==1)throw Error('quality-product-action-not-ready');
 if(action.disabled)return {action:'skip',reason:'no-available-platform-optimization'};
 return {action:'submit'};
}
export function submissionKey(shopId,products){
 if(!/^\d+$/.test(shopId))throw Error('quality-shop-id-invalid');validateProducts(products);
 return digest({shopId,taskIds:products.products.map(p=>p.taskId).sort(),scope:'all-category-details'});
}
export function reconcileProducts(before,after){
 validateProducts(before);validateProducts(after);
 const previous=new Set(before.products.map(p=>p.taskId));
 const newTasks=after.products.filter(p=>!previous.has(p.taskId));
 if(newTasks.length)return {state:'unknown',reason:'new-product-tasks-during-submission',remaining:after.total};
 if(after.total===0)return {state:'completed',reason:'all-product-problems-cleared',remaining:0};
 if(after.products.every(p=>!p.hasSuggestion))return {state:'manual_required',reason:'remaining-products-have-no-platform-suggestion',remaining:after.total};
 return {state:'unknown',reason:'submitted-product-tasks-still-pending',remaining:after.total};
}
export function maySubmit(store){return !store.submission && !['completed','unknown','manual_required'].includes(store.state);}
export function executionNotice(handled,unconfirmed=0){return unconfirmed?`淘宝闪购 优质商品率低 门店整改流程已按顺序执行完毕（今日执行了 ${handled} 家；其中 ${unconfirmed} 家结果未确认，详见Excel）`:notification(handled);}
export function recordedUnknown(store,day){
 const r=store.executionRecord,sub=store.submission,rec=store.reconciliation;
 return store.state==='unknown'&&store.executionRecorded===true&&r?.day===day&&r?.kind==='attempted-unconfirmed'
  &&sub?.day===day&&sub?.shopId===store.shopId&&sub?.eventId===day+'-quality-'+store.shopId
  &&r.submissionSha256===digest(sub)&&/^[a-f0-9]{64}$/.test(r.intentSha256||'')
  &&rec?.mode==='read-only'&&rec.submissionSha256===r.submissionSha256&&rec.observedAt===r.readonlyObservedAt
  &&Number.isSafeInteger(rec.currentTotal)&&rec.currentTotal>=0;
}
export const SINGLE_PASS='single-pass-per-day-v1';
export function singlePassNotice(handled,unconfirmed=0,failed=0,rowErrors=0,imageOnly=0){
 if(imageOnly)return `淘宝闪购 优质商品率低 门店整改流程已按顺序执行完毕（今日记录了 ${handled} 家门店；${imageOnly} 家仅有图片问题且平台无自动建议，${failed} 家未能执行，${unconfirmed} 家结果未确认，另有 ${rowErrors} 条访问异常，详见Excel）`;
 if(failed||rowErrors)return `淘宝闪购 优质商品率低 门店整改流程已按顺序执行完毕（今日记录了 ${handled} 家门店；${failed} 家未能执行，${unconfirmed} 家结果未确认，另有 ${rowErrors} 条访问异常，详见Excel）`;
 return executionNotice(handled,unconfirmed);
}
export function singlePassSummary(state){
 const stores=state.stores||[],optimized=stores.filter(s=>s.state==='completed'&&['confirmed','popoverClosed','uiStable'].every(k=>s.operation?.[k]===true)).length;
 const checked=stores.filter(s=>s.state==='checked_no_action').length;
 const imageOnly=stores.filter(s=>s.state==='checked_no_action'&&s.reason==='image-only-no-automatic-suggestions').length;
 const unconfirmed=stores.filter(s=>['unknown','attempted'].includes(s.state)&&s.submission?.day===state.day&&s.submission?.shopId===s.shopId&&s.submission?.eventId===state.day+'-quality-'+s.shopId).length;
 const failed=stores.length-optimized-checked-unconfirmed,rowErrors=(state.rowErrors||[]).length;
 return {ok:state.scopeFinished===true,total:stores.length,completed:optimized,optimized,checkedNoAction:checked,attemptedUnconfirmed:unconfirmed,failed,rowErrorCount:rowErrors,
  handled:stores.length,recordRows:stores.length+rowErrors,pending:state.scopeFinished?0:1,unknown:unconfirmed,errors:failed+rowErrors,round:1,
  observedPlatformTotal:state.latestTotal??null,text:state.scopeFinished?singlePassNotice(stores.length,unconfirmed,failed,rowErrors,imageOnly):null};
}
export function finishSinglePass(state,current){
 if(state.executionPolicy!==SINGLE_PASS||state.cursor?.round!==1||current.hasNext!==false||current.page!==state.cursor.page||state.cursor.row<current.rows.length)return false;
 if(state.scopeFinished)return true;
 const ended=new Date().toISOString(),entry={round:1,fromPage:1,lastPage:current.page,lastPageHasNext:false,rowsVisited:state.cursor.rowsVisited,platformTotal:current.total,
  newShops:state.cursor.newShops,rowErrors:(state.rowErrors||[]).length,independentStores:state.stores.length,finishedAt:ended};
 state.rounds=[entry];state.scopeFinished=true;state.finishedAt=ended;state.scopeFinishBasis={kind:'single-sequential-pass-reached-last-page',...entry};return true;
}
export function aggregate(state){
 if(state.executionPolicy===SINGLE_PASS)return singlePassSummary(state);
 const stores=state.stores||[],completed=stores.filter(s=>s.state==='completed'),checked=stores.filter(s=>s.state==='checked_no_action');
 const unknown=stores.filter(s=>['unknown','attempted'].includes(s.state)),recorded=unknown.filter(s=>recordedUnknown(s,state.day)),errors=stores.filter(s=>s.state==='blocked');
 const ok=state.scopeFinished===true&&unknown.length===recorded.length&&errors.length===0,handled=completed.length+checked.length+recorded.length;
 return {ok,total:stores.length,completed:completed.length,optimized:completed.length,checkedNoAction:checked.length,attemptedUnconfirmed:recorded.length,handled,
  pending:state.scopeFinished?0:1,unknown:unknown.length,unrecordedUnknown:unknown.length-recorded.length,errors:errors.length,round:state.cursor?.round||1,
  observedPlatformTotal:state.latestTotal??null,text:ok?executionNotice(handled,recorded.length):null};
}
export function shanghaiClock(now=Date.now()){
 const parts=new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Shanghai',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).formatToParts(new Date(now));
 return Object.fromEntries(parts.filter(p=>['hour','minute','second'].includes(p.type)).map(p=>[p.type,Number(p.value)]));
}
export function segmentDeadline(now=Date.now(),budgetMs=120000){
 const next=(Math.floor(now/1800000)+1)*1800000;
 return Math.min(now+budgetMs,next-10000);
}
export function canStartStore(deadline,now=Date.now()){return deadline-now>=65000;}
export function safeRetryEligible(store,codeVersion,now=Date.now()){
 if(store.submission)return false;
 if(store.state==='pending')return true;
 if(store.state!=='blocked')return false;
 if(store.lastAttemptVersion!==codeVersion)return true;
 return (store.attemptsForVersion||0)<2&&Number.isFinite(store.retryAt)&&now>=store.retryAt;
}

export function scopeCompletionProof(state){
 if(!Array.isArray(state.rounds)||!Array.isArray(state.stores)||state.cursor?.newShops>0)return null;
 if(state.stores.some(s=>!['completed','checked_no_action'].includes(s.state)&&!recordedUnknown(s,state.day)))return null;
 if(new Set(state.stores.map(s=>s.shopId)).size!==state.stores.length)return null;
 for(let i=state.rounds.length-1;i>=0;i--){
  const round=state.rounds[i];
  if(round.newShops!==0||!Number.isSafeInteger(round.rowsVisited)||!Number.isSafeInteger(round.platformTotal)||round.rowsVisited<round.platformTotal||!Number.isFinite(Date.parse(round.finishedAt)))continue;
  if((state.rowErrors||[]).some(e=>e.round===round.round))continue;
  if(state.rounds.slice(i+1).some(r=>r.newShops>0))continue;
  return {kind:'complete-normal-sequential-round-no-new-daily-shops',sourceRound:round.round,rowsVisited:round.rowsVisited,platformTotal:round.platformTotal,
   newShops:0,rowErrors:0,independentStores:state.stores.length,sourceFinishedAt:round.finishedAt,roundRecordSha256:digest(round)};
 }
 return null;
}
export function normalRoundComplete(state){return scopeCompletionProof(state)!==null;}
