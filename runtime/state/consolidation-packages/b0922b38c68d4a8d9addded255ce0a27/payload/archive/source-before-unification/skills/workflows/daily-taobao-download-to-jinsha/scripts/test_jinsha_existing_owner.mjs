import assert from 'node:assert/strict';
import { completedJinshaOwnerMarker, ownedJinshaPageDecision, jinshaReusePageDecision } from './background_browser_executor.mjs';
const receipt={executor:'background-browser-executor',ok:true,stage:'completed',phase:'completed',cleanupStatus:'completed',jinshaTaskStrategy:'reused-existing-work-target',businessDate:'2026-10-24',runId:'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',profiles:{jinsha:{profile:'jinsha-business',port:9232,pid:123}}};
const marker=completedJinshaOwnerMarker(receipt,123),url='https://data.guoshuyufen.com/#/businessData/realTimeData';
assert.equal(marker,'aos-background-task:taobao-jinsha-aaaaaaaa-bbbb-cccc-dddd-eeeeee');
const proof={receipt,file:'/fixed/receipt.json',sha256:'proof',createdAt:2000};
assert.equal(jinshaReusePageDecision([url]).ok,true);
assert.equal(jinshaReusePageDecision([url,url]).ok,false);
const decide=(pages,proofs,pid=123)=>ownedJinshaPageDecision(pages,proofs,pid,1000);
const chosen=decide([{url,marker:''},{url,marker}], [proof]);
assert.equal(chosen.ok,true);assert.equal(chosen.index,1);
assert.equal(decide([{url,marker},{url,marker}],[proof]).ok,false);
assert.equal(decide([{url,marker:''}],[proof]).ok,false);
assert.equal(decide([{url:'https://other.test/',marker}],[proof]).ok,false);
assert.equal(decide([{url,marker}],[proof,proof]).ok,false);
assert.equal(decide([{url,marker}],[{...proof,createdAt:999}]).ok,false);
for(const change of [{ok:false},{phase:'unknown'},{cleanupStatus:'not-completed'}, {executor:'other'},{jinshaTaskStrategy:'other'},{runId:'../invalid'},{profiles:{jinsha:{profile:'other',port:9232,pid:123}}},{profiles:{jinsha:{profile:'jinsha-business',port:9233,pid:123}}},{profiles:{jinsha:{profile:'jinsha-business',port:9232,pid:124}}}]) {
 assert.equal(completedJinshaOwnerMarker({...receipt,...change},123),null);
 assert.equal(decide([{url,marker}],[{...proof,receipt:{...receipt,...change}}]).ok,false);
}
assert.equal(completedJinshaOwnerMarker(receipt,'123'),null);
console.log(JSON.stringify({ok:true,scenarios:17,realUIActions:0}));
