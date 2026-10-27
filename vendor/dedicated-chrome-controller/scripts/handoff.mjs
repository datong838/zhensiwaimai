import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {pathsFor,readState,safeProfileName} from './background_chrome.mjs';
import {withProfileLock,atomicState,guardConnection,assertProcess,assertListener,checkPhase,sleep,publicUrl} from './session_guard.mjs';
const require=createRequire(import.meta.url);
const {chromium}=require('../../headless-playwright/node_modules/playwright-core');

export function requireUnique(items){if(items.length!==1)throw Error('TARGET_AMBIGUOUS');return items[0];}
export function classifyMeituan(body,metadata={}){
 const security=['安全验证','滑动验证','拖动滑块','请完成验证','账号存在风险','异常登录'];
 const login=['扫码登录','账号密码登录','验证码登录','登录美团外卖','手机登录'];
 const securityMarkers=security.filter(x=>body.includes(x));const loginMarkers=login.filter(x=>body.includes(x));
 const markers=['商家中心','全部门店','今日有效订单','今日预计收入','全部订单','订单状态','巡店助手','巡检门店'].filter(x=>body.includes(x));
 const textBrand=markers.includes('商家中心')&&markers.includes('全部门店')&&(markers.includes('今日有效订单')&&markers.includes('今日预计收入')||markers.includes('全部订单')&&markers.includes('订单状态'));
 const imageBrand=metadata.site==='meituan'&&metadata.title==='美团外卖商家版'&&['全部门店','今日有效订单','今日预计收入','巡店助手','巡检门店'].every(x=>markers.includes(x));
 let rootPage=false;try{const u=new URL(metadata.url);rootPage=u.origin==='https://waimaie.meituan.com'&&u.pathname==='/';}catch{}
 const dashboardWithoutPatrol=metadata.site==='meituan'&&metadata.title==='美团外卖商家版'&&rootPage&&['全部门店','商家首页','商品管理','店铺设置','今日有效订单','今日预计收入','今日预约单','到期预约单','未读违规','未读预警'].every(x=>body.includes(x));
 const authenticated=!securityMarkers.length&&!loginMarkers.length&&(textBrand||imageBrand||dashboardWithoutPatrol);
 const reason=securityMarkers.length?'SECURITY_CHALLENGE':loginMarkers.length?'LOGIN_REQUIRED':!body.trim()?'PAGE_NOT_READY':authenticated?'AUTHENTICATED':'STRUCTURE_UNVERIFIED';
 return {authenticated,reason,markers,loginMarkers,securityMarkers,textLength:body.length};
}
export function classifyJinsha(body,metadata={}){
 const security=['安全验证','滑动验证','拖动滑块','请完成验证','账号存在风险','异常登录'];
 const securityMarkers=security.filter(x=>body.includes(x));
 const contextMarkers=['授权失败','权限异常'].filter(x=>body.includes(x));
 const loginRoute=String(metadata.url||'').includes('#/login');
 const login=['账号登录','密码登录','验证码登录','请输入账号','请输入密码'].filter(x=>body.includes(x));
 const legacy=['数据中心','实时数据','评价&AI申述','差评列表','活动监控','菜品监控','排行中心','组织架构','店铺激活'];
 const current=['总览','营业','顾客','推广魔方','辅助驾驶','店铺列表','今日实时数据'];
 const markers=[...legacy,...current].filter(x=>body.includes(x));
 const titleOk=['金鲨数据','臻肆外卖运营'].includes(metadata.title);
 const legacyOk=legacy.filter(x=>markers.includes(x)).length>=3;
 const currentOk=['总览','营业','顾客','推广魔方','辅助驾驶'].every(x=>markers.includes(x));
 const authenticated=!securityMarkers.length&&!loginRoute&&!login.length&&titleOk&&(legacyOk||currentOk);
 const reason=securityMarkers.length?'SECURITY_CHALLENGE':loginRoute||login.length?'LOGIN_REQUIRED':!body.trim()?'PAGE_NOT_READY':authenticated?'AUTHENTICATED':'STRUCTURE_UNVERIFIED';
 return {authenticated,reason,markers,loginMarkers:login,securityMarkers,contextMarkers,textLength:body.length};
}
export function classifySite(body,metadata={}){
 if(metadata.site==='jinsha')return classifyJinsha(body,metadata);
 return classifyMeituan(body,metadata);
}
function assertUrl(url,s){if(!url.startsWith(s.prefix))throw Error('UNEXPECTED_TASK_URL');}
async function targetId(context,page){const c=await context.newCDPSession(page);try{return (await c.send('Target.getTargetInfo')).targetInfo.targetId;}finally{await c.detach();}}
async function windowId(browser,id){const c=await browser.newBrowserCDPSession();try{return (await c.send('Browser.getWindowForTarget',{targetId:id})).windowId;}finally{await c.detach();}}
async function connect(p,s,o,action){await guardConnection(p,s,o,action);return chromium.connectOverCDP(`http://127.0.0.1:${s.port}`,{timeout:10000});}
async function disconnect(browser){if(browser)await browser.close();} // connectOverCDP: disconnect this client, keep external Chrome alive.
export function inViewport(box,viewport){return !!box&&box.width>1&&box.height>1&&box.x<viewport.width&&box.y<viewport.height&&box.x+box.width>0&&box.y+box.height>0;}
export async function observe(page,s){
 assertUrl(page.url(),s);
 const texts=[];
 for(const frame of page.frames()){
  if(!frame.url().startsWith(s.prefix)){
   // A visible foreign frame could contain a login/security challenge. Do not approve an unread surface.
   if(frame===page.mainFrame())throw Error('UNEXPECTED_TASK_URL');
   const element=await frame.frameElement();
   try{const box=await element.boundingBox();const viewport=await page.evaluate(()=>({width:innerWidth,height:innerHeight}));if(inViewport(box,viewport))throw Error('FRAME_ORIGIN_UNVERIFIED');}finally{await element.dispose();}
   continue;
  }
  try{texts.push(await frame.locator('body').first().innerText({timeout:5000}));}catch{throw Error('FRAME_UNREADABLE');}
 }
 assertUrl(page.url(),s);
 const title=await page.title();
 const result=classifySite([...new Set(texts)].join('\n'),{title,site:s.site,url:page.url()});
 return {...result,url:publicUrl(page.url()),title,frameCount:page.frames().length,at:new Date().toISOString()};
}
async function requireAuthenticated(page,s){
 const observation=await observe(page,s);if(!observation.authenticated)throw Error(observation.reason);return observation;
}
async function markedPage(browser,s,id,marker){
 const context=browser.contexts()[0];if(!context)throw Error('CONTEXT_MISSING');
 const matches=[];
 for(const page of context.pages()){
  if(!page.url().startsWith(s.prefix))continue;
  if(await page.evaluate(()=>window.name)===marker)matches.push(page);
 }
 const page=requireUnique(matches);
 if(await targetId(context,page)!==id)throw Error('TARGET_ID_CHANGED');
 return page;
}
async function exactTargetPage(browser,s,id){
 const context=browser.contexts()[0];if(!context)throw Error('CONTEXT_MISSING');
 const matches=[];
 for(const page of context.pages())if(page.url().startsWith(s.prefix)&&await targetId(context,page)===id)matches.push(page);
 return requireUnique(matches);
}
function receipt(s,command){return {ok:true,command,profile:s.profile,instanceId:s.instanceId,phase:s.phase,pid:s.pid,port:s.port,taskId:s.taskId,mode:s.mode,site:s.site,observations:s.observations,elapsedMs:s.elapsedMs};}
const known=/^(TARGET_|UNEXPECTED_|FRAME_|PAGE_|SECURITY_|LOGIN_|STRUCTURE_|CONTEXT_|WINDOW_|TASK_|EXPLICIT_|handoff-|managed-|cdp-|state-|profile-)/;
function safeReason(e){return known.test(e.message)?e.message:'HANDOFF_OPERATION_FAILED';}

