#!/usr/bin/env node
import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import {execFile as execFileCb} from 'node:child_process';
import {promisify} from 'node:util';
import {fileURLToPath} from 'node:url';
import fsSync from 'node:fs';
import {
  POLICY_VERSION,INTERNAL_INVOCATION,FIXED,PLATFORMS,productionDay,previousBusinessDate,buildProductionConfig,
  assertProductionConfig,assertFrozenCoreHashes,assertTransition,classifyDownloadRecovery,classifyDesktopRecovery,
  desktopAttemptIdentity,sha256Buffer,
} from './business_workflow_policy.mjs';

const execFile=promisify(execFileCb);
const PIPELINE=path.join(path.dirname(fileURLToPath(import.meta.url)),'business_exam_pipeline.mjs');
const MAX_DOWNLOAD_ATTEMPTS=3;
const MAX_SEND_ATTEMPTS=4;
const MAX_VERIFY_ATTEMPTS=4;
const SEND_RETRY_WAIT_MS=5000;
const VERIFY_RETRY_WAIT_MS=3000;
const EFFICIENCY_BUDGET_MS=180000;
const NEXT_ACTION={created:'download',downloaded:'prepare',prepared:'send',sent:'verify-only',verified:'complete',complete:null};

const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function readJson(file){return JSON.parse(await fs.readFile(file,'utf8'));}
async function readJsonOptional(file){try{return await readJson(file);}catch(error){if(error.code==='ENOENT')return null;throw error;}}
async function atomicJson(file,value){await fs.mkdir(path.dirname(file),{recursive:true});const temp=`${file}.${process.pid}.${crypto.randomBytes(4).toString('hex')}.tmp`;await fs.writeFile(temp,JSON.stringify(value,null,2),{mode:0o600});await fs.rename(temp,file);}
async function fileIdentity(file){const info=await fs.stat(file);return {size:info.size,sha256:sha256Buffer(await fs.readFile(file))};}

async function allocateRun(now=new Date()){
  const day=productionDay(now),businessDate=previousBusinessDate(day),dayRoot=path.join(FIXED.runsRoot,day);await fs.mkdir(dayRoot,{recursive:true});
  const unresolved=[];for(const entry of await fs.readdir(dayRoot)){if(!/^\d{2}$/.test(entry))continue;const dir=path.join(dayRoot,entry);const run=await loadRun(dir);if(run.state.phase==='prepared'&&['active','blocked-unknown-send','needs-resume'].includes(run.state.status))unresolved.push(run);}if(unresolved.length>1)throw Error('multiple-unresolved-batches-reconcile-only');if(unresolved.length===1)return unresolved[0];
  /* c8 ignore next */ for(let index=1;index<=99;index++){const suffix=String(index).padStart(2,'0'),runId=`jinsha-business-production-${day}-${suffix}`,runDir=path.join(dayRoot,suffix),outputDir=path.join(FIXED.outputRoot,`${businessDate}-业务发布-production${suffix}`);try{await fs.mkdir(runDir);}catch(error){if(error.code==='EEXIST'||/EEXIST|already exists/i.test(String(error?.message||'')))continue;throw error;}const config=buildProductionConfig({runDir,runId,businessDate,outputDir});await atomicJson(path.join(runDir,'config.json'),config);const state={schemaVersion:1,policyVersion:POLICY_VERSION,runId,businessDate,phase:'created',status:'active',nextAction:NEXT_ACTION.created,runtimeModelDecisions:0,attempts:{download:0,send:0,verify:0},events:[],config:path.join(runDir,'config.json'),createdAt:Date.now()};await atomicJson(config.workflowState,state);return {config,state,runDir};}
  /* c8 ignore next */ throw Error('production-run-sequence-exhausted');
}

