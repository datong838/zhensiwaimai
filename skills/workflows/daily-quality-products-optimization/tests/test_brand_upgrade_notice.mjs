import assert from 'node:assert/strict';
import {BRAND_UPGRADE_ASSET,knownBrandUpgrade,dismissKnownBrandUpgrade} from '../scripts/quality_optimizer.mjs';

const notice={tag:'DIV',className:'updateModalWrapper__observed',descendants:3,maskCount:1,modalCount:1,
 buttonCount:1,buttonTag:'DIV',buttonVisible:true,nativeControls:0,text:'',image:`url("${BRAND_UPGRADE_ASSET}")`};
let tests=0;
assert.equal(knownBrandUpgrade(notice),true);tests++;
for(const change of [{tag:'FORM'},{className:'accountRiskModal'},{descendants:4},{maskCount:0},
 {maskCount:2},{modalCount:0},{modalCount:2},{buttonCount:0},{buttonCount:2},{buttonTag:'INPUT'},
 {buttonVisible:false},{nativeControls:1},{text:'验证码'},{image:'none'},
 {image:`url("${BRAND_UPGRADE_ASSET}?changed=1")`},{image:'url("https://other.example/update.png")'}]){
 assert.equal(knownBrandUpgrade({...notice,...change}),false);tests++;
}
function fixture({count=1,snapshot=notice,clickError=false,hideError=false,url='https://melody.shop.ele.me/app/shop/123/food-rectify'}={}){
 const calls={clicks:0,hidden:0,reads:0};
 const wrapper={count:async()=>count,evaluate:async()=>{calls.reads++;return snapshot;},
  locator:selector=>{assert.equal(selector,'[class^="updateBtn__"]');return {click:async()=>{calls.clicks++;if(clickError)throw Error('click timeout');}};},
  waitFor:async options=>{assert.equal(options.state,'hidden');calls.hidden++;if(hideError)throw Error('notice did not close');}};
 return {calls,page:{url:()=>url,locator:selector=>{assert.equal(selector,'[class^="updateModalWrapper__"]:visible');return wrapper;}}};
}
const absent=fixture({count:0});assert.deepEqual(await dismissKnownBrandUpgrade(absent.page,Date.now()+10000,'123'),{dismissed:false});assert.equal(absent.calls.clicks,0);tests++;
const known=fixture();assert.equal((await dismissKnownBrandUpgrade(known.page,Date.now()+10000,'123')).dismissed,true);assert.equal(known.calls.clicks,1);assert.equal(known.calls.hidden,1);tests++;
await assert.rejects(dismissKnownBrandUpgrade(known.page,Date.now()+10000,'123'),/reappeared/);assert.equal(known.calls.clicks,1);tests++;
for(const config of [{count:2},{snapshot:{...notice,text:'风险验证'}},{snapshot:{...notice,image:'none'}},
 {snapshot:{...notice,nativeControls:1}},{snapshot:{...notice,buttonCount:2}}]){
 const f=fixture(config);await assert.rejects(dismissKnownBrandUpgrade(f.page,Date.now()+10000,'123'),/quality-upgrade/);assert.equal(f.calls.clicks,0);tests++;
}
for(const config of [{url:'https://other.example/app/shop/123/food-rectify'},
 {url:'https://melody.shop.ele.me/app/shop/456/food-rectify'},{url:'https://melody.shop.ele.me/login'}]){
 const f=fixture(config);await assert.rejects(dismissKnownBrandUpgrade(f.page,Date.now()+10000,'123'),/page-invalid/);assert.equal(f.calls.clicks,0);tests++;
}
for(const config of [{clickError:true},{hideError:true}]){
 const f=fixture(config);await assert.rejects(dismissKnownBrandUpgrade(f.page,Date.now()+10000,'123'));
 await assert.rejects(dismissKnownBrandUpgrade(f.page,Date.now()+10000,'123'),/reappeared/);
 assert.equal(f.calls.clicks,1);tests++;
}
const expired=fixture();await assert.rejects(dismissKnownBrandUpgrade(expired.page,Date.now()-1,'123'),/segment-yield/);assert.equal(expired.calls.clicks,0);tests++;
console.log(JSON.stringify({ok:true,tests,realBrowserActions:0,productSubmissions:0,sendAttempts:0}));
