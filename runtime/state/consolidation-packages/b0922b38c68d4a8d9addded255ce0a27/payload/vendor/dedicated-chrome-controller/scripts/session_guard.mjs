import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {randomUUID} from 'node:crypto';
const exec=promisify(execFile);
export const CHROME='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
export const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
export function publicUrl(value){try{const u=new URL(value);return u.origin+u.pathname;}catch{return 'invalid-url';}}
export async function atomicState(p,s){
 const file=path.join(p.meta,`state-${randomUUID()}.tmp`);
 await fs.writeFile(file,JSON.stringify(s,null,2),{mode:0o600});
 await fs.rename(file,p.state);
}
export async function withProfileLock(p,fn){
 await fs.mkdir(p.meta,{recursive:true,mode:0o700});
 const lock=path.join(p.meta,'operation.lock');
 try{await fs.mkdir(lock,{mode:0o700});}catch(e){if(e.code==='EEXIST')throw Error('profile-operation-busy');throw e;}
 try{return await fn();}finally{await fs.rmdir(lock);}
}
export async function processIdentity(pid){
 const env={...process.env,LC_ALL:'C',LANG:'C'};
 try{
 const [cmd,start]=await Promise.all([exec('/bin/ps',['-p',String(pid),'-o','command='],{env}),exec('/bin/ps',['-p',String(pid),'-o','lstart='],{env})]);
 return {cmd:cmd.stdout.trim(),start:start.stdout.trim()};
 }catch{return {cmd:'',start:''};}
}
function hasArg(cmd,arg){return cmd.endsWith(arg)||cmd.includes(arg+' ');}
function identityValid(p,s,actual){
 if(!s||!actual||!actual.cmd.startsWith(CHROME+' ')||!hasArg(actual.cmd,`--user-data-dir=${p.profile}`))return false;
 if(s.port&&!hasArg(actual.cmd,`--remote-debugging-port=${s.port}`))return false;
 if(s.mode==='headless'&&!actual.cmd.includes('--headless'))return false;
 if(s.processStartedAt&&s.processStartedAt!==actual.start)return false;
 return true;
}
export function checkIdentity(p,s,actual){
 if(!identityValid(p,s,actual))throw Error('managed-process-identity-mismatch');
 if(s.mode==='visible-handoff'&&(!s.processStartedAt||!s.instanceId))throw Error('managed-process-identity-mismatch');
}
export function checkListeners(output,pid,port){
 let current=null;let count=0;
 for(const line of output.trim().split('\n')){
  if(line.startsWith('p'))current=Number(line.slice(1));
  if(line.startsWith('n')){
   if(current!==pid||!['127.0.0.1:'+port,'[::1]:'+port].includes(line.slice(1)))throw Error('cdp-listener-identity-mismatch');
   count++;
  }
 }
 if(!count)throw Error('cdp-listener-unavailable');
}
async function discoverManagedProcess(p,s){
 if(!s?.port)return null;
 let out='';
 try{out=(await exec('/usr/sbin/lsof',['-nP',`-iTCP:${s.port}`,'-sTCP:LISTEN','-Fpn'])).stdout;}catch{return null;}
 let pid=null;for(const line of out.split('\n')){if(line.startsWith('p'))pid=Number(line.slice(1));}
 if(!pid)return null;
 const env={...process.env,LC_ALL:'C',LANG:'C'};
 const [cmd,start]=await Promise.all([
  exec('/bin/ps',['-p',String(pid),'-o','command='],{env}).catch(()=>({stdout:''})),
  exec('/bin/ps',['-p',String(pid),'-o','lstart='],{env}).catch(()=>({stdout:''}))
 ]);
 return {pid,cmd:cmd.stdout.trim(),start:start.stdout.trim()};
}
export async function assertProcess(p,s){
 const actual=await processIdentity(s?.pid);
 if(identityValid(p,s,actual)){checkIdentity(p,s,actual);return;}
 // 记录的 pid 查不到/启动时间对不上（进程在 launcher 控制之外重启）时，按端口重新发现受管 Chrome 并自愈 state。
 const found=await discoverManagedProcess(p,s);
 if(found&&identityValid(p,s,found)){
  s.pid=found.pid;s.processStartedAt=found.start;
  try{await atomicState(p,{...s});}catch{}
  checkIdentity(p,s,found);return;
 }
 throw Error('managed-process-identity-mismatch');
}
export async function assertListener(s){
 let output='';try{output=(await exec('/usr/sbin/lsof',['-nP',`-iTCP:${s.port}`,'-sTCP:LISTEN','-Fpn'])).stdout;}catch{throw Error('cdp-listener-unavailable');}
 checkListeners(output,s.pid,s.port);
}
export function hasSafeJinshaContextRecoveryObservation(s){
 const observation=s?.lastDiagnosticObservation;
 const required=['总览','营业','顾客','辅助驾驶','店铺列表','今日实时数据'];
 return observation?.authenticated===false&&observation?.reason==='STRUCTURE_UNVERIFIED'&&
  ['金鲨数据','臻肆外卖运营'].includes(observation?.title)&&observation?.url==='https://data.guoshuyufen.com/'&&
  Array.isArray(observation?.loginMarkers)&&observation.loginMarkers.length===0&&
  Array.isArray(observation?.securityMarkers)&&observation.securityMarkers.length===0&&
  Array.isArray(observation?.markers)&&required.every(marker=>observation.markers.includes(marker));
}
export function hasAuthenticatedJinshaDiagnostic(s){
 const observation=s?.lastDiagnosticObservation;
 return observation?.authenticated===true&&observation?.reason==='AUTHENTICATED'&&
  ['金鲨数据','臻肆外卖运营'].includes(observation?.title)&&observation?.url==='https://data.guoshuyufen.com/'&&
  Array.isArray(observation?.loginMarkers)&&observation.loginMarkers.length===0&&
  Array.isArray(observation?.securityMarkers)&&observation.securityMarkers.length===0;
}
export function hasAuthenticatedJinshaReleaseDiagnostic(s){
 const observation=s?.lastReleaseTargetDiagnosticObservation;
 return observation?.authenticated===true&&observation?.reason==='AUTHENTICATED'&&
  ['金鲨数据','臻肆外卖运营'].includes(observation?.title)&&observation?.url==='https://data.guoshuyufen.com/'&&
  Array.isArray(observation?.loginMarkers)&&observation.loginMarkers.length===0&&
  Array.isArray(observation?.securityMarkers)&&observation.securityMarkers.length===0;
}
export function checkPhase(s,o,action){
 if(!s)throw Error('managed-state-missing');
 if(s.mode==='visible')throw Error('legacy-visible-no-control-interface');
 if(!['visible-handoff','headless'].includes(s.mode))throw Error('managed-mode-invalid');
 if(s.mode!=='visible-handoff'){
  if(['confirm-login','takeover','release-login-window','recover-target','release-recovered-pages','diagnose-target','verify-work-page','minimize-work-window'].includes(action))throw Error('handoff-mode-required');
  return;
 }
 if(o.instance!==s.instanceId)throw Error('handoff-instance-mismatch');
 if(action==='recover-target'){
  const ambiguous=s.failure==='TARGET_AMBIGUOUS';
  const legacyUnbound=s.failure==='STRUCTURE_UNVERIFIED'&&!s.activeTargetId&&!s.loginTargetId;
  if(s.phase!=='BLOCKED'||(!ambiguous&&!legacyUnbound)||s.recoveryAttempted||s.confirmationInstance!==s.instanceId)throw Error('handoff-recovery-forbidden');
  return;
 }
 if(action==='ensure-jinsha-context'){
  const bound=(s.activeTargetId&&s.activeMarker)||(s.loginTargetId&&s.loginMarker);
  const legacyContextFailure=s.failure==='SECURITY_CHALLENGE'&&Array.isArray(s.observations)&&s.observations.some(x=>x.authenticated===true);
  const retryableContextFailure=['CONTEXT_MENU_NOT_UNIQUE','CONTEXT_WAIMAI_NOT_UNIQUE','CONTEXT_TAOBAO_NOT_UNIQUE','CONTEXT_SELECTION_UNVERIFIED'].includes(s.failure)&&(s.contextRepairAttempts??1)<2;
  const diagnosedStructureFailure=(s.failure==='STRUCTURE_UNVERIFIED'||retryableContextFailure)&&hasSafeJinshaContextRecoveryObservation(s);
  const phaseOk=s.phase==='TAKEOVER_VERIFIED'||s.phase==='BLOCKED'&&(s.failure==='CONTEXT_AUTHORIZATION_FAILED'||legacyContextFailure||diagnosedStructureFailure);
  if(s.site!=='jinsha'||!bound||!phaseOk||s.confirmationInstance!==s.instanceId)throw Error('jinsha-context-repair-forbidden');
  return;
 }
 if(action==='diagnose-target'||action==='verify-work-page'){
  const hasBoundTarget=(s.activeTargetId&&s.activeMarker)||(s.loginTargetId&&s.loginMarker);
  const contextFailure=['CONTEXT_MENU_NOT_UNIQUE','CONTEXT_WAIMAI_NOT_UNIQUE','CONTEXT_TAOBAO_NOT_UNIQUE','CONTEXT_SELECTION_UNVERIFIED'].includes(s.failure);
  const contextDiagnostic=action==='diagnose-target'&&contextFailure&&hasSafeJinshaContextRecoveryObservation(s);
  const contextPostVerify=action==='verify-work-page'&&contextFailure&&hasAuthenticatedJinshaDiagnostic(s)&&(s.contextPostVerifyAttempts??0)<1;
  const initialReleaseDiagnostic=s.failure==='HANDOFF_OPERATION_FAILED';
  const correctionReleaseDiagnostic=s.failure==='WINDOW_RELEASE_UNSAFE'&&s.releaseResumeAttempts===1&&(s.releaseCorrectionAttempts??0)<1;
  const internalReleaseDiagnostic=s.failure==='handoff-release-resume-forbidden'&&s.releaseResumeAttempts===1&&s.releaseCorrectionAttempts===1&&(s.releaseInternalCorrectionAttempts??0)<1;
  const releaseTargetDiagnostic=action==='diagnose-target'&&(initialReleaseDiagnostic||correctionReleaseDiagnostic||internalReleaseDiagnostic)&&s.loginTargetId&&s.loginMarker&&s.taskTargetId&&s.taskMarker;
  if(s.phase!=='BLOCKED'||!hasBoundTarget||s.confirmationInstance!==s.instanceId||!['STRUCTURE_UNVERIFIED','PAGE_NOT_READY','FRAME_ORIGIN_UNVERIFIED'].includes(s.failure)&&!contextDiagnostic&&!contextPostVerify&&!releaseTargetDiagnostic)throw Error('handoff-diagnosis-forbidden');
  if(action==='verify-work-page'&&!contextPostVerify&&(s.workVerifyAttempts??1)>=2)throw Error('handoff-verification-limit');
  return;
 }
 if(action==='release-login-window'&&s.phase==='BLOCKED'){
  const resumable=s.failure==='HANDOFF_OPERATION_FAILED'&&s.site==='jinsha'&&s.loginTargetId&&s.loginMarker&&s.taskTargetId&&s.taskMarker&&hasAuthenticatedJinshaReleaseDiagnostic(s)&&(s.releaseResumeAttempts??0)<1;
  const structureResumable=s.failure==='STRUCTURE_UNVERIFIED'&&s.site==='jinsha'&&s.loginTargetId&&s.loginMarker&&s.taskTargetId&&s.taskMarker&&hasAuthenticatedJinshaDiagnostic(s)&&(s.releaseStructureAttempts??0)<1;
  const correctable=s.failure==='WINDOW_RELEASE_UNSAFE'&&s.site==='jinsha'&&s.loginTargetId&&s.loginMarker&&s.taskTargetId&&s.taskMarker&&s.releaseResumeAttempts===1&&s.releaseCorrectionReady===true&&hasAuthenticatedJinshaReleaseDiagnostic(s)&&(s.releaseCorrectionAttempts??0)<1;
  const internallyCorrectable=s.failure==='handoff-release-resume-forbidden'&&s.site==='jinsha'&&s.loginTargetId&&s.loginMarker&&s.taskTargetId&&s.taskMarker&&s.releaseResumeAttempts===1&&s.releaseCorrectionAttempts===1&&s.releaseInternalReady===true&&hasAuthenticatedJinshaReleaseDiagnostic(s)&&(s.releaseInternalCorrectionAttempts??0)<1;
  if(!resumable&&!structureResumable&&!correctable&&!internallyCorrectable)throw Error('handoff-release-resume-forbidden');
  return;
 }
 const allowed={
  'confirm-login':['MANUAL_LOGIN'],takeover:['USER_CONFIRMED'],
  'release-login-window':['TAKEOVER_VERIFIED'],'release-recovered-pages':['TAKEOVER_VERIFIED'],
  'minimize-work-window':['TAKEOVER_VERIFIED','WINDOW_RELEASED'],probe:['TAKEOVER_VERIFIED','WINDOW_RELEASED'],inspect:['TAKEOVER_VERIFIED','WINDOW_RELEASED']
 };
 if(!(allowed[action]||[]).includes(s.phase))throw Error('handoff-phase-forbids-'+action);
}
export async function guardConnection(p,s,o,action){
 checkPhase(s,o,action);
 if(Number(o.port??s.port)!==s.port)throw Error('state-port-mismatch');
 await assertProcess(p,s);await assertListener(s);
}
export function handoffConfig(o){
 if(o['test-url']){
  const u=new URL(o['test-url']);const root=path.resolve(o['profile-root']||'.');
  if(!String(o.profile).startsWith('test-')||!root.startsWith(path.resolve(os.tmpdir())+path.sep)&&!root.startsWith('/tmp/')||u.hostname!=='127.0.0.1'||u.protocol!=='http:'||u.username||u.password)throw Error('fixture-mode-requires-temporary-loopback-profile');
  const port=Number(o.port);if(!Number.isInteger(port)||port<1024||port>65535||[9230,9231,9232,9233].includes(port))throw Error('fixture-port-invalid');
  return {site:'fixture-meituan',prefix:u.origin+'/',url:u.href,port};
 }
 const production={
  'meituan-merchant':{site:'meituan',port:9233,prefix:'https://waimaie.meituan.com/',url:'https://waimaie.meituan.com/?ignoreSetRouterProxy=true'},
  'jinsha-business':{site:'jinsha',port:9232,prefix:'https://data.guoshuyufen.com/',url:'https://data.guoshuyufen.com/#/businessData/realTimeData'}
 };
 const config=production[o.profile];
 if(!config||Number(o.port??config.port)!==config.port)throw Error('handoff-profile-port-required');
 const {site,port,prefix}=config;const url=o.url||config.url;
 if(!url.startsWith(prefix))throw Error('unexpected-task-url');
 return {site,prefix,url,port};
}
