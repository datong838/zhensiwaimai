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
export function aggregate(state){
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

export function normalRoundComplete(noNewRounds,handled,firstTotal,currentTotal){return noNewRounds>0&&handled>=Math.min(firstTotal??currentTotal,currentTotal);}
