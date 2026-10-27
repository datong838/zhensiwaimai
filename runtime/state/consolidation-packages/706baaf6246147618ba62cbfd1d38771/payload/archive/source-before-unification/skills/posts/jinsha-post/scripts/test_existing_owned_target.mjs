import assert from 'node:assert/strict';
import {ownerMarker,ownedTargetDecision,selectExistingJinshaTarget,assertSelectedJinshaTarget} from './existing_owned_target.mjs';
const pid=123,started=1000,receipt={executor:'background-browser-executor',ok:true,stage:'completed',phase:'completed',cleanupStatus:'completed',jinshaTaskStrategy:'reused-existing-work-target',businessDate:'2026-10-25',runId:'12345678-1234-4234-8234-123456789012',profiles:{jinsha:{profile:'jinsha-business',port:9232,pid}}};
const proof={receipt,createdAt:2000},page={type:'page',id:'owned',url:'https://data.guoshuyufen.com/#/businessData/realTimeData',marker:ownerMarker(receipt,pid)},other={...page,id:'unowned',marker:''};
let tests=0;
assert.equal(ownedTargetDecision([other,page],[proof],pid,started,3000).id,'owned');tests++;
for(const change of [{ok:false},{stage:'failed'},{cleanupStatus:'pending'},{jinshaTaskStrategy:'created-owned-tab'},{runId:'bad'},{profiles:{jinsha:{profile:'other',port:9232,pid}}},{profiles:{jinsha:{profile:'jinsha-business',port:9233,pid}}},{profiles:{jinsha:{profile:'jinsha-business',port:9232,pid:456}}}]){assert.equal(ownerMarker({...receipt,...change},pid),null);tests++;}
for(const [pages,proofs,p,start] of [[[page,other],[{...proof,createdAt:999}],pid,started],[[page,other],[proof],456,started],[[page,page],[proof],pid,started],[[other],[proof],pid,started],[[page],[proof,proof],pid,started],[[page],[proof],pid,NaN],[[{...page,url:'https://example.org/'}],[proof],pid,started],[[{...page,url:'https://data.guoshuyufen.com/#/login'}],[proof],pid,started]]){assert.throws(()=>ownedTargetDecision(pages,proofs,p,start,3000));tests++;}
assert.equal((await selectExistingJinshaTarget([page],{probe:()=>{throw Error('must-not-probe-single');}})).id,'owned');tests++;
assert.equal((await selectExistingJinshaTarget([other,page],{probe:async p=>p.marker,context:{pid,startedAt:started,proofs:[proof]}})).id,'owned');tests++;
await assertSelectedJinshaTarget({eval:async()=>({url:page.url,marker:page.marker})},{...page,jinshaOwnerMarker:page.marker});tests++;
await assert.rejects(()=>assertSelectedJinshaTarget({eval:async()=>({url:page.url,marker:'changed'})},{...page,jinshaOwnerMarker:page.marker}));tests++;
console.log(JSON.stringify({ok:true,tests,browserActions:0,sendAttempts:0}));
