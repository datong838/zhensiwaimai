import assert from 'node:assert/strict';
import {ensureShopSelectorReady} from '../scripts/decoration_collector.mjs';
function fake(states, loginAfterReload=false) {
 let calls=0,reloads=0;
 return {url:()=>reloads&&loginAfterReload?'https://melody.shop.ele.me/login':'https://melody.shop.ele.me/app/chain/1',
 frames:()=>[{locator:()=>({first:()=>({isVisible:async()=>states[Math.min(calls++,states.length-1)]})})}],
 reload:async()=>{reloads++;},waitForTimeout:async()=>{},get reloads(){return reloads;}};
}
let page=fake([false]);assert.deepEqual(await ensureShopSelectorReady(page,0),{reloaded:false});assert.equal(page.reloads,0);
page=fake([true,false]);assert.deepEqual(await ensureShopSelectorReady(page,0),{reloaded:true});assert.equal(page.reloads,1);
page=fake([true]);await assert.rejects(()=>ensureShopSelectorReady(page,0),/shop-selector-loading-timeout/);assert.equal(page.reloads,1);
page=fake([true],true);await assert.rejects(()=>ensureShopSelectorReady(page,0),/brand-login-required/);assert.equal(page.reloads,1);
console.log(JSON.stringify({ok:true,tests:4,newSendAttempts:0}));
