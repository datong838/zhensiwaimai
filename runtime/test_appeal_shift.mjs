import assert from 'node:assert/strict';
import {shiftPlan,runShift,parseOriginalReceipt,closingReadOnlyDecision,readOriginalClosing,closingBusinessDate} from './appeal_shift.mjs';
const date=time=>new Date(`2026-10-24T${time}:00+08:00`);
let tests=0;
for(const platform of ['taobao','meituan']) {
 for(const time of ['12:59','19:00']) {assert.throws(()=>shiftPlan(platform,date(time)),/outside-authorized/);tests++;}
 for(const time of ['13:00','15:00','17:00','18:30']) {
  const seen=[];const result=await runShift(platform,{date:date(time),readClosing:async()=>null,runner:async step=>{seen.push(step.stage);return {ok:true,verified:true};}});
  assert.equal(result.ok,true);assert.deepEqual(seen,time==='18:30'?['appeal','build','deliver']:['appeal']);tests++;
 }
 for(const fail of ['appeal','build','deliver']) {
  const seen=[];const result=await runShift(platform,{date:date('18:30'),readClosing:async()=>null,runner:async step=>{seen.push(step.stage);return {ok:step.stage!==fail,verified:step.stage!==fail};}});
  assert.equal(result.ok,false);assert.equal(seen.at(-1),fail);tests++;
 }
 for(const time of ['18:30','18:59']) {assert.deepEqual(shiftPlan(platform,date(time)).steps.map(x=>x.stage),['appeal','build','deliver']);tests++;}
 assert.deepEqual(shiftPlan(platform,date('18:29')).steps.map(x=>x.stage),['appeal']);tests++;
 const earlyFailure=await runShift(platform,{date:date('17:00'),readClosing:async()=>null,runner:async()=>({ok:false,reason:'appeal-failed'})});assert.equal(earlyFailure.ok,false);assert.equal(earlyFailure.stage,'appeal');tests++;
 const failed=await runShift(platform,{date:date('18:30'),readClosing:async()=>null,runner:async()=>{throw Error('unknown-existing-attempt');}});
 assert.equal(failed.ok,false);assert.equal(failed.results.length,0);tests++;
}
assert.throws(()=>shiftPlan('other',date('13:00')),/unsupported/);tests++;
const originalFailure=await runShift('meituan',{date:date('13:00'),readClosing:async()=>null,runner:async()=>({ok:false,error:'jinsha-page-count:2'})});assert.equal(originalFailure.reason,'jinsha-page-count:2');tests++;
assert.equal(parseOriginalReceipt('log\n'+JSON.stringify({ok:false,error:'jinsha-page-count:2'}),1).error,'jinsha-page-count:2');tests++;
assert.throws(()=>parseOriginalReceipt(JSON.stringify({ok:true}),1),/conflict/);tests++;
assert.throws(()=>parseOriginalReceipt('no-json',1),/missing/);tests++;
console.log(JSON.stringify({ok:true,tests,sendAttempts:0}));

const group='上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰';
const excel={groupName:group,payloadType:'file',ok:true,verified:true,state:'verified',sendAttempts:1};
const image={groupName:group,payloadType:'image',ok:false,verified:false,state:'unknown',sendAttempts:1};
for(const state of ['unknown','attempted']){assert.deepEqual(closingReadOnlyDecision(excel,{...image,state}),{complete:false});tests++;}
for(const count of [null,undefined,2]){assert.deepEqual(closingReadOnlyDecision(excel,{...image,state:'blocked',sendAttempts:count}),{complete:false});tests++;}
assert.deepEqual(closingReadOnlyDecision(excel,{...image,ok:true,verified:true,state:'verified'}),{complete:true});tests++;
for(const x of [null,{...excel,groupName:'wrong'},{...excel,payloadType:'image'},{...excel,state:'unknown'},{...excel,sendAttempts:0},{...excel,sendAttempts:true}]){assert.equal(closingReadOnlyDecision(x,image),null);tests++;}
for(const x of [null,{...image,groupName:'wrong'},{...image,payloadType:'file'},{...image,state:'blocked',sendAttempts:0}]){assert.equal(closingReadOnlyDecision(excel,x),null);tests++;}
for(const platform of ['meituan','taobao']){
 for(const complete of [false,true]){let calls=0;const r=await runShift(platform,{date:date('18:30'),readClosing:async()=>({complete,businessDate:'2026-10-23'}),runner:async()=>{calls++;throw Error('must not execute');}});assert.equal(calls,0);assert.equal(r.ok,complete);assert.equal(r.sendAttempts,0);assert.equal(r.results.length,0);tests++;}
 let reads=0;await runShift(platform,{date:date('17:00'),readClosing:async()=>{reads++;return {complete:false};},runner:async()=>({ok:true})});assert.equal(reads,0);tests++;
 const invalid=await runShift(platform,{date:date('18:30'),readClosing:async()=>{throw Error('bad-json');},runner:async()=>{throw Error('must not execute');}});assert.match(invalid.reason,/prior-evidence-unreadable/);assert.equal(invalid.sendAttempts,0);tests++;
}
for(const [time,expected]of [['2026-10-28T00:01:00+08:00','2026-10-27'],['2026-10-27T15:59:59Z','2026-10-26'],['2026-10-27T16:00:00Z','2026-10-27'],['2027-01-01T18:30:00+08:00','2026-12-31'],['2028-03-01T18:30:00+08:00','2028-02-29']]){assert.equal(closingBusinessDate(new Date(time)),expected);tests++;}
await assert.rejects(readOriginalClosing('other',date('18:30')),/unsupported/);tests++;
console.log(JSON.stringify({ok:true,allTests:tests,closingReadOnlyTests:tests-33,sendAttempts:0}));
