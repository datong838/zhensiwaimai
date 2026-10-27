export const METRIC_ROUTES=Object.freeze(Object.fromEntries(Array.from({length:11},(_,i)=>{const id=`M${String(i+1).padStart(2,'0')}`;return [id,i===0?'comments':i<6?'customerStats':'stats__center'];})));
export function lastJson(text){for(const m of text.matchAll(/^\s*\{/gm)){try{return JSON.parse(text.slice(m.index).trim());}catch{}}throw Error('capture-json-missing');}
export function normalizeCapture(raw,{metric,shopId,shopName}){
 if(!Object.hasOwn(METRIC_ROUTES,metric)||raw?.ok!==true||raw.metric!==metric||String(raw.shopId)!==String(shopId)||raw.topName!==shopName)throw Error('capture-identity-mismatch');
 const inner=String(raw.inner||raw.innerUrl||'');let scopeVerified=false;
 try{const u=new URL(inner);scopeVerified=metric==='M01'?u.hostname==='melody-comment.faas.ele.me'&&!inner.includes('/chain/'):u.hostname==='melody-stats-next.ele.me'&&u.hash.includes('/single/');}catch{}
 let timeVerified=false;
 if(metric==='M01')timeVerified=raw.tabActive===true;
 else if(metric<'M07')timeVerified=!!raw.timeCheck&&!raw.timeCheck.bad?.length&&(metric==='M03'?raw.timeCheck.static30===true:raw.timeCheck.good?.some(t=>t.t==='近30日'));
 else timeVerified=raw.times?.length>0&&raw.times.every(t=>t.ok===true&&t.after===t.target);
 if(metric==='M11')timeVerified=timeVerified&&raw.times.length===3&&raw.times[0].after==='本周'&&raw.times.slice(1).every(t=>t.after==='近30日');
 const shots=raw.shots||[{file:raw.file,truncated:raw.truncated}];const files=raw.files||[raw.file];
 if(!scopeVerified||!timeVerified||shots.some(s=>s.truncated!==false)||files.length!==(metric==='M11'?3:1))throw Error('capture-contract-unverified');
 return {ok:true,metric,shopId:String(shopId),topName:shopName,scopeVerified,timeVerified,files,shots:shots.map(s=>({file:s.file,truncated:s.truncated,bytes:s.bytes})),truncated:false,timeRange:metric==='M01'?'平台评分快照':metric==='M06'?'互动行为固定近7日；顾客画像近30日':metric==='M11'?'数据概览本周；营业分析/出餐时效近30日':'近30日'};
}

export function isRestoredChain(raw){try{const u=new URL(raw);return u.origin==='https://melody.shop.ele.me'&&u.pathname==='/app/chain/95708808/stats__center'&&u.hash==='#app.chainshop.stats.center';}catch{return false;}}
