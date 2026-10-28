import {inspectDatedAcceptance,inspectIndependentBusinessDay,inspectCurrentAcceptedSubmission} from './dated_acceptance_evidence.mjs';
import {readUiDeliveryEvidence} from './ui_delivery_evidence.mjs';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {FIXED, SKILL_DIR, PROJECT_ROOT, assertConfig, buildConfig, previousBusinessDate, shanghaiDay} from './workflow_policy.mjs';

const SCRIPT_DIR=path.dirname(fileURLToPath(import.meta.url));
const MANIFEST=path.join(SKILL_DIR,'dependencies.json');
const POLICY=path.join(SKILL_DIR,'runtime-policy.json');
const PUBLIC_MANIFEST='/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/skills/wechat-messaging/dependencies.json';
const PUBLIC_BRIDGE='/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/skills/wechat-messaging/scripts/workflow_bridge_windows.py';
// 2026-09-30 D14：REGISTRY 台账路径迁移改动了桌面桥字节；本清单同样绑定它，
// 处理方式与 PUBLIC_MANIFEST/PUBLIC_BRIDGE 相同——本地不做字节检查（权威封印在
// wechat-messaging 侧），重绑时按公共清单的钉死值重算。
const PUBLIC_DESKTOP_BRIDGE='/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/skills/wechat-messaging/scripts/workflow_bridge.py';
const MAINTENANCE_AUTHORIZATION='user-20260920-negative-review-dependency-maintenance';
const SELF_KEY='scripts/maintenance_executor.mjs';
const CODE_REPAIRABLE_FILES=new Set(['scripts/fixtures/dated-acceptance-20261025.json','scripts/dated_acceptance_evidence.mjs','scripts/test_dated_acceptance_evidence.mjs','scripts/ui_delivery_evidence.mjs','scripts/test_ui_delivery_evidence.mjs','scripts/workflow_executor.mjs','scripts/workflow_policy.mjs','scripts/browser_collect.mjs','scripts/build_report.mjs','scripts/test_workflow_policy.mjs','scripts/test_browser_policy.mjs','scripts/test_build_report.mjs','scripts/test_maintenance_executor.mjs',SELF_KEY]);
const TESTS=['test_dated_acceptance_evidence.mjs','test_ui_delivery_evidence.mjs','test_workflow_policy.mjs','test_browser_policy.mjs','test_build_report.mjs','test_reconcile.py','test_maintenance_executor.mjs'];

