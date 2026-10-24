import assert from 'node:assert/strict';
import {shiftPlan,runShift} from './appeal_shift.mjs';
const date=time=>new Date(`2026-10-24T${time}:00+08:00`);
let tests=0;
for(const platform of ['taobao','meituan']) {
 for(const time of ['12:59','19:00']) {assert.throws(()=>shiftPlan(platform,date(time)),/outside-authorized/);tests++;}
 for(const time of ['13:00','15:00','17:00','18:30']) {
  const seen=[];const result=await runShift(platform,{date:date(time),runner:async step=>{seen.push(step.stage);return {ok:true,verified:true};}});
  assert.equal(result.ok,true);assert.deepEqual(seen,time==='18:30'?['appeal','build','deliver']:['appeal']);tests++;
 }
 for(const fail of ['appeal','build','deliver']) {
  const seen=[];const result=await runShift(platform,{date:date('18:30'),runner:async step=>{seen.push(step.stage);return {ok:step.stage!==fail,verified:step.stage!==fail};}});
  assert.equal(result.ok,false);assert.equal(seen.at(-1),fail);tests++;
 }
 const failed=await runShift(platform,{date:date('18:30'),runner:async()=>{throw Error('unknown-existing-attempt');}});
 assert.equal(failed.ok,false);assert.equal(failed.results.length,0);tests++;
}
assert.throws(()=>shiftPlan('other',date('13:00')),/unsupported/);tests++;
console.log(JSON.stringify({ok:true,tests,sendAttempts:0}));
