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
export function aggregate(state){
 const stores=state.stores||[];const complete=stores.filter(s=>s.state==='completed');
 const all=state.snapshotComplete===true&&stores.length===state.total&&complete.length===stores.length&&state.finalReconciled===true;
 return {ok:all,total:stores.length,completed:complete.length,pending:stores.filter(s=>s.state==='pending').length,
   unknown:stores.filter(s=>s.state==='unknown').length,manualRequired:stores.filter(s=>s.state==='manual_required').length,
   errors:stores.filter(s=>s.state==='blocked').length,text:all?notification(complete.length):null};
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
export function priorSubmission(records,shopId,current){
 validateProducts(current);const ids=new Set(current.products.map(p=>p.taskId));
 const overlapping=records.filter(r=>r.shopId===shopId&&Array.isArray(r.taskIds)&&r.taskIds.some(id=>ids.has(id)));
 if(overlapping.length>1)throw Error('quality-prior-submission-conflict');
 if(overlapping.length===1){const r=overlapping[0];if(r.key!==submissionKey(shopId,r.before))throw Error('quality-prior-submission-binding-invalid');return r;}
 return null;
}
export function safeRetryEligible(store,codeVersion,now=Date.now()){
 if(store.submission)return false;
 if(store.state==='pending')return true;
 if(store.state!=='blocked')return false;
 if(store.lastAttemptVersion!==codeVersion)return true;
 return (store.attemptsForVersion||0)<2&&Number.isFinite(store.retryAt)&&now>=store.retryAt;
}