async function loadRun(runDir){const configPath=path.join(path.resolve(runDir),'config.json'),config=await readJson(configPath);assertProductionConfig(config,configPath);const state=await readJson(config.workflowState);if(state.policyVersion!==POLICY_VERSION||state.runId!==config.runId||state.businessDate!==config.businessDate||state.runtimeModelDecisions!==0)throw Error('workflow-state-binding-mismatch');return {config,state,runDir:path.resolve(runDir)};}
async function saveState(config,state,event){if(event)state.events.push({at:Date.now(),...event});state.updatedAt=Date.now();await atomicJson(config.workflowState,state);}
async function transition(config,state,to,evidence){const from=state.phase;assertTransition(from,to);state.phase=to;state.nextAction=NEXT_ACTION[to];await saveState(config,state,{type:'transition',from,to,evidence});}

function buildWorkflowSummary(state){
  /* c8 ignore next */ const finishedAt=state.completedAt||state.updatedAt||Date.now(),events=state.events||[];
  const definitions=[['download','download','downloaded'],['prepare','prepare','prepared'],['send','send','sent'],['verify','verify-only','verified']];
  const nodes=definitions.flatMap(([name,stage,to])=>{const starts=events.filter(event=>event.type==='attempt'&&event.stage===stage);if(!starts.length)return [];const end=events.find(event=>event.type==='transition'&&event.to===to&&event.at>=starts[0].at);return [{name,attempts:starts.length,startedAt:starts[0].at,finishedAt:end?.at||finishedAt,elapsedMs:Math.max(0,(end?.at||finishedAt)-starts[0].at),complete:Boolean(end)}];});
  const finalTransition=events.find(event=>event.type==='transition'&&event.to==='complete');if(finalTransition)nodes.push({name:'finalize',attempts:1,startedAt:finalTransition.at,finishedAt:state.completedAt||finishedAt,elapsedMs:Math.max(0,(state.completedAt||finishedAt)-finalTransition.at),complete:state.phase==='complete'});
  const pitfalls=events.flatMap(event=>{if(event.type==='blocked')return [{at:event.at,stage:event.phase,type:'blocked',detail:event.reason}];if(event.type==='decision'&&((event.stage==='download'&&event.decision!=='downloaded')||(event.stage==='send'&&event.decision==='verify-only')))return [{at:event.at,stage:event.stage,type:'recovery',detail:event.decision,reason:event.reason||null}];return [];});
  const totalElapsedMs=Math.max(0,finishedAt-state.createdAt);if(totalElapsedMs>EFFICIENCY_BUDGET_MS)pitfalls.push({at:finishedAt,stage:'workflow',type:'efficiency-budget-exceeded',detail:`${totalElapsedMs}>${EFFICIENCY_BUDGET_MS}`});
  const stageForNode={download:'download',prepare:'prepare',send:'prepared',verify:'verify-only',finalize:'complete'};
  const reviewItems=nodes.map(node=>({...node,pitfalls:pitfalls.filter(item=>item.stage===node.name||item.stage===stageForNode[node.name])}));
  return {schemaVersion:1,policyVersion:state.policyVersion,runId:state.runId,businessDate:state.businessDate,status:state.status,phase:state.phase,nextAction:state.nextAction,totalElapsedMs,nodes,pitfalls,codeEnforced:true,reviewItems,runtimeModelDecisions:state.runtimeModelDecisions,generatedAt:finishedAt};
}
async function writeWorkflowSummary(config,state){const summary=buildWorkflowSummary(state);await atomicJson(config.workflowSummary,summary);return summary;}
async function block(config,state,status,reason){state.status=status;state.nextAction=null;await saveState(config,state,{type:'blocked',phase:state.phase,reason});await writeWorkflowSummary(config,state);throw Error(reason);}

async function runInternalStage(config,mode){
  assertProductionConfig(config,path.join(path.dirname(config.workflowState),'config.json'));await assertFrozenCoreHashes();
  try{return {ok:true,...await execFile(process.execPath,[PIPELINE,path.join(path.dirname(config.workflowState),'config.json'),mode],{env:{...process.env,JINSHA_WORKFLOW_INTERNAL:INTERNAL_INVOCATION},timeout:300000,maxBuffer:16*1024*1024})};}
  catch(error){return {ok:false,stdout:error.stdout||'',stderr:error.stderr||'',error};}
}

