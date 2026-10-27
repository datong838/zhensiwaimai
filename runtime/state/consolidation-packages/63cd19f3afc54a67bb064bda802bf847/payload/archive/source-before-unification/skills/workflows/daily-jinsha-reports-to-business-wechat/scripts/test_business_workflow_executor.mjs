import assert from 'node:assert/strict';
import {execFile as execFileCb} from 'node:child_process';
import {promisify} from 'node:util';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {
  MAX_DOWNLOAD_ATTEMPTS,MAX_SEND_ATTEMPTS,MAX_VERIFY_ATTEMPTS,SEND_RETRY_WAIT_MS,VERIFY_RETRY_WAIT_MS,EFFICIENCY_BUDGET_MS,NEXT_ACTION,buildWorkflowSummary,completionOutput,validDesktopBatchProof,selfTest,main,
} from './business_workflow_executor.mjs';

const execFile=promisify(execFileCb),scriptDir=path.dirname(fileURLToPath(import.meta.url));
assert.equal(MAX_DOWNLOAD_ATTEMPTS,3);
assert.equal(MAX_SEND_ATTEMPTS,4);
assert.equal(MAX_VERIFY_ATTEMPTS,4);
assert.equal(SEND_RETRY_WAIT_MS,5000);
assert.equal(VERIFY_RETRY_WAIT_MS,3000);
assert.equal(EFFICIENCY_BUDGET_MS,180000);
assert.equal(NEXT_ACTION.prepared,'send');
assert.equal(NEXT_ACTION.complete,null);
// 2026-09-30 W3 收口：回执升级为 windows-readback-file-card 强读回证明（D14 迁移后形状）。
// 每个 item 必须携带 verificationLevel，否则 fail-closed 校验会拒绝（未知级别一律不认）。
const batchItems=[{status:'verified',verificationLevel:'windows-readback-file-card',transport:{sendAttempts:1}},{status:'verified',verificationLevel:'windows-readback-file-card',transport:{sendAttempts:1}}];
assert.equal(validDesktopBatchProof({verified:true,runtimeModelDecisions:0,sendAttempts:2,newSendAttempts:2,commonReceipt:{items:batchItems}}),true);
assert.equal(validDesktopBatchProof({verified:true,runtimeModelDecisions:0,sendAttempts:2,newSendAttempts:1,commonReceipt:{items:batchItems}}),false);
assert.equal(validDesktopBatchProof({verified:true,runtimeModelDecisions:0,sendAttempts:2,newSendAttempts:2,commonReceipt:{items:[batchItems[0],{status:'unknown',transport:{sendAttempts:1}}]}}),false);
const summary=buildWorkflowSummary({policyVersion:'p',runId:'r',businessDate:'2026-09-10',status:'complete',phase:'complete',nextAction:null,runtimeModelDecisions:0,createdAt:1000,completedAt:6100,events:[
  {at:1100,type:'attempt',stage:'download'},{at:2100,type:'decision',stage:'download',decision:'retry-download',reason:'covered'},
  {at:2200,type:'attempt',stage:'download'},{at:3100,type:'transition',to:'downloaded'},
  {at:3200,type:'attempt',stage:'prepare'},{at:4100,type:'transition',to:'prepared'},
  {at:4200,type:'attempt',stage:'send'},{at:5100,type:'transition',to:'sent'},
  {at:5200,type:'attempt',stage:'verify-only'},{at:5900,type:'transition',to:'verified'},
  {at:6000,type:'transition',to:'complete'},
]});
assert.equal(summary.totalElapsedMs,5100);
assert.deepEqual(summary.nodes.map(node=>[node.name,node.attempts,node.elapsedMs,node.complete]),[['download',2,2000,true],['prepare',1,900,true],['send',1,900,true],['verify',1,700,true],['finalize',1,100,true]]);
assert.equal(summary.pitfalls[0].detail,'retry-download');
assert.equal(summary.nextAction,null);
assert.equal(summary.codeEnforced,true);
assert.equal(summary.reviewItems.length,summary.nodes.length);
assert(summary.reviewItems.every(item=>Number.isFinite(item.elapsedMs)&&Array.isArray(item.pitfalls)));
const output=completionOutput({runId:'r',businessDate:'2026-09-10',phase:'complete',status:'complete'},
  {workflowState:'/state',workflowSummary:'/summary',examReceipt:'/exam'},summary);
assert.equal(output.completionReview.codeEnforced,true);
assert.equal(output.completionReview.reviewItems.length,5);
const blockedSummary=buildWorkflowSummary({policyVersion:'p',runId:'r2',businessDate:'2026-09-10',status:'needs-maintenance',phase:'prepared',nextAction:null,runtimeModelDecisions:0,createdAt:0,updatedAt:180001,events:[{at:1,type:'attempt',stage:'send'},{at:180001,type:'blocked',phase:'prepared',reason:'window-obscured'}]});
assert.equal(blockedSummary.nodes[0].complete,false);
assert.deepEqual(blockedSummary.pitfalls.map(item=>item.type),['blocked','efficiency-budget-exceeded']);
const self=await selfTest();
assert.equal(self.ok,true);
assert.equal(self.frozenCoreFiles,18);
assert.equal(self.runtimeModelDecisions,0);
await assert.rejects(()=>main(['--execute','--group','bad']),/usage:/);
const pipeline=path.join(scriptDir,'business_exam_pipeline.mjs');
await assert.rejects(()=>execFile(process.execPath,[pipeline,'/tmp/forged.json','--send']),error=>String(error.stderr).includes('direct-stage-invocation-forbidden'));
const browser=path.join(scriptDir,'business_jinsha_browser_exam.mjs');
await assert.rejects(()=>execFile(process.execPath,[browser,'/tmp/forged.json']),error=>String(error.stderr).includes('direct-stage-invocation-forbidden'));
const python='/Users/ddt/work/projects/ai_agent/.venvs/harmonyos3-phone-control/bin/python';
for(const name of ['business_desktop_wechat_file_sender.py','business_wechat_file_sender.py','business_wecom_shared_space_sender.py','wecom_shared_space.py'])await assert.rejects(()=>execFile(python,[path.join(scriptDir,name)]),error=>String(error.stdout).includes('direct-stage-invocation-forbidden'));
console.log(JSON.stringify({ok:true,tests:29,productionEntry:'business_workflow_executor.mjs',runtimeModelDecisions:0}));
