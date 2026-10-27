import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import crypto from 'node:crypto';
import {validateDatedAcceptance,assertNewDatedRunAbsent} from './dated_acceptance_evidence.mjs';
import {unsealedAcceptanceRecord,MAINTENANCE_AUTHORIZATION} from './maintenance_executor.mjs';
const fixtureBytes=await fs.readFile(new URL('./fixtures/dated-acceptance-20261025.json',import.meta.url));
const fixture=JSON.parse(fixtureBytes),now=new Date('2026-10-27T02:00:00+08:00');
const check=value=>validateDatedAcceptance(value,'2026-10-25','2026-10-26',now);
const evidence=check(fixture);
const candidate=unsealedAcceptanceRecord({authorization:MAINTENANCE_AUTHORIZATION,policy:{allowedBusinessDate:'2026-10-25',carryForward:evidence},candidateDependencyDigest:'a'.repeat(64),allowedBusinessDate:'2026-10-26',now,publicHash:'b'.repeat(64),publicInspect:{candidateFileCount:32},tests:{tests:8}});
assert.equal(candidate.status,'UNSEALED_ACCEPTANCE');assert.equal(candidate.allowedBusinessDate,'2026-10-26');assert.equal(candidate.maintenance.sendAttempts,0);assert.equal(candidate.maintenance.carryForward.technicalStatusPreserved,'unknown');
assert.equal(evidence.allowedBusinessDate,'2026-10-26');assert.equal(evidence.technicalStatusPreserved,'unknown');assert.equal(evidence.newSendAttempts,0);
let cases=0;
function rejects(change){const bundle=structuredClone(fixture);change(bundle);assert.throws(()=>check(bundle),/dated-acceptance/);cases++;}
for(const change of [
 b=>b.confirmation.businessAccepted=false,
 b=>b.confirmation.userQuotes=[],
 b=>b.confirmation.date='2026-10-27',
 b=>b.confirmation.items.push({...b.confirmation.items[0]}),
 b=>b.confirmation.items[0].groupName='其它群',
 b=>b.confirmation.items[0].eventId='wrong',
 b=>b.confirmation.items[0].sendAttempts=2,
 b=>b.config.businessDate='2026-10-24',
 b=>b.state.status='unknown',
 b=>b.fileReceipt.state='unknown',
 b=>b.identities.file.sha256='f'.repeat(64),
 b=>b.identities.image.sha256='f'.repeat(64),
 b=>b.identities.frozen.size++,
 b=>b.imageReceipt.sendAttempts=2,
 b=>b.imageMarker.state='verified',
])rejects(change);
for(const name of ['task.json','response.json','send-intent.json'])rejects(b=>b.originals[name]+=' ');
// Change the parsed semantics and refresh the inventory hash: bindings still reject it.
for(const [name,mutate] of [
 ['task.json',t=>t.request.context.eventId='wrong'],
 ['task.json',t=>t.request.groupName='其它群'],
 ['task.json',t=>t.item.sha256='f'.repeat(64)],
 ['response.json',r=>r.result.sendAttempts=2],
 ['response.json',r=>r.result.status='verified'],
 ['send-intent.json',i=>i.at=now.getTime()/1000],
])rejects(b=>{const v=JSON.parse(b.originals[name]);mutate(v);b.originals[name]=JSON.stringify(v);b.confirmation.items[0].sources[name]=crypto.createHash('sha256').update(b.originals[name]).digest('hex');});
assert.throws(()=>validateDatedAcceptance(fixture,'2026-10-24','2026-10-26',now),/date-scope/);
assert.throws(()=>validateDatedAcceptance(fixture,'2026-10-25','2026-10-27',now),/date-scope/);
const root=await fs.mkdtemp(path.join(os.tmpdir(),'negative-dated-'));
try{
 await assertNewDatedRunAbsent(root,'2026-10-26');
 for(const rel of ['.local/runs/daily-negative-reviews/20261026/workflow-state.json','outputs/yesterday-negative-20261026/report.xlsx','.local/state/negative-review-send-shanghai-zhensi-operations-ding-fandang-v1.desktop-attempts/negative-review-2026-10-26.json','.local/state/negative-review-summary-send-shanghai-zhensi-operations-ding-fandang-v1.desktop-attempts/negative-review-summary-2026-10-26.json']){
  const file=path.join(root,rel);await fs.mkdir(path.dirname(file),{recursive:true});await fs.writeFile(file,JSON.stringify({state:'unknown',sendAttempts:1}));
  await assert.rejects(assertNewDatedRunAbsent(root,'2026-10-26'),/new-run-has-effect/);cases++;
  await fs.rm(path.join(root,rel.startsWith('outputs')?'outputs':'.local'),{recursive:true,force:true});
 }
 const queue=path.join(root,'skills/wechat-messaging/.runtime/ui-post-queue/example');await fs.mkdir(queue,{recursive:true});
 for(const prefix of ['negative-review','negative-review-summary']){
  await fs.writeFile(path.join(queue,'task.json'),JSON.stringify({request:{context:{eventId:path.join(root,`.local/state/${prefix}-send-shanghai-zhensi-operations-ding-fandang-v1.desktop-attempts/${prefix}-2026-10-26.json`)}}}));
  await assert.rejects(assertNewDatedRunAbsent(root,'2026-10-26'),/new-event-queue-exists/);cases++;
 }
}finally{await fs.rm(root,{recursive:true,force:true});}
assert.deepEqual(await fs.readFile(new URL('./fixtures/dated-acceptance-20261025.json',import.meta.url)),fixtureBytes);
assert.equal(fixture.imageReceipt.state,'unknown');assert.equal(fixture.state.phase,'sent');
console.log(JSON.stringify({ok:true,negativeCases:cases+2,sendAttempts:0,oldBytesUnchanged:true}));