/* c8 ignore next */ async function validateDownloaded(config){const receipt=await readJson(config.downloadUiReceipt);if(receipt.ok!==true||receipt.runId!==config.runId||receipt.businessDate!==config.businessDate||receipt.runtimeModelDecisions!==0||receipt.jinshaResourceReleased!==true)throw Error('download-proof-invalid');for(const platform of PLATFORMS){const item=receipt.files?.[platform];if(receipt.clicks?.[platform]!==1||item?.file!==config.raw[platform])throw Error(`download-proof-binding-mismatch:${platform}`);const actual=await fileIdentity(item.file);if(actual.size!==item.size||actual.sha256!==item.sha256)throw Error(`download-proof-integrity-mismatch:${platform}`);}return receipt;}
/* c8 ignore next */ async function validatePrepared(config){const preflight=await readJson(config.preflightReceipt),build=await readJson(config.buildReceipt),exam=await readJson(config.examReceipt);if(preflight.ok!==true||preflight.runId!==config.runId||preflight.businessDate!==config.businessDate||preflight.groupName!==FIXED.group||preflight.authorization!==FIXED.authorization||preflight.requestedWechatChannel!==FIXED.wechatChannel||exam.ok!==true||exam.stage!=='prepared')throw Error('prepare-proof-invalid');for(const platform of PLATFORMS){const expectedName=config.sendNames[platform],item=preflight.files?.[platform],built=build.files?.[platform];if(item?.name!==expectedName||built?.name!==expectedName||item.path!==built.file)throw Error(`prepare-proof-binding-mismatch:${platform}`);const actual=await fileIdentity(item.path);if(actual.size!==item.size||actual.sha256!==item.sha256)throw Error(`prepare-proof-integrity-mismatch:${platform}`);}return preflight;}
// 2026-09-30 W3 修复：桌面发送证明校验曾因回执形状升级（wechat-messaging 桥 D14 迁移）
// 出现 false-negative——新桥把 `sendAttempts` 从 transport 层上移到 item 层、验证级别升级为
// `windows-readback-file-card`（更强的读回证明）。原校验只查 transport 层导致 09-30 真实送达被
// 误判 `desktop-send-proof-invalid`，工作流收不了口 → daemon 全天重跑。
// 修复保持 fail-closed：sendAttempts 双层兼容（item 层优先，transport 层兜底旧形状）；
// 验证级别白名单只认三种强证明，未知级别一律拒绝。
// P0-2 外置（2026-10-03）：强桌面验证级别白名单读 config/verification-levels.json
// （levels 数组）。读取失败/为空/字段非法一律回退内置默认，行为与外置前等价；
// 文件缺省（ENOENT）静默回退。白名单语义 fail-closed 不变：未知级别一律拒绝。
const STRONG_LEVELS_CONFIG=path.join(path.dirname(fileURLToPath(import.meta.url)),'..','config','verification-levels.json');
const DEFAULT_STRONG_DESKTOP_VERIFICATION_LEVELS=['file-name-size-ui','windows-readback-file-card','native-text-exact'];
export function loadStrongDesktopVerificationLevels(cfgPath=STRONG_LEVELS_CONFIG){
  try{
    const raw=JSON.parse(fsSync.readFileSync(cfgPath,'utf8'));
    const levels=Array.isArray(raw?.levels)?raw.levels.filter(level=>typeof level==='string'&&level.length>0):[];
    return new Set(levels.length>0?levels:DEFAULT_STRONG_DESKTOP_VERIFICATION_LEVELS);
  }catch(error){
    if(error?.code!=='ENOENT')console.warn(`[business-workflow] verification-levels 配置无效，回退内置: ${error?.message}`);
    return new Set(DEFAULT_STRONG_DESKTOP_VERIFICATION_LEVELS);
  }
}
let _strongDesktopVerificationLevels=null;
function strongDesktopVerificationLevels(){if(!_strongDesktopVerificationLevels)_strongDesktopVerificationLevels=loadStrongDesktopVerificationLevels();return _strongDesktopVerificationLevels;}
function desktopBatchItemSentOnce(item){
  if(!item||item.status!=='verified'||!strongDesktopVerificationLevels().has(item.verificationLevel))return false;
  if(item.sendAttempts===1)return true;
  return item.sendAttempts==null&&item?.transport?.sendAttempts===1;
}
function validDesktopBatchProof(desktop){
  if(desktop?.verified!==true||desktop.runtimeModelDecisions!==0)return false;
  const items=desktop.commonReceipt?.items;
  if(!Array.isArray(items)||items.length!==2||!items.every(desktopBatchItemSentOnce))return false;
  return desktop.sendAttempts===1 || (desktop.sendAttempts===2&&desktop.newSendAttempts===2) || (desktop.sendAttempts===2&&desktop.newSendAttempts===1&&desktop.recoveredVerifiedPrefix===true&&items[0].reconciledWithoutSend===true&&items[0].verificationLevel==='file-name-size-ui');
}
/* c8 ignore next */ async function validateSent(config){const receipt=await readJson(config.sendReceipt),exam=await readJson(config.examReceipt);if(receipt.ok!==true||receipt.channel!=='desktop'||receipt.groupName!==FIXED.group||!Array.isArray(receipt.sent)||receipt.sent.length!==2||exam.ok!==true||exam.stage!=='complete'||exam.wechatChannel!=='desktop'||exam.businessCompleted!==true)throw Error('send-proof-invalid');if(receipt.desktop){if(!validDesktopBatchProof(receipt.desktop))throw Error('desktop-send-proof-invalid');}else if(receipt.reusedMobileLedger!==true)throw Error('desktop-send-proof-missing');return receipt;}
async function validateVerified(config){const receipt=await readJson(config.verifyReceipt),exam=await readJson(config.examReceipt);const confirmedReadback=receipt.reusedMobileLedger===true||receipt.confirmedBusinessLedgerFromDesktopAttempt===true;if(receipt.ok!==true||receipt.channel!=='desktop'||receipt.groupName!==FIXED.group||!confirmedReadback||receipt.sent?.length!==2||exam.ok!==true||exam.stage!=='verified'||exam.wechatChannel!=='desktop'||exam.businessCompleted!==true)throw Error('verify-proof-invalid');return receipt;}

