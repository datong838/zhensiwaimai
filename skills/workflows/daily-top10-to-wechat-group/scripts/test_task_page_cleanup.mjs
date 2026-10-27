import assert from 'node:assert/strict';
import {ownsTaskMarker} from './desktop_background_executor.mjs';
const task='top10-fc9cfc45-4264-402e-b959-9570556ca28e';
const marker='aos-background-task:'+task;
const wrapped='nameStorage:'+encodeURIComponent(marker)+'?TRACERT_REF_referPageId=0.0_trace&TRACERT_REF_referO2oPageId=trace';
assert.equal(ownsTaskMarker(marker,task),true);
assert.equal(ownsTaskMarker(wrapped,task),true);
for(const value of ['',null,marker+'-other','prefix'+marker,'nameStorage:?TRACERT_REF_referPageId=trace',
  'nameStorage:'+encodeURIComponent(marker)+'?unknown=value',wrapped.replace('fc9cfc45','00000000'),
  'nameStorage:%ZZ?TRACERT_REF_referPageId=trace','nameStorage:'+encodeURIComponent(marker)+'-extra?TRACERT_REF_referPageId=trace']){
  assert.equal(ownsTaskMarker(value,task),false,String(value));
}
console.log(JSON.stringify({ok:true,tests:11,browserActions:0,sendAttempts:0}));