export function canRelease(s,loginWindow,taskWindow,loginTargets){
 if(s.phase!=='TAKEOVER_VERIFIED'||loginWindow===taskWindow||loginTargets.length!==1)throw Error('WINDOW_RELEASE_UNSAFE');
}
export async function inspectHandoff(p,s,o){
 if(o['task-id']!==s.taskId)throw Error('TASK_ID_MISMATCH');
 const b=await connect(p,s,o,'inspect');try{
  const released=s.phase==='WINDOW_RELEASED';
  const page=await markedPage(b,s,s.activeTargetId||(released?s.taskTargetId:s.loginTargetId),s.activeMarker||(released?s.taskMarker:s.loginMarker));
  return {...receipt(s,'inspect'),observation:await requireAuthenticated(page,s)};
 }finally{await disconnect(b);}
}
export async function runHandoff(command,o){
 const p=pathsFor(o);
 return withProfileLock(p,async()=>{
  let s=await readState(p);checkPhase(s,o,command);
  if(command==='confirm-login'){
   if(o['user-confirmed']!==true)throw Error('EXPLICIT_USER_CONFIRMATION_REQUIRED');
   await assertProcess(p,s);await assertListener(s);
   s={...s,phase:'USER_CONFIRMED',confirmedAt:new Date().toISOString(),confirmationInstance:s.instanceId};
   await atomicState(p,s);return receipt(s,command);
  }
  await guardConnection(p,s,o,command);
  if(command==='diagnose-target'||command==='verify-work-page'){if(o['task-id']!==s.taskId)throw Error('TASK_ID_MISMATCH');return inspectFailedTarget(p,s,o,command);}
  if(command==='minimize-work-window'){if(o['task-id']!==s.taskId)throw Error('TASK_ID_MISMATCH');return minimizeWorkWindow(p,s,o);}
  if(command==='ensure-jinsha-context'){if(o['task-id']!==s.taskId)throw Error('TASK_ID_MISMATCH');return ensureJinshaContext(p,s,o);}
  if(command==='recover-target'){safeProfileName(o['task-id']);return recoverTarget(p,s,o);}
  if(command==='release-recovered-pages'){if(o['task-id']!==s.taskId||!s.activeTargetId||!s.recoveryAttempted)throw Error('TASK_ID_MISMATCH');return releaseRecovered(p,s,o);}
  if(command==='takeover'){
   safeProfileName(o['task-id']);
   if(s.confirmationInstance!==s.instanceId)throw Error('handoff-confirmation-mismatch');
   return takeover(p,s,o);
  }
  if(command==='release-login-window'){
   if(o['task-id']!==s.taskId)throw Error('TASK_ID_MISMATCH');
   return release(p,s,o);
  }
  throw Error('unknown-handoff-command');
 });
}
async function visibleExact(page,label){
 const hits=[];for(const frame of page.frames()){const loc=frame.getByText(label,{exact:true});for(let i=0;i<await loc.count();i++){const item=loc.nth(i);if(await item.isVisible().catch(()=>false))hits.push(item);}}return hits;
}
export function shouldOpenJinshaContextMenu(waimaiCount){return waimaiCount===0;}
async function ensureJinshaContext(p,s,o){
 const access=s;let b;
 try{
  const inferredAttempts=Number.isInteger(s.contextRepairAttempts)?s.contextRepairAttempts:String(s.failure||'').startsWith('CONTEXT_')?1:0;
  s={...s,contextRepairAttempts:inferredAttempts+1};await atomicState(p,{...s,phase:'REPAIRING_CONTEXT'});
  b=await connect(p,access,o,'ensure-jinsha-context');const id=s.activeTargetId||s.loginTargetId,marker=s.activeMarker||s.loginMarker;
  const page=await markedPage(b,s,id,marker);assertUrl(page.url(),s);
  let waimai=await visibleExact(page,'外卖');
  if(shouldOpenJinshaContextMenu(waimai.length)){const button=page.locator('.hamburger-container:visible');if(await button.count()!==1)throw Error('CONTEXT_MENU_NOT_UNIQUE');await button.click();await sleep(500);waimai=await visibleExact(page,'外卖');}
  if(waimai.length!==1)throw Error('CONTEXT_WAIMAI_NOT_UNIQUE');
  await waimai[0].click();await sleep(800);
  let taobao=await visibleExact(page,'淘宝');if(taobao.length!==1)throw Error('CONTEXT_TAOBAO_NOT_UNIQUE');
  await taobao[0].click();await sleep(1200);
  waimai=await visibleExact(page,'外卖');taobao=await visibleExact(page,'淘宝');
  const waimaiSelected=waimai.length===1&&String(await waimai[0].getAttribute('class')).split(/\s+/).includes('complete_active');
  const taobaoSelected=taobao.length===1&&String(await taobao[0].getAttribute('class')).split(/\s+/).includes('pitchOn');
  if(!waimaiSelected||!taobaoSelected)throw Error('CONTEXT_SELECTION_UNVERIFIED');
  await sleep(1500);const observation=await requireAuthenticated(page,s);
  s={...s,phase:'TAKEOVER_VERIFIED',failure:null,context:{business:'外卖',platform:'淘宝',warnings:observation.contextMarkers||[],verifiedAt:new Date().toISOString()},observations:[observation]};
  await atomicState(p,s);return {...receipt(s,'ensure-jinsha-context'),context:s.context};
 }catch(e){await atomicState(p,{...s,phase:'BLOCKED',failure:safeReason(e)});throw Error(safeReason(e));}
 finally{await disconnect(b);}
}
async function takeover(p,s,o){
 const started=Date.now();let b;
 try{
  // Persist in-flight state before attachment. A crashed run cannot be replayed as confirmed.
  await atomicState(p,{...s,phase:'VERIFYING'});
  b=await connect(p,s,o,'takeover');
  const context=b.contexts()[0];if(!context)throw Error('CONTEXT_MISSING');
  const page=requireUnique(context.pages().filter(page=>page.url().startsWith(s.prefix)));
  const id=await targetId(context,page);const marker=`aos-background-task:${o['task-id']}:login`;
  await page.evaluate(value=>{window.name=value;},marker);
  s={...s,taskId:o['task-id'],loginTargetId:id,loginMarker:marker};
  await atomicState(p,{...s,phase:'VERIFYING'});
  const first=await requireAuthenticated(page,s);
  s={...s,observations:[first]};
  await disconnect(b);b=null;
  await sleep(3000);
  b=await connect(p,s,o,'takeover');
  const second=await requireAuthenticated(await markedPage(b,s,id,marker),s);
  s={...s,phase:'TAKEOVER_VERIFIED',automationAttached:true,observations:[first,second],elapsedMs:Date.now()-started};
  await atomicState(p,s);return receipt(s,'takeover');
 }catch(e){await atomicState(p,{...s,phase:'BLOCKED',failure:safeReason(e)});throw Error(safeReason(e));}
 finally{await disconnect(b);}
}
async function loginWindowTargets(browser,s,loginWindow){
 const context=browser.contexts()[0];const ids=[];
 for(const page of context.pages()){
  const id=await targetId(context,page);
  if(await windowId(browser,id)===loginWindow)ids.push(id);
 }
 return ids;
}
async function release(p,s,o){
 const access=s;let b;let closing=false;
 try{
  const initialResume=s.phase==='BLOCKED'&&s.failure==='HANDOFF_OPERATION_FAILED'&&s.taskTargetId&&s.taskMarker;
  const structureResume=s.phase==='BLOCKED'&&s.failure==='STRUCTURE_UNVERIFIED'&&s.taskTargetId&&s.taskMarker&&s.lastDiagnosticObservation?.authenticated===true;
  const correctionResume=s.phase==='BLOCKED'&&s.failure==='WINDOW_RELEASE_UNSAFE'&&s.releaseCorrectionReady===true&&s.taskTargetId&&s.taskMarker;
  const internalResume=s.phase==='BLOCKED'&&s.failure==='handoff-release-resume-forbidden'&&s.releaseInternalReady===true&&s.taskTargetId&&s.taskMarker;
  const resumeExisting=initialResume||structureResume||correctionResume||internalResume;
  if(initialResume)s={...s,releaseResumeAttempts:(s.releaseResumeAttempts??0)+1};
  if(structureResume)s={...s,releaseStructureAttempts:(s.releaseStructureAttempts??0)+1};
  if(correctionResume)s={...s,releaseCorrectionAttempts:(s.releaseCorrectionAttempts??0)+1,releaseCorrectionReady:false};
  if(internalResume)s={...s,releaseInternalCorrectionAttempts:(s.releaseInternalCorrectionAttempts??0)+1,releaseInternalReady:false};
  await atomicState(p,{...s,phase:'PREPARING_WINDOW'});
  b=await connect(p,access,o,'release-login-window');
  const login=await markedPage(b,s,s.loginTargetId,s.loginMarker);
  await requireAuthenticated(login,s);
  const loginWindow=await windowId(b,s.loginTargetId);
  const before=await loginWindowTargets(b,s,loginWindow);
  if(before.length!==1||before[0]!==s.loginTargetId)throw Error('WINDOW_CONTAINS_UNOWNED_TABS');
  let newId=s.taskTargetId;let task;
  if(resumeExisting){task=await exactTargetPage(b,s,newId);assertUrl(task.url(),s);await task.evaluate(value=>{window.name=value;},s.taskMarker);}
  else{
   const c=await b.newBrowserCDPSession();
   try{newId=(await c.send('Target.createTarget',{url:login.url(),newWindow:true,background:true})).targetId;}finally{await c.detach();}
   s={...s,taskTargetId:newId,taskMarker:`aos-background-task:${s.taskId}:work`};
   await atomicState(p,{...s,phase:'PREPARING_WINDOW'});
   for(let i=0;i<40;i++){
    const found=[];for(const page of b.contexts()[0].pages())if(await targetId(b.contexts()[0],page)===newId)found.push(page);
    if(found.length===1){task=found[0];break;}await sleep(100);
   }
   if(!task)throw Error('TASK_WINDOW_NOT_READY');
   await task.waitForLoadState('domcontentloaded',{timeout:15000});assertUrl(task.url(),s);
   await task.evaluate(value=>{window.name=value;},s.taskMarker);
  }
  const first=await requireAuthenticated(task,s);
  const taskWindow=await windowId(b,newId);
  canRelease(resumeExisting?{...s,phase:'TAKEOVER_VERIFIED'}:s,loginWindow,taskWindow,before);
  await disconnect(b);b=null;await sleep(3000);
  b=await connect(p,access,o,'release-login-window');
  const work=await markedPage(b,s,newId,s.taskMarker);await requireAuthenticated(work,s);
  const original=await markedPage(b,s,s.loginTargetId,s.loginMarker);await requireAuthenticated(original,s);
  const currentLoginWindow=await windowId(b,s.loginTargetId);const currentTaskWindow=await windowId(b,newId);
  const currentIds=await loginWindowTargets(b,s,currentLoginWindow);
  canRelease(resumeExisting?{...s,phase:'TAKEOVER_VERIFIED'}:s,currentLoginWindow,currentTaskWindow,currentIds);
  if(currentIds[0]!==s.loginTargetId)throw Error('WINDOW_RELEASE_UNSAFE');
  await assertProcess(p,s);await assertListener(s);
  closing=true;await atomicState(p,{...s,phase:'CLOSING'});
  await original.close({runBeforeUnload:false});
  const final=await requireAuthenticated(work,s);
  await assertProcess(p,s);await assertListener(s);
  s={...s,phase:'WINDOW_RELEASED',observations:[first,final],releasedAt:new Date().toISOString()};
  await atomicState(p,s);return receipt(s,'release-login-window');
 }catch(e){await atomicState(p,{...s,phase:closing?'CLOSE_OUTCOME_UNKNOWN':'BLOCKED',failure:safeReason(e)});throw Error(safeReason(e));}
 finally{await disconnect(b);}
}