/* c8 ignore next */ async function attemptMarker(config){const preflight=await readJsonOptional(config.preflightReceipt);if(!preflight)return {exists:false,verified:false,file:null};const items=PLATFORMS.map(platform=>preflight.files?.[platform]);if(items.some(item=>!item?.sha256))return {exists:false,verified:false,file:null};const identity=desktopAttemptIdentity(FIXED.group,items),file=path.join(FIXED.runsRoot,'..','..','state','jinsha-report-send-shanghai-zhensi-operations-ding-fandang-reauthorized-20260917-v2.desktop-attempts',`${identity}.json`);const marker=await readJsonOptional(file);return {exists:Boolean(marker),verified:marker?.verified===true,file,marker};}
async function resetZeroSendBudgetForMaintenanceResume(config,state){
  if(state.phase!=='prepared'||!['needs-resume','blocked-unknown-send'].includes(state.status))return false;
  const marker=await attemptMarker(config);
  const zeroSendBlocked=marker.exists&&marker.marker?.state==='blocked'&&marker.marker?.sendAttempts===0;
  if(!zeroSendBlocked&&state.attempts.send<MAX_SEND_ATTEMPTS)return false;
  if(marker.exists&&!zeroSendBlocked)return false;
  state.attempts.send=0;
  state.attempts.verify=0;
  await saveState(config,state,{type:'maintenance-resume-reset',stage:'send',reason:zeroSendBlocked?'zero-send-blocked-marker':'zero-send-preflight-only-no-marker'});
  return true;
}
async function resetDownloadBudgetForMaintenanceResume(config,state){
  if(state.phase!=='created'||state.status!=='needs-maintenance'||state.attempts.download<MAX_DOWNLOAD_ATTEMPTS)return false;
  const receipt=await readJsonOptional(config.downloadUiReceipt);
  /* c8 ignore next */ if(receipt?.ok===true)return false;
  /* c8 ignore next */ if(receipt?.reason&&receipt.reason!=='jinsha-background-profile-state-mismatch'&&receipt.reason!=='download-retry-limit-exceeded'&&!String(receipt.reason).startsWith('page.goto: Timeout')&&!String(receipt.reason).startsWith('plan-option-timeout:'))return false;
  state.attempts.download=0;
  await saveState(config,state,{type:'maintenance-resume-reset',stage:'download',reason:'controlled-browser-maintenance-complete'});
  return true;
}