// New days are isolated from old unknowns, without claiming old delivery.
const {inspectIndependentBusinessDay,inspectCurrentAcceptedSubmission}=await import('./dated_acceptance_evidence.mjs');
const independentRoot=await fs.mkdtemp(path.join(os.tmpdir(),'negative-independent-day-'));
try{
 const tomorrow=new Date('2026-10-28T08:00:00+08:00');
 const inspect=()=>inspectIndependentBusinessDay(independentRoot,'2026-10-26','2026-10-27',tomorrow);
 const result=await inspect();assert.equal(result.oldDeliveryAccepted,false);assert.equal(result.oldRecordsModified,false);assert.equal(result.newSendAttempts,0);
 for(const [prior,current] of [['2026-10-27','2026-10-27'],['2026-10-26','2026-10-28'],['2026-10-26','2026-10-25'],['2026-02-30','2026-10-27']])await assert.rejects(inspectIndependentBusinessDay(independentRoot,prior,current,tomorrow));
 const monthEnd=await inspectIndependentBusinessDay(independentRoot,'2026-10-30','2026-10-31',new Date('2026-11-01T08:00:00+08:00'));assert.equal(monthEnd.runDay,'2026-11-01');
 for(const target of result.checkedAbsentPaths){await fs.mkdir(path.dirname(target),{recursive:true});await fs.writeFile(target,'old evidence must not be overwritten');await assert.rejects(inspect(),/new-run-has-effect/);await fs.unlink(target);}
 const queue=path.join(independentRoot,'skills/wechat-messaging/.runtime/ui-post-queue/new-task');await fs.mkdir(queue,{recursive:true});
 await fs.writeFile(path.join(queue,'task.json'),JSON.stringify({request:{context:{eventId:result.checkedAbsentPaths[2]}}}));await assert.rejects(inspect(),/new-event-queue-exists/);
 await assert.rejects(inspectCurrentAcceptedSubmission({runDir:path.join(independentRoot,'run'),runDay:'2026-10-28',businessDate:'2026-10-27'},'wrong'),/current-acceptance-scope/);
}finally{await fs.rm(independentRoot,{recursive:true,force:true});}
console.log(JSON.stringify({ok:true,independentBusinessDayScenarios:12,productionActions:0}));
