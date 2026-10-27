import test from 'node:test';import assert from 'node:assert/strict';import {METRIC_ROUTES,normalizeCapture,lastJson} from './capture_receipt.mjs';
test('all eleven metrics have fixed page routing and M12 is rejected',()=>{
 assert.equal(Object.keys(METRIC_ROUTES).length,11);assert.equal(METRIC_ROUTES.M01,'comments');assert.equal(METRIC_ROUTES.M06,'customerStats');assert.equal(METRIC_ROUTES.M11,'stats__center');assert.throws(()=>normalizeCapture({}, {metric:'M12'}));
});
test('real JSON must be present; noisy logs cannot manufacture successful receipt',()=>{assert.deepEqual(lastJson('hello\n{\n "ok":true\n}\n'),{ok:true});assert.throws(()=>lastJson('DONE exit=0'));});
for(let n=1;n<=11;n++)test(`M${String(n).padStart(2,'0')} scope, time and screenshot contract`,()=>{
 const m=`M${String(n).padStart(2,'0')}`,options={metric:m,shopId:'101',shopName:'甲店'};
 const raw={ok:true,metric:m,shopId:'101',topName:'甲店',inner:n===1?'https://melody-comment.faas.ele.me/single':'https://melody-stats-next.ele.me/new/#/single/business-analysis',tabActive:true,timeCheck:{good:[{t:'近30日'}],bad:[],static30:true},times:n===11?[{target:'本周',after:'本周',ok:true},{target:'近30日',after:'近30日',ok:true},{target:'近30日',after:'近30日',ok:true}]:[{target:'近30日',after:'近30日',ok:true}],file:'a.png',files:n===11?['a.png','b.png','c.png']:['a.png'],shots:n===11?[{truncated:false},{truncated:false},{truncated:false}]:[{truncated:false}]};
 assert.equal(normalizeCapture(raw,options).scopeVerified,true);
 assert.throws(()=>normalizeCapture({...raw,topName:'乙店'},options));assert.throws(()=>normalizeCapture({...raw,inner:'https://melody-stats-next.ele.me/new/#/chain/business-analysis'},options));assert.throws(()=>normalizeCapture({...raw,shots:[{truncated:true}]},options));
 if(n===6)assert.match(normalizeCapture(raw,options).timeRange,/近7日/);
 if(n===11)assert.throws(()=>normalizeCapture({...raw,times:raw.times.map(t=>({...t,target:'近30日',after:'近30日'}))},options));
});

test('post-capture check requires exact restored chain seed, not just a logged-in single shop',async()=>{
 const {isRestoredChain}=await import('./capture_receipt.mjs');
 assert.equal(isRestoredChain('https://melody.shop.ele.me/app/chain/95708808/stats__center#app.chainshop.stats.center'),true);
 for(const u of ['https://melody.shop.ele.me/app/shop/101/stats__center#app.shop.stats.center','https://melody.shop.ele.me/app/chain/other/stats__center#app.chainshop.stats.center','https://example.com/'])assert.equal(isRestoredChain(u),false);
});