function sha256(bytes){return crypto.createHash('sha256').update(bytes).digest('hex');}
async function readJson(file){return JSON.parse(await fs.readFile(file,'utf8'));}
async function atomicJson(file,value){const temp=`${file}.${process.pid}.tmp`;await fs.writeFile(temp,`${JSON.stringify(value,null,2)}\n`,{mode:0o600});await fs.rename(temp,file);}
async function run(command,args,cwd=SKILL_DIR){return await new Promise(resolve=>{const child=spawn(command,args,{cwd,stdio:['ignore','pipe','pipe']});let stdout='',stderr='';child.stdout.on('data',chunk=>stdout+=chunk);child.stderr.on('data',chunk=>stderr+=chunk);child.once('error',error=>resolve({ok:false,reason:String(error)}));child.once('close',code=>resolve({ok:code===0,code,stdout,stderr,reason:code===0?null:(stderr||stdout).trim()}));});}
function nextDailyBusinessDate(now=new Date()){
  const day=shanghaiDay(now);const parts=new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Shanghai',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(now);const hour=Number(parts.find(part=>part.type==='hour')?.value),minute=Number(parts.find(part=>part.type==='minute')?.value);
  if(hour<9||(hour===9&&minute===0))return previousBusinessDate(day);
  const tomorrow=shanghaiDay(new Date(new Date(`${day}T12:00:00+08:00`).getTime()+86400000));return previousBusinessDate(tomorrow);
}
async function publicManifestClean(){const result=await run(FIXED.wechatPython,[path.join(path.dirname(PUBLIC_MANIFEST),'scripts','dependency_maintenance.py'),'inspect'],path.dirname(PUBLIC_MANIFEST));const parsed=JSON.parse(result.stdout.trim()||'{}');if(!result.ok||parsed.ok!==true||parsed.status!=='clean'||parsed.sendAttempts!==0||parsed.runtimeModelDecisions!==0)throw Error(`public-dependency-inspect-failed:${parsed.reason||result.reason||'invalid'}`);const manifest=await readJson(PUBLIC_MANIFEST);return {...parsed,manifest};}
function acceptanceBusinessDate(now,acceptedBusinessDate){const current=buildConfig(now).businessDate;return current>acceptedBusinessDate?current:nextDailyBusinessDate(now);}
async function absent(file){try{await fs.access(file);return false;}catch(error){if(error.code==='ENOENT')return true;throw error;}}
async function currentRunIsAbsentPreEffect(config){for(const file of [config.config,config.state,config.browserReceipt,config.raw,config.report,config.sendReceipt,path.join(FIXED.sendLedger,config.sendMarker)])if(!await absent(file))throw Error('current-business-run-has-effect-artifact');return true;}
function assertAllocatedStatePreEffect(state){
  const allowed=new Set(['policyVersion','businessDate','phase','status','startedAt','updatedAt','reviewItems','runtimeModelDecisions','lastRecovery']);
  if(Object.keys(state||{}).some(key=>!allowed.has(key)))throw Error('current-business-run-not-allocated-pre-effect');
  if(state?.lastRecovery!==undefined){const value=state.lastRecovery;if(!value||Object.keys(value).sort().join(',')!=='allowed,nextAttempt,priorFailures,stage'||value.allowed!==true||value.stage!=='browser_collect'||value.priorFailures!==0||value.nextAttempt!==1)throw Error('current-business-run-not-allocated-pre-effect');}
  if(state?.phase!=='created'||!['active','recoverable'].includes(state?.status)||!Array.isArray(state?.reviewItems)||state.reviewItems.length!==0||state.attempted||state.unknown||state.sendAttempts!=null||state.reason||state.recoveryReason||state.recovery)throw Error('current-business-run-not-allocated-pre-effect');
  return true;
}
async function currentRunIsAllocatedPreEffect(config){
  assertConfig(config);
  const stored=await readJson(config.config);assertConfig(stored);
  if(JSON.stringify(stored)!==JSON.stringify(config))throw Error('allocated-config-identity-mismatch');
  assertAllocatedStatePreEffect(await readJson(config.state));
  const effects=[config.browserReceipt,config.raw,config.uiStatus,config.finalData,config.analysis,config.report,config.reportValidation,config.sendOutput,config.screenshot,config.screenshotReceipt,config.screenshotSendOutput,config.summary,path.join(FIXED.sendLedger,config.sendMarker),path.join(FIXED.summaryLedger,config.screenshotSendMarker)];
  for(const file of effects)if(!await absent(file))throw Error('current-business-run-has-effect-artifact');
  // Unknown files also mean this is no longer an allocation-only directory.
  const names=await fs.readdir(config.runDir);
  if(names.some(name=>![path.basename(config.config),path.basename(config.state)].includes(name)))throw Error('allocated-run-has-unknown-artifact');
  return true;
}
async function currentRunIsPreEffect(config){if(await absent(config.browserReceipt))return currentRunIsAllocatedPreEffect(config);const state=await readJson(config.state),browser=await readJson(config.browserReceipt);if(state.phase!=='created'||state.status!=='recoverable'||browser.downloadClicks!==0)throw Error('current-business-run-not-pre-effect');for(const file of [config.raw,config.report,config.sendReceipt,path.join(FIXED.sendLedger,config.sendMarker)])if(!await absent(file))throw Error('current-business-run-has-effect-artifact');return true;}
async function currentRunHasReusableDownload(config){const state=await readJson(config.state),browser=await readJson(config.browserReceipt);if(!['created','downloaded'].includes(state.phase)||state.status!=='recoverable'||browser.downloadClicks!==1)throw Error('current-business-run-not-reusable-download');const info=await fs.stat(config.raw),actual=sha256(await fs.readFile(config.raw));if(browser.download){if(path.resolve(browser.download.path)!==path.resolve(config.raw)||browser.download.size!==info.size||browser.download.sha256!==actual)throw Error('current-business-run-download-identity-mismatch');}else{const completed=(state.reviewItems||[]).filter(item=>item.stage==='download'&&item.status==='completed');if(state.phase!=='downloaded'||completed.length!==1||info.size<=0)throw Error('current-business-run-download-receipt-loss-invalid');const archive=await run('/usr/bin/unzip',['-t',config.raw]);if(!archive.ok)throw Error('current-business-run-download-receipt-loss-invalid');}for(const file of [config.report,config.sendReceipt,path.join(FIXED.sendLedger,config.sendMarker)])if(!await absent(file))throw Error('current-business-run-has-effect-artifact');return true;}
function isZeroSendWechatPreflightBlocked(state,marker){return state?.phase==='report_built'&&state?.status==='recoverable'&&marker?.state==='blocked'&&marker?.verified===false&&marker?.sendAttempts===0&&marker?.reason==='exact-group-result-count:0';}
async function currentRunIsZeroSendWechatPreflightBlocked(config){const state=await readJson(config.state),marker=await readJson(path.join(FIXED.sendLedger,config.sendMarker));if(!isZeroSendWechatPreflightBlocked(state,marker))throw Error('current-business-run-not-zero-send-wechat-preflight');return true;}
function isZeroSendWechatRuntimeBlocked(state,receipt){return state?.phase==='report_built'&&state?.status==='recoverable'&&receipt?.state==='blocked'&&receipt?.verified===false&&receipt?.sendAttempts===0&&receipt?.newSendAttempts===0&&receipt?.attempted!==true&&receipt?.unknown!==true&&receipt?.reason==="No module named 'AppKit'";}
async function currentRunIsZeroSendWechatRuntimeBlocked(config){const state=await readJson(config.state),receipt=await readJson(config.sendReceipt);if(!isZeroSendWechatRuntimeBlocked(state,receipt))throw Error('current-business-run-not-zero-send-wechat-runtime');return true;}
// 2026-09-30：Windows 驱动业务拒绝（服务端已应答、什么都没发出）也属已证明零发送。
// 判定项与上方运行时阻断逐项同强度，仅多要求 reason 以 'windows-send-rejected:' 开头。
function isZeroSendWechatDriverBlocked(state,receipt){return state?.phase==='report_built'&&state?.status==='recoverable'&&receipt?.state==='blocked'&&receipt?.verified===false&&receipt?.sendAttempts===0&&receipt?.newSendAttempts===0&&receipt?.attempted!==true&&receipt?.unknown!==true&&typeof receipt?.reason==='string'&&receipt.reason.startsWith('windows-send-rejected:');}
async function currentRunIsZeroSendWechatDriverBlocked(config){const state=await readJson(config.state),receipt=await readJson(config.sendReceipt);if(!isZeroSendWechatDriverBlocked(state,receipt))throw Error('current-business-run-not-zero-send-wechat-driver-rejected');return true;}
async function currentRunIsComplete(config){const state=await readJson(config.state);if(state.phase!=='complete'||state.status!=='complete')throw Error('current-business-run-not-complete');return true;}
async function acceptedRunIsComplete(policy){const config=buildConfig(new Date(new Date(`${policy.acceptedBusinessDate}T12:00:00+08:00`).getTime()+86400000));if(config.businessDate!==policy.acceptedBusinessDate||path.resolve(policy.acceptedSummary)!==path.resolve(config.summary))throw Error('accepted-run-path-mismatch');await currentRunIsComplete(config);const summary=await readJson(config.summary);if(summary.ok!==true||summary.businessDate!==policy.acceptedBusinessDate||summary.completionReview?.codeEnforced!==true||summary.send?.verified!==true||summary.report?.sha256!==policy.acceptedReportSha256)throw Error('accepted-run-proof-invalid');return true;}
async function assertLocalIntegrity(manifest,{allowCodeRepair=false}={}){for(const [file,expected] of Object.entries(manifest.files||{})){if([PUBLIC_MANIFEST,PUBLIC_BRIDGE,PUBLIC_DESKTOP_BRIDGE].includes(file))continue;const resolved=path.isAbsolute(file)?file:path.join(SKILL_DIR,file);const actual=sha256(await fs.readFile(resolved));if(actual!==expected&&(!allowCodeRepair||!CODE_REPAIRABLE_FILES.has(file)))throw Error(`local-dependency-hash-mismatch:${file}`);}return sha256(await fs.readFile(path.join(SKILL_DIR,SELF_KEY)));}
async function runOfflineTests(){for(const test of TESTS){const isPython=test.endsWith('.py');const result=await run(isPython?FIXED.analysisPython:FIXED.node,[path.join(SCRIPT_DIR,test)]);if(!result.ok)throw Error(`offline-test-failed:${test}:${result.reason}`);}const selfTest=await run(FIXED.node,[path.join(SCRIPT_DIR,'workflow_executor.mjs'),'--self-test']);const parsed=JSON.parse(selfTest.stdout.trim()||'{}');if(!selfTest.ok||parsed.ok!==true||parsed.runtimeModelDecisions!==0)throw Error(`workflow-self-test-failed:${parsed.reason||selfTest.reason||'invalid'}`);return {tests:TESTS.length+1};}
function unsealedAcceptanceRecord({authorization,policy,candidateDependencyDigest,allowedBusinessDate,now,publicHash,publicInspect,tests}){
  if(policy.carryForward){assert.equal(policy.carryForward.allowedBusinessDate,allowedBusinessDate);assert.equal(policy.carryForward.previousAllowedBusinessDate,policy.allowedBusinessDate);assert.equal(policy.carryForward.newSendAttempts,0);}
  return {schemaVersion:1,status:'UNSEALED_ACCEPTANCE',authorizationRef:FIXED.authorization,candidateDependencyDigest,allowedBusinessDate,preparedAt:new Date(now).toISOString(),maintenance:{authorization,...(policy.carryForward?{carryForward:policy.carryForward}:{}),publicManifestSha256:publicHash,publicInspect:{candidateFileCount:publicInspect.candidateFileCount,sendAttempts:0,runtimeModelDecisions:0},tests,sendAttempts:0,runtimeModelDecisions:0}};
}
async function prepareUnsealedAcceptance(authorization,{now=new Date()}={}){
  const started=Date.now();const review=[];const stage=async(label,fn)=>{const tick=Date.now();try{const value=await fn();review.push({label,status:'completed',elapsedMs:Date.now()-tick,pitfalls:[]});return value;}catch(error){review.push({label,status:'failed',elapsedMs:Date.now()-tick,pitfalls:[String(error.message||error)]});throw error;}};
  if(authorization!==MAINTENANCE_AUTHORIZATION)throw Error('maintenance-authorization-mismatch');
  const originalManifest=await fs.readFile(MANIFEST),originalPolicy=await fs.readFile(POLICY);let manifestWritten=false;
  try{
    const policy=await stage('核验封板或可重绑定验收态',async()=>{const value=await readJson(POLICY),current=buildConfig(now);if(value.authorizationRef!==FIXED.authorization)throw Error('release-authorization-mismatch');if(value.status==='SEALED'){if(!value.dependencyDigest||!value.acceptedSummary)throw Error('sealed-policy-invalid');await acceptedRunIsComplete(value);if(current.businessDate===value.acceptedBusinessDate)await currentRunIsComplete(current);else if(!await absent(current.state))throw Error('new-business-run-already-started');return {...value,rebind:false,codeRepair:true,keepAllowed:false};}if(value.status==='UNSEALED_ACCEPTANCE'&&value.allowedBusinessDate<current.businessDate){const carryForward=await inspectIndependentBusinessDay(PROJECT_ROOT,value.allowedBusinessDate,current.businessDate,now);return {...value,rebind:true,codeRepair:true,keepAllowed:false,carryForward};}if(value.status==='UNSEALED_ACCEPTANCE'&&value.allowedBusinessDate>current.businessDate){if(await absent(current.state))return {...value,rebind:true,codeRepair:false,keepAllowed:false};await currentRunIsComplete(current);return {...value,rebind:false,codeRepair:true,keepAllowed:true};}if(value.status==='UNSEALED_ACCEPTANCE'&&value.allowedBusinessDate===current.businessDate){if(await absent(current.state)){await currentRunIsAbsentPreEffect(current);return {...value,rebind:false,codeRepair:true,keepAllowed:false};}try{await currentRunIsPreEffect(current);return {...value,rebind:false,codeRepair:true,keepAllowed:false};}catch{try{await currentRunHasReusableDownload(current);return {...value,rebind:false,codeRepair:true,keepAllowed:false};}catch{try{await currentRunIsZeroSendWechatPreflightBlocked(current);return {...value,rebind:false,codeRepair:true,keepAllowed:false};}catch{try{await currentRunIsZeroSendWechatRuntimeBlocked(current);return {...value,rebind:false,codeRepair:true,keepAllowed:false};}catch{try{await currentRunIsZeroSendWechatDriverBlocked(current);}catch{const state=await readJson(current.state);if(!['report_built','sent'].includes(state.phase)||state.status!=='recoverable')throw Error('current-business-run-no-bound-ui-delivery');if(!await readUiDeliveryEvidence(current,FIXED.group))await inspectCurrentAcceptedSubmission(current,FIXED.group,now);}return {...value,rebind:false,codeRepair:true,keepAllowed:false};}}}}}throw Error('release-policy-not-maintainable');});
    const manifest=await stage('核验差评本地依赖',async()=>readJson(MANIFEST));
    const selfHash=await stage('核验维护器完整性',()=>assertLocalIntegrity(manifest,{allowCodeRepair:policy.rebind||policy.codeRepair}));
    const publicInspect=await stage('核验公共微信依赖',publicManifestClean);
    const publicHash=sha256(await fs.readFile(PUBLIC_MANIFEST));
    const bridgeHash=sha256(await fs.readFile(PUBLIC_BRIDGE));
    const desktopBridgeHash=sha256(await fs.readFile(PUBLIC_DESKTOP_BRIDGE));
    if(publicInspect.manifest.files?.['scripts/workflow_bridge_windows.py']!==bridgeHash)throw Error('public-bridge-not-bound-by-public-manifest');
    if(publicInspect.manifest.files?.['scripts/workflow_bridge.py']!==desktopBridgeHash)throw Error('public-desktop-bridge-not-bound-by-public-manifest');
    if(manifest.files?.[PUBLIC_MANIFEST]===publicHash&&manifest.files?.[PUBLIC_BRIDGE]===bridgeHash&&manifest.files?.[PUBLIC_DESKTOP_BRIDGE]===desktopBridgeHash&&!policy.rebind&&!policy.codeRepair)throw Error('outer-dependency-already-current');
    const files={...manifest.files,[PUBLIC_MANIFEST]:publicHash,[PUBLIC_BRIDGE]:bridgeHash,[PUBLIC_DESKTOP_BRIDGE]:desktopBridgeHash,[SELF_KEY]:selfHash};if(policy.codeRepair)for(const file of CODE_REPAIRABLE_FILES)files[file]=sha256(await fs.readFile(path.join(SKILL_DIR,file)));const candidate={...manifest,files};
    await stage('原子更新外层依赖摘要',async()=>{await atomicJson(MANIFEST,candidate);manifestWritten=true;const reread=await readJson(MANIFEST);assert.equal(reread.files[PUBLIC_MANIFEST],publicHash);assert.equal(reread.files[PUBLIC_BRIDGE],bridgeHash);assert.equal(reread.files[PUBLIC_DESKTOP_BRIDGE],desktopBridgeHash);assert.equal(reread.files[SELF_KEY],selfHash);});
    const tests=await stage('运行差评离线回归与自检',runOfflineTests);
    const allowedBusinessDate=policy.keepAllowed?policy.allowedBusinessDate:policy.status==='SEALED'?acceptanceBusinessDate(now,policy.acceptedBusinessDate):(policy.rebind||policy.codeRepair)?buildConfig(now).businessDate:acceptanceBusinessDate(now,policy.acceptedBusinessDate);if(!policy.keepAllowed&&allowedBusinessDate<=policy.acceptedBusinessDate)throw Error('acceptance-business-date-not-future');
    const candidateBytes=await fs.readFile(MANIFEST);const acceptance=unsealedAcceptanceRecord({authorization,policy,candidateDependencyDigest:sha256(candidateBytes),allowedBusinessDate,now,publicHash,publicInspect,tests});
    await stage('原子进入一次性验收态',async()=>{if(policy.carryForward){const finalEvidence=await inspectIndependentBusinessDay(PROJECT_ROOT,policy.allowedBusinessDate,allowedBusinessDate,now);assert.deepEqual(finalEvidence,policy.carryForward);}await atomicJson(POLICY,acceptance);const reread=await readJson(POLICY);assert.equal(reread.status,'UNSEALED_ACCEPTANCE');assert.equal(reread.allowedBusinessDate,allowedBusinessDate);assert.equal(reread.candidateDependencyDigest,sha256(await fs.readFile(MANIFEST)));});
    return {ok:true,status:'prepared',allowedBusinessDate,sendAttempts:0,runtimeModelDecisions:0,totalElapsedMs:Date.now()-started,review};
  }catch(error){if(manifestWritten)await fs.writeFile(MANIFEST,originalManifest,{mode:0o600});await fs.writeFile(POLICY,originalPolicy,{mode:0o600});throw error;}
}
const PUBLIC_RESYNC_TEST='scripts/test_public_dependency_resync.mjs';
const APPROVED_PUBLIC_RECEIPT='ea6e61281e3e02de8b852e48354f5a41898a6778897449711d6cede1912d6896';
const APPROVED_CONTENT_COPY_RECEIPT='7ceb51e9fb06a4b84c0dd746826e46a3f65f2c3ac554d0e05254ee8f91c55db6';
const CONTENT_COPY_AFTER={"scripts/dependency_maintenance.py":"ed258407aa7275d4fbced64efbd87d89aaaf43ba366a415f881f88ddfd31dd17","scripts/native_image_content.jxa":"6c812071ded7d68f035fd2e41a1c5205e5fecca765c0a10a4dc3c176c1c3660b","scripts/native_image_content.py":"53e53e8c9c96550970374f99e8e1c37af71c95d3c6b7f46eaa383217e53ebedc","scripts/native_image_content_driver.py":"e2d66dcde00b4f14084c4b0fe480f71c86f896e4cf6c7bdc57bd2d2df3cf91ef","scripts/native_image_content_hook.py":"3b432103936415c94485f2b2ad017d0b1e2fabcfd79bd3165cd71573392c7dad","scripts/native_ui_post.py":"e59ebe38f6685888cb6f1465ab2647dc1fe39bbb75dc75a622d1832e6ee41407"};
const APPROVED_ERROR_DETAIL_RECEIPT='2c6f12f44913201f233feb8ff1da0ea8ece14f0f63149b03a42d3648f31d4f11';
const ERROR_DETAIL_AFTER={"scripts/dependency_maintenance.py":"92b9f7c27bf0766598b6546cab894680001b0aedce17eeddce877fa85c23dae9","scripts/native_image_content_driver.py":"eabd427dee5caed32a7bcc2b6487b601618a7b5058a8cbfe06a00d7af892387b"};
const UI_CLOSURE_AUTHORIZATION='user-20261028-ui-execution-closure';
const UI_CLOSURE_INSTRUCTION_SHA256='ad3ab4f8a8bd21f9a84a2c17242733036a90c489ba95eaf5b7208e4d60e33ce3';
const UI_CLOSURE_AFTER={
  'scripts/file_size_policy.py':'bbee1269d339bd21583b626451ef4772a1d5a4222ca5abb892bd4ab0f9173299',
  'scripts/native_ui_tree.py':'89d6e21e6f3303eca512154994ae03ffc7716908ffd1f4b3476a45b5dd4b66a7',
  'scripts/presentation_policy.py':'cea830bd3ac88a90a34932e1b3c80a1557de5c63c3724cdf9f56111d5129c507',
  'scripts/registered_ui_routes.py':'154fa6fb7dba37822f39c6b2d23920403ba635bbb46b9d365757b26dd3a9c010',
  'scripts/wecom_adapter.py':'d14448385606c83a58b96f640300049a4001db693e6a3d3a4a5884f6bb6aebd1',
  'scripts/wecom_ui_queue.py':'5ceb7ae15972a4b2564471c72eac6a94fb8d41bcc51adfffa9e14e9cdbc1e9ba',
  'config/ui-execution-policy.json':'5332b773fbf5c1044f47da9867e08c58ab122908e66582219734bf4171017351',
  'config/native-ui-selectors.json':'04d0bf97e3e1a6a743400dd8c82a06171ab921824ee7f598f6891dbf118747f9',
  'scripts/native_ui_tree.jxa':'bba531ba0fed9b84f82f57146dae4dee70afea75b30f1d467c0a359fe2d9b8e6'
};
function publicDependencyResyncCandidate({manifest,policy,receipt,publicHash,selfHash,testHash,businessDate,now}){
  if(policy.status!=='UNSEALED_ACCEPTANCE'||policy.authorizationRef!==FIXED.authorization||policy.allowedBusinessDate!==businessDate)throw Error('public-resync-policy-scope');
  const contentCopy=receipt.authorization==='user-20261028-native-image-content-copy';
  const errorDetail=receipt.authorization==='user-20261028-native-image-copy-error-detail';
  const uiClosure=receipt.authorization===UI_CLOSURE_AUTHORIZATION;
  const expectedInstruction=uiClosure?UI_CLOSURE_INSTRUCTION_SHA256:(contentCopy||errorDetail)?'8fce75de5cce301189aca6e2b6f306f6bb41b3d95786802e42445c9913792441':'dfa8a44d577f91e092bb92a7d8eac777012a9d863d7d8f4410f2f5d903626c45';
  const minimumTests=uiClosure?1:errorDetail?463:contentCopy?459:432;
  if(receipt.ok!==true||receipt.status!=='prepared'||receipt.sendAttempts!==0||receipt.runtimeModelDecisions!==0||(!uiClosure&&!contentCopy&&!errorDetail&&receipt.authorization!=='user-20261028-native-media-anchor-shift')||receipt.userInstructionSha256!==expectedInstruction||!Number.isFinite(Date.parse(receipt.expiresAt))||Date.parse(receipt.expiresAt)<=new Date(now).getTime()||receipt.tests?.ok!==true||receipt.tests?.testCount<minimumTests||receipt.capabilityCheck?.ok!==true)throw Error('public-resync-receipt-invalid');
  if(receipt.dependencyManifestPath!==PUBLIC_MANIFEST||receipt.dependencyManifestBeforeSha256!==manifest.files?.[PUBLIC_MANIFEST]||receipt.dependencyManifestAfterSha256!==publicHash)throw Error('public-resync-receipt-binding');
  const expectedPaths=uiClosure?['scripts/dependency_maintenance.py',...Object.keys(UI_CLOSURE_AFTER)]:errorDetail?Object.keys(ERROR_DETAIL_AFTER):contentCopy?Object.keys(CONTENT_COPY_AFTER):['scripts/dependency_maintenance.py','scripts/native_ui_post.py'];
  const expectedAfter=uiClosure?UI_CLOSURE_AFTER:errorDetail?ERROR_DETAIL_AFTER:contentCopy?CONTENT_COPY_AFTER:null;
  if(!Array.isArray(receipt.changes)||receipt.changes.length!==expectedPaths.length||new Set(receipt.changes.map(x=>x.path)).size!==expectedPaths.length||receipt.changes.some(x=>!expectedPaths.includes(x.path)||(expectedAfter&&(!uiClosure||x.path!=='scripts/dependency_maintenance.py')&&x.after!==expectedAfter[x.path])))throw Error('public-resync-change-scope');
  return {...manifest,files:{...manifest.files,[PUBLIC_MANIFEST]:publicHash,[SELF_KEY]:selfHash,[PUBLIC_RESYNC_TEST]:testHash}};
}
async function refreshPublicDependency(authorization,receiptFile){
  if(authorization!==MAINTENANCE_AUTHORIZATION)throw Error('maintenance-authorization-mismatch');
  const lock=await fs.open(POLICY+'.public-resync.lock','wx');
  let written=false,originalManifest,originalPolicy;
  try{
    if((await fs.readdir(path.join(PROJECT_ROOT,'runtime/state/live_steps'))).length)throw Error('public-resync-director-busy');
    originalManifest=await fs.readFile(MANIFEST);originalPolicy=await fs.readFile(POLICY);
    const manifest=JSON.parse(originalManifest),policy=JSON.parse(originalPolicy),current=buildConfig();
    if(policy.candidateDependencyDigest!==sha256(originalManifest))throw Error('public-resync-original-digest');
    const receiptBytes=await fs.readFile(receiptFile);
    const parsedReceipt=JSON.parse(receiptBytes);
    if(parsedReceipt.authorization!==UI_CLOSURE_AUTHORIZATION&&![APPROVED_PUBLIC_RECEIPT,APPROVED_CONTENT_COPY_RECEIPT,APPROVED_ERROR_DETAIL_RECEIPT].includes(sha256(receiptBytes)))throw Error('public-resync-unapproved-receipt');
    for(const [file,expected] of Object.entries(manifest.files)){
      if(file===PUBLIC_RESYNC_TEST&&parsedReceipt.authorization===UI_CLOSURE_AUTHORIZATION)continue;
      if(file===PUBLIC_RESYNC_TEST&&sha256(receiptBytes)===APPROVED_ERROR_DETAIL_RECEIPT){if(sha256(await fs.readFile(path.join(SKILL_DIR,file)))!=='84f695e84a299ec9946ef71821fcdd8f9d71ee4373da33e57238a586d3c305ca')throw Error('public-resync-unapproved-error-detail-test');continue;}
      if(file===PUBLIC_RESYNC_TEST&&sha256(receiptBytes)===APPROVED_CONTENT_COPY_RECEIPT){if(sha256(await fs.readFile(path.join(SKILL_DIR,file)))!=='61b1329e3b186cbebf57fa9304cd430b8d5ffbaa4a271a08ad1056d7729450b0')throw Error('public-resync-unapproved-content-test');continue;}
      if(file===PUBLIC_MANIFEST||file===SELF_KEY)continue;
      if(sha256(await fs.readFile(path.isAbsolute(file)?file:path.join(SKILL_DIR,file)))!==expected)throw Error('public-resync-local-drift:'+file);
    }
    const publicInspect=await publicManifestClean(),publicHash=sha256(await fs.readFile(PUBLIC_MANIFEST));
    for(const bridge of [PUBLIC_BRIDGE,PUBLIC_DESKTOP_BRIDGE])if(publicInspect.manifest.files['scripts/'+path.basename(bridge)]!==manifest.files[bridge])throw Error('public-resync-bridge-drift');
    const businessFiles=[current.state,current.sendReceipt,current.screenshotSendReceipt,path.join(FIXED.sendLedger,current.sendMarker),path.join(FIXED.summaryLedger,current.screenshotSendMarker)];
    const snapshot=async()=>Object.fromEntries(await Promise.all(businessFiles.map(async file=>[file,await absent(file)?null:sha256(await fs.readFile(file))])));
    const before=await snapshot(),candidate=publicDependencyResyncCandidate({manifest,policy,receipt:parsedReceipt,publicHash,selfHash:sha256(await fs.readFile(path.join(SKILL_DIR,SELF_KEY))),testHash:sha256(await fs.readFile(path.join(SKILL_DIR,PUBLIC_RESYNC_TEST))),businessDate:current.businessDate,now:new Date()});
    const output=path.join(PROJECT_ROOT,'runtime/state/native-image-content-install-20261028/negative-public-resync-'+sha256(receiptBytes).slice(0,12));await fs.mkdir(output,{recursive:true});
    await fs.writeFile(path.join(output,'original-dependencies.json'),originalManifest,{flag:'wx'});await fs.writeFile(path.join(output,'original-policy.json'),originalPolicy,{flag:'wx'});
    if(!originalManifest.equals(await fs.readFile(MANIFEST))||!originalPolicy.equals(await fs.readFile(POLICY)))throw Error('public-resync-concurrent-maintenance');
    written=true;await atomicJson(MANIFEST,candidate);
    await atomicJson(POLICY,{...policy,candidateDependencyDigest:sha256(await fs.readFile(MANIFEST))});
    const extra=await run(FIXED.node,[path.join(SKILL_DIR,PUBLIC_RESYNC_TEST)]);if(!extra.ok)throw Error('public-resync-test-failed:'+extra.reason);
    const tests=await runOfflineTests();
    assert.deepEqual(await snapshot(),before);
    const after=await readJson(POLICY);assert.deepEqual({...after,candidateDependencyDigest:policy.candidateDependencyDigest},policy);
    const result={ok:true,action:'refresh-public-dependency',status:after.status,businessDate:current.businessDate,sendAttempts:0,runtimeModelDecisions:0,acceptedNewDelivery:false,tests,receiptSha256:sha256(receiptBytes),businessFilesUnchanged:before,manifestBeforeSha256:sha256(originalManifest),manifestAfterSha256:sha256(await fs.readFile(MANIFEST)),policyStatusAndDatesPreserved:true};
    await atomicJson(path.join(output,'receipt.json'),result);return result;
  }catch(error){if(written){await fs.writeFile(MANIFEST,originalManifest);await fs.writeFile(POLICY,originalPolicy);}throw error;}
  finally{await lock.close();await fs.unlink(POLICY+'.public-resync.lock');}
}
export {publicDependencyResyncCandidate,refreshPublicDependency};
async function main(){const [action,authorization,receiptFile]=process.argv.slice(2);if(action==='refresh-public-dependency'&&authorization&&receiptFile){console.log(JSON.stringify(await refreshPublicDependency(authorization,receiptFile)));return;}if(action!=='prepare-unsealed-acceptance'||!authorization)throw Error('usage: maintenance_executor.mjs prepare-unsealed-acceptance AUTHORIZATION | refresh-public-dependency AUTHORIZATION RECEIPT');console.log(JSON.stringify(await prepareUnsealedAcceptance(authorization)));}
export {unsealedAcceptanceRecord,assertAllocatedStatePreEffect,currentRunIsAllocatedPreEffect,MAINTENANCE_AUTHORIZATION,nextDailyBusinessDate,acceptanceBusinessDate,isZeroSendWechatPreflightBlocked,isZeroSendWechatRuntimeBlocked,isZeroSendWechatDriverBlocked,currentRunIsComplete,currentRunIsAbsentPreEffect,currentRunHasReusableDownload,prepareUnsealedAcceptance};
if(fileURLToPath(import.meta.url)===path.resolve(process.argv[1]||''))main().catch(error=>{console.error(JSON.stringify({ok:false,status:'blocked',reason:String(error.message||error),sendAttempts:0,runtimeModelDecisions:0}));process.exitCode=1;});
