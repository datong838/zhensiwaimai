import assert from 'node:assert/strict';
import {enterShopFromResult} from '../scripts/decoration_collector.mjs';
let count=1,entered=0;
const li={click(){throw Error('row-click-only-selects-not-entry');},locator(selector){assert.equal(selector,'span[class^="itemShopName__"]');return {count:async()=>count,dispatchEvent:async event=>{assert.equal(event,'click');entered++;}};}};
await enterShopFromResult(li);assert.equal(entered,1);
for(count of [0,2]) {await assert.rejects(()=>enterShopFromResult(li),/not-unique/);assert.equal(entered,1);}
console.log(JSON.stringify({ok:true,tests:3,sendAttempts:0}));