async function recoverTarget(p,s,o){
 const access=s;let b;const started=Date.now();
 try{
  s={...s,recoveryAttempted:true,taskId:o['task-id']};
  await atomicState(p,{...s,phase:'RECOVERING_TARGET'});
  b=await connect(p,access,o,'recover-target');
  const context=b.contexts()[0];if(!context)throw Error('CONTEXT_MISSING');
  const previous=[];
  for(const page of context.pages())if(page.url().startsWith(s.prefix))previous.push(await targetId(context,page));
  assertUrl(s.url,s);
  const c=await b.newBrowserCDPSession();let id;
  try{id=(await c.send('Target.createTarget',{url:s.url,newWindow:true,background:true})).targetId;}finally{await c.detach();}
  s={...s,activeTargetId:id,activeMarker:`aos-background-task:${o['task-id']}:recovered`,recoveryPreviousTargets:previous};
  await atomicState(p,{...s,phase:'RECOVERING_TARGET'});
  let page;
  for(let i=0;i<40;i++){
   for(const candidate of context.pages())if(await targetId(context,candidate)===id){page=candidate;break;}
   if(page)break;await sleep(100);
  }
  if(!page)throw Error('TASK_WINDOW_NOT_READY');
  await page.waitForLoadState('domcontentloaded',{timeout:15000});
  assertUrl(page.url(),s);await page.evaluate(marker=>{window.name=marker;},s.activeMarker);
  const first=await requireAuthenticated(page,s);
  await disconnect(b);b=null;await sleep(3000);
  b=await connect(p,access,o,'recover-target');
  const second=await requireAuthenticated(await markedPage(b,s,id,s.activeMarker),s);
  s={...s,phase:'TAKEOVER_VERIFIED',failure:null,automationAttached:true,observations:[first,second],elapsedMs:Date.now()-started};
  await atomicState(p,s);return receipt(s,'recover-target');
 }catch(e){await atomicState(p,{...s,phase:'BLOCKED',failure:safeReason(e)});throw Error(safeReason(e));}
 finally{await disconnect(b);}
}
async function releaseRecovered(p,s,o){
 let b;let closing=false;
 try{
  b=await connect(p,s,o,'release-recovered-pages');
  const work=await markedPage(b,s,s.activeTargetId,s.activeMarker);await requireAuthenticated(work,s);
  const context=b.contexts()[0];const previous=new Set(s.recoveryPreviousTargets||[]);const closable=[];
  if(previous.has(s.activeTargetId))throw Error('WINDOW_RELEASE_UNSAFE');
  for(const page of context.pages()){
   const id=await targetId(context,page);
   if(previous.has(id)){assertUrl(page.url(),s);closable.push(page);}
  }
  closing=true;await atomicState(p,{...s,phase:'CLOSING'});
  for(const page of closable){assertUrl(page.url(),s);await page.close({runBeforeUnload:false});}
  const observation=await requireAuthenticated(work,s);await assertProcess(p,s);await assertListener(s);
  s={...s,phase:'WINDOW_RELEASED',closedPreviousTargets:closable.length,observations:[observation]};
  await atomicState(p,s);return {...receipt(s,'release-recovered-pages'),closedPreviousTargets:s.closedPreviousTargets};
 }catch(e){await atomicState(p,{...s,phase:closing?'CLOSE_OUTCOME_UNKNOWN':'BLOCKED',failure:safeReason(e)});throw Error(safeReason(e));}
 finally{await disconnect(b);}
}