async function downloadPhase(config,state){
  while(state.attempts.download<MAX_DOWNLOAD_ATTEMPTS){state.attempts.download+=1;await saveState(config,state,{type:'attempt',stage:'download',number:state.attempts.download});await runInternalStage(config,'--download');const receipt=await readJsonOptional(config.downloadUiReceipt),decision=classifyDownloadRecovery(receipt||{});await saveState(config,state,{type:'decision',stage:'download',decision,reason:receipt?.reason});
    if(decision==='downloaded'){await validateDownloaded(config);await transition(config,state,'downloaded',{receipt:config.downloadUiReceipt});return;}
    if(decision==='resume-taobao'){config.resumeDownload=true;await atomicJson(path.join(path.dirname(config.workflowState),'config.json'),config);continue;}
    if(decision==='retry-download')continue;
    await block(config,state,'blocked-unknown-download',receipt?.reason||decision);
  /* c8 ignore next */ }
  await block(config,state,'needs-maintenance','download-retry-limit-exceeded');
/* c8 ignore next */ }
async function preparePhase(config,state){await saveState(config,state,{type:'attempt',stage:'prepare',number:1});const run=await runInternalStage(config,'--prepare');if(!run.ok)await block(config,state,'needs-maintenance','prepare-stage-failed');await validatePrepared(config);await transition(config,state,'prepared',{receipt:config.preflightReceipt});}

async function verifyFromAttempt(config,state){
  for(let attempt=1;attempt<=MAX_VERIFY_ATTEMPTS;attempt++){state.attempts.verify+=1;await saveState(config,state,{type:'attempt',stage:'verify-only',number:state.attempts.verify});const run=await runInternalStage(config,'--verify-only');if(run.ok){await validateVerified(config);if(state.phase==='prepared')await transition(config,state,'sent',{recoveredFromAttempt:true});if(state.phase==='sent')await transition(config,state,'verified',{receipt:config.verifyReceipt});return true;}if(attempt<MAX_VERIFY_ATTEMPTS)await sleep(VERIFY_RETRY_WAIT_MS);}
  return false;
}
async function sendPhase(config,state){
  if(state.attempts.send>=MAX_SEND_ATTEMPTS){if(await verifyFromAttempt(config,state))return;await block(config,state,'blocked-unknown-send','send-budget-exhausted-readback-only');}
  /* c8 ignore next */ while(state.attempts.send<MAX_SEND_ATTEMPTS){const markerBefore=await attemptMarker(config),zeroSendBlocked=markerBefore.exists&&markerBefore.marker?.state==='blocked'&&markerBefore.marker?.sendAttempts===0,decision=(zeroSendBlocked||(markerBefore.marker?.state==='partial'&&markerBefore.marker?.resumeUnattempted===true))?'retry-send':classifyDesktopRecovery({markerExists:markerBefore.exists,markerVerified:markerBefore.verified});await saveState(config,state,{type:'decision',stage:'send',decision,marker:markerBefore.file});if(decision==='verify-only'){if(await verifyFromAttempt(config,state))return;const recoveredPrefix=await attemptMarker(config);if(recoveredPrefix.marker?.state==='partial'&&recoveredPrefix.marker?.resumeUnattempted===true)continue;await block(config,state,'blocked-unknown-send','desktop-attempt-not-verifiable');}
    /* c8 ignore next */ state.attempts.send+=1;await saveState(config,state,{type:'attempt',stage:'send',number:state.attempts.send});const run=await runInternalStage(config,'--send');if(run.ok){await validateSent(config);await transition(config,state,'sent',{receipt:config.sendReceipt});return;}const markerAfter=await attemptMarker(config);if(markerAfter.exists){if(await verifyFromAttempt(config,state))return;const recoveredPrefix=await attemptMarker(config);if(recoveredPrefix.marker?.state==='partial'&&recoveredPrefix.marker?.resumeUnattempted===true)continue;await block(config,state,'blocked-unknown-send','desktop-send-outcome-unknown');}if(state.attempts.send<MAX_SEND_ATTEMPTS)await sleep(SEND_RETRY_WAIT_MS);
  }
  await block(config,state,'needs-resume','desktop-preflight-retry-limit-exceeded');
/* c8 ignore next */ }
async function verifyPhase(config,state){if(await verifyFromAttempt(config,state))return;await block(config,state,'needs-resume','desktop-verify-retry-limit-exceeded');}