async function inspectFailedTarget(p,s,o,command){
 const access=s;let b;
 try{
  if(command==='verify-work-page'){
   const contextPostVerify=String(s.failure||'').startsWith('CONTEXT_')&&s.lastDiagnosticObservation?.authenticated===true;
   s=contextPostVerify?{...s,contextPostVerifyAttempts:(s.contextPostVerifyAttempts??0)+1}:{...s,workVerifyAttempts:(s.workVerifyAttempts??1)+1};
   await atomicState(p,{...s,phase:'VERIFYING'});
  }
  const releaseTargetDiagnostic=command==='diagnose-target'&&['HANDOFF_OPERATION_FAILED','WINDOW_RELEASE_UNSAFE','handoff-release-resume-forbidden'].includes(s.failure)&&s.taskTargetId&&s.taskMarker;
  const boundId=releaseTargetDiagnostic?s.taskTargetId:s.activeTargetId||s.loginTargetId;const boundMarker=releaseTargetDiagnostic?s.taskMarker:s.activeMarker||s.loginMarker;
  b=await connect(p,access,o,command);const page=releaseTargetDiagnostic?await exactTargetPage(b,s,boundId):await markedPage(b,s,boundId,boundMarker);
  if(command==='diagnose-target'){
   let observation;try{observation=await observe(page,s);}catch(e){observation={reason:safeReason(e)};}
   if(releaseTargetDiagnostic&&observation?.reason){
    const correction=s.failure==='WINDOW_RELEASE_UNSAFE';const internal=s.failure==='handoff-release-resume-forbidden';
    await atomicState(p,{...s,lastReleaseTargetDiagnosticObservation:observation,...(correction?{releaseCorrectionReady:observation.authenticated===true,releaseCorrectionDiagnosticAt:new Date().toISOString()}:{}),...(internal?{releaseInternalReady:observation.authenticated===true,releaseInternalDiagnosticAt:new Date().toISOString()}:{})});
   }
   else if(s.site==='jinsha'&&observation?.reason)await atomicState(p,{...s,lastDiagnosticObservation:observation});
   const result={...receipt(s,command),observation,frames:page.frames().map(f=>({url:publicUrl(f.url()),main:f===page.mainFrame()}))};
   if(s.site==='jinsha'){
    const labels=['外卖','团购','分账','美团','淘宝','京东','总览','营业','顾客','智能斗金','推广魔方','全站推广列表','辅助驾驶','店铺列表','今日实时数据'];
    result.jinshaControls={};
    for(const label of labels){const rows=[];for(const frame of page.frames()){const loc=frame.getByText(label,{exact:true});for(let i=0;i<await loc.count();i++){const item=loc.nth(i);if(!await item.isVisible().catch(()=>false))continue;rows.push(await item.evaluate(el=>({tag:el.tagName,className:String(el.className||''),parentClassName:String(el.parentElement?.className||''),ariaPressed:el.getAttribute('aria-pressed'),ariaChecked:el.getAttribute('aria-checked')})));}}result.jinshaControls[label]=rows;}
   }
   if(o.screenshot){assertUrl(page.url(),s);const file=path.resolve(o.screenshot);await fs.mkdir(path.dirname(file),{recursive:true});await page.screenshot({path:file,fullPage:false});result.screenshot=file;}
   return result;
  }
  const first=await requireAuthenticated(page,s);await disconnect(b);b=null;await sleep(3000);
  b=await connect(p,access,o,command);const second=await requireAuthenticated(await markedPage(b,s,boundId,boundMarker),s);
  s={...s,phase:'TAKEOVER_VERIFIED',failure:null,automationAttached:true,observations:[first,second]};await atomicState(p,s);return receipt(s,command);
 }catch(e){if(command==='verify-work-page')await atomicState(p,{...s,phase:'BLOCKED',failure:safeReason(e)});throw Error(safeReason(e));}
 finally{await disconnect(b);}
}

async function minimizeWorkWindow(p,s,o){
 let b;
 try{
  b=await connect(p,s,o,'minimize-work-window');
  const id=s.activeTargetId||(s.phase==='WINDOW_RELEASED'?s.taskTargetId:s.loginTargetId);
  const marker=s.activeMarker||(s.phase==='WINDOW_RELEASED'?s.taskMarker:s.loginMarker);
  const page=await markedPage(b,s,id,marker);await requireAuthenticated(page,s);
  const win=await windowId(b,id);const ids=await loginWindowTargets(b,s,win);
  if(ids.length!==1||ids[0]!==id)throw Error('WINDOW_CONTAINS_UNOWNED_TABS');
  const c=await b.newBrowserCDPSession();
  try{
   const initial=await c.send('Browser.getWindowBounds',{windowId:win});
   if(initial.bounds.windowState!=='minimized')await c.send('Browser.setWindowBounds',{windowId:win,bounds:{windowState:'minimized'}});
   await waitMinimized(c,win,'AFTER_SET');
  }finally{await c.detach();}
  const first=await requireAuthenticated(page,s);await disconnect(b);b=null;await sleep(3000);
  b=await connect(p,s,o,'minimize-work-window');
  const work=await markedPage(b,s,id,marker);const second=await requireAuthenticated(work,s);
  const check=await b.newBrowserCDPSession();
  try{await waitMinimized(check,await windowId(b,id),'AFTER_RECONNECT');}finally{await check.detach();}
  s={...s,workWindowState:'minimized',minimizedVerifiedAt:new Date().toISOString(),observations:[first,second]};await atomicState(p,s);
  return {...receipt(s,'minimize-work-window'),workWindowState:'minimized',reconnectedWhileMinimized:true};
 }catch(e){await atomicState(p,{...s,minimizeFailure:safeReason(e)});throw Error(safeReason(e));}
 finally{await disconnect(b);}
}

async function waitMinimized(session,id,stage){
 for(let i=0;i<30;i++){if((await session.send('Browser.getWindowBounds',{windowId:id})).bounds.windowState==='minimized')return;await sleep(100);}
 throw Error('WINDOW_NOT_MINIMIZED_'+stage);
}