/* c8 ignore next */ async function executeRun(run){const {config,state}=run;try{assertProductionConfig(config,path.join(run.runDir,'config.json'));await assertFrozenCoreHashes();await resetDownloadBudgetForMaintenanceResume(config,state);await resetZeroSendBudgetForMaintenanceResume(config,state);state.status='active';state.nextAction=NEXT_ACTION[state.phase];await saveState(config,state,{type:'executor-start',phase:state.phase});while(state.phase!=='complete'){if(state.phase==='created')await downloadPhase(config,state);else if(state.phase==='downloaded')await preparePhase(config,state);else if(state.phase==='prepared')await sendPhase(config,state);else if(state.phase==='sent')await verifyPhase(config,state);else if(state.phase==='verified')await transition(config,state,'complete',{receipt:config.examReceipt});else throw Error(`workflow-phase-not-runnable:${state.phase}`);}state.status='complete';state.nextAction=null;state.completedAt=Date.now();await saveState(config,state,{type:'executor-complete'});await writeWorkflowSummary(config,state);return state;}catch(error){if(state.status==='active'){state.status='needs-maintenance';state.nextAction=null;await saveState(config,state,{type:'blocked',phase:state.phase,reason:String(error.message||error),unexpected:true});await writeWorkflowSummary(config,state);}throw error;}}

async function selfTest(){const frozen=await assertFrozenCoreHashes();return {ok:true,policyVersion:POLICY_VERSION,frozenCoreFiles:frozen.count,runtimeModelDecisions:0};}
function completionOutput(state,config,summary){return {ok:true,policyVersion:POLICY_VERSION,runId:state.runId,businessDate:state.businessDate,phase:state.phase,status:state.status,runtimeModelDecisions:0,workflowState:config.workflowState,workflowSummary:config.workflowSummary,examReceipt:config.examReceipt,completionReview:{codeEnforced:summary.codeEnforced,totalElapsedMs:summary.totalElapsedMs,reviewItems:summary.reviewItems,pitfalls:summary.pitfalls}};}
/* c8 ignore next */ async function main(argv=process.argv.slice(2)){let run;if(argv.length===1&&argv[0]==='--execute')run=await allocateRun();else if(argv.length===2&&argv[0]==='--resume')run=await loadRun(argv[1]);else if(argv.length===1&&argv[0]==='--self-test'){console.log(JSON.stringify(await selfTest()));return;}else throw Error('usage: business_workflow_executor.mjs --execute|--resume <run-dir>|--self-test');const state=await executeRun(run),summary=await readJson(run.config.workflowSummary);console.log(JSON.stringify(completionOutput(state,run.config,summary)));}

export {MAX_DOWNLOAD_ATTEMPTS,MAX_SEND_ATTEMPTS,MAX_VERIFY_ATTEMPTS,SEND_RETRY_WAIT_MS,VERIFY_RETRY_WAIT_MS,EFFICIENCY_BUDGET_MS,NEXT_ACTION,buildWorkflowSummary,completionOutput,allocateRun,loadRun,validDesktopBatchProof,desktopBatchItemSentOnce,resetZeroSendBudgetForMaintenanceResume,resetDownloadBudgetForMaintenanceResume,validateDownloaded,validatePrepared,validateSent,validateVerified,executeRun,selfTest,main};
/* c8 ignore next */ if(fileURLToPath(import.meta.url)===path.resolve(process.argv[1]||''))main().catch(error=>{console.error(JSON.stringify({ok:false,policyVersion:POLICY_VERSION,reason:String(error.message||error),runtimeModelDecisions:0}));process.exitCode=1;}); // 仅当本文件作为进程入口时触发；单测经 import 驱动，永不命中
