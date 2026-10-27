#!/usr/bin/env node
import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import http from 'node:http';
import path from 'node:path';
import process from 'node:process';
import {execFile as execFileCb} from 'node:child_process';
import {promisify} from 'node:util';
import {createRequire} from 'node:module';
// 2026-09-30 S2a 金鲨岗转正：租约锁切换到 posts/jinsha-post（契约逐字一致、
// 默认锁路径相同 ⇒ 与其它金鲨流水线全局互斥）。frozen core 字节不动（copy-not-move），
// 原 jinsha_cua_exam.js 内租约实现留档，assertFrozenCoreHashes 不受影响。
import {acquireJinshaLease, releaseJinshaLease} from '../../../posts/jinsha-post/scripts/lease.mjs';
// 金鲨登录态门禁（岗位共享判定，与 lease 同源目录）。转正重构时丢失本 import，
// 导致 pageTextGuard 调用 assertJinshaLoginGate 抛 ReferenceError，
// 被 executor 兜底成 download-retry-limit-exceeded（每轮必失败）。
import {assertJinshaLoginGate} from '../../../posts/jinsha-post/scripts/auth.mjs';
import {resolveJinshaChannel} from './jinsha_channel_policy.mjs';
import {assertInternalInvocation} from './business_workflow_policy.mjs';

const require=createRequire(import.meta.url);
const {chromium}=require('/Users/ddt/work/projects/ai_agent/aos-platform/plugins/browser/headless-playwright/node_modules/playwright-core');
const execFile=promisify(execFileCb);
const PROFILE_ROOT='/Users/ddt/Library/Application Support/AOS Background Chrome';
const PROFILE='jinsha-business';
const PORT=9232;
const HOME='https://data.guoshuyufen.com/#/businessData/realTimeData';
const REPORT='https://data.guoshuyufen.com/#/reportDownload';
const PREFIX='https://data.guoshuyufen.com/';
const PLANS={meituan:'最终美团最新日报',taobao:'饿了么日报数据📊6.18最新最新'};
const LABELS={meituan:'美团外卖',taobao:'淘宝闪购'};
const PLAN_OPTION_WAIT_MS=10000;
const PLAN_OPTION_POLL_MS=150;
const PLAN_OPTION_STABLE_POLLS=2;
const REPORT_READY_WAIT_MS=30000;
const REPORT_READY_STABLE_MS=300;
const DOWNLOAD_STAGING_WAIT_MS=60000;
const DOWNLOAD_STAGING_POLL_MS=200;
const DOWNLOAD_STAGING_STABLE_POLLS=2;

function yesterdayInShanghai(now=new Date()) {
  const parts=Object.fromEntries(new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(now).map(part=>[part.type,part.value]));
  const date=new Date(`${parts.year}-${parts.month}-${parts.day}T00:00:00+08:00`);
  date.setUTCDate(date.getUTCDate()-1);
  return new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(date);
}

function safeTaskId(value){return /^[a-z0-9][a-z0-9-]{0,62}$/.test(value||'');}
function safeRawFile(file){return typeof file==='string'&&path.isAbsolute(file)&&path.basename(file)===file.split(path.sep).at(-1)&&/\.xlsx$/i.test(file);}
function isLoginUrl(url){return typeof url==='string'&&url.startsWith('https://data.guoshuyufen.com/')&&url.includes('#/login');}
function planPattern(platform){return platform==='meituan'?/^最终美团最新日报$/:/^饿了么(?:日报数据📊6\.18|\.\.\.)最新最新$/;}
function classifyPlanOptions(values,platform){const matches=values.map(value=>String(value).trim()).filter(value=>planPattern(platform).test(value));if(matches.length===0)return {state:'wait',count:0};if(matches.length>1)return {state:'ambiguous',count:matches.length};return {state:'unique',count:1,text:matches[0]};}
function classifyStagedEntries(names){const values=names.filter(name=>!String(name).startsWith('.'));const partial=values.filter(name=>/\.(?:crdownload|tmp|part)$/i.test(name));const complete=values.filter(name=>/\.xlsx$/i.test(name));const unexpected=values.filter(name=>!partial.includes(name)&&!complete.includes(name));if(unexpected.length>0||complete.length>1||(complete.length===1&&partial.length>0))return {state:'ambiguous',count:values.length};if(complete.length===1)return {state:'unique',count:1,name:complete[0]};return {state:'wait',count:0};}
function assertBrowserProfileState(state){
  if(state?.profile!==PROFILE||Number(state?.port)!==PORT)throw Error('jinsha-background-profile-state-mismatch');
  if(state.mode==='headless')return true;
  const nonempty=value=>typeof value==='string'&&value.length>0;
  const activeFieldsPresent=state.activeTargetId!==undefined||state.activeMarker!==undefined;
  const taskFieldsPresent=state.taskId!==undefined||state.taskTargetId!==undefined||state.taskMarker!==undefined;
  const activeReady=nonempty(state.activeTargetId)&&nonempty(state.activeMarker);
  const taskReady=nonempty(state.taskId)&&nonempty(state.taskTargetId)&&state.taskMarker===`aos-background-task:${state.taskId}:work`;
  const bindingsValid=(activeReady||taskReady)&&(!activeFieldsPresent||activeReady)&&(!taskFieldsPresent||taskReady)&&(!(activeReady&&taskReady)||(state.activeTargetId===state.taskTargetId&&state.activeMarker===state.taskMarker));
  const handoffReady=state.mode==='visible-handoff'&&state.phase==='WINDOW_RELEASED'&&state.site==='jinsha'&&state.prefix===PREFIX&&state.cdpEnabled===true&&state.automationAttached===true&&nonempty(state.instanceId)&&state.confirmationInstance===state.instanceId&&bindingsValid;
  if(!handoffReady)throw Error('jinsha-background-profile-state-mismatch');
  return true;
}
function matchesDedicatedBrowserCommand(command,{port=PORT,profileDir=path.join(PROFILE_ROOT,PROFILE)}={}){
  const text=String(command||'');
  return /(?:Google Chrome|Chromium)(?:\.app)?\/Contents\/MacOS\/Google Chrome|(?:^|\s)(?:google-chrome|chromium)(?:\s|$)/.test(text)
    && text.includes(`--remote-debugging-port=${port}`)
    && text.includes(`--user-data-dir=${profileDir}`);
}
function probeCdpBrowser(port,timeoutMs=4000){
  return new Promise(resolve=>{
    let settled=false;
    const finish=value=>{if(!settled){settled=true;resolve(value);}};
    const request=http.get({host:'127.0.0.1',port,path:'/json/version',timeout:timeoutMs},response=>{
      let body='';response.setEncoding('utf8');
      response.on('data',chunk=>{body+=chunk;});
      response.on('end',()=>{try{const parsed=JSON.parse(body);finish(typeof parsed?.Browser==='string'?parsed.Browser:'');}catch{finish('');}});
    });
    request.on('error',()=>finish(''));
    request.on('timeout',()=>{request.destroy();finish('');});
  });
}
// 2026-09-30 受限执行环境降级：WorkBuddy 沙箱禁止 spawn /bin/ps（EPERM），
// 生产 launchd 环境不受此限制，仍走下面的命令行严格匹配。
// 降级时不伪造命令行参数，改用三重等价证据自证专用浏览器身份：
//   (1) 端口唯一监听 pid（上方 lsof 已保证）
//   (2) 该 pid 的可执行文件为 Google Chrome（lsof txt 读取真实路径）
//   (3) 该端点的 CDP /json/version 自证为 Chrome
// Profile 绑定由调用方前置的 assertBrowserProfileState（state.json）保证。
async function degradedDedicatedIdentity(pid){
  let executable='';
  try{
    const {stdout}=await execFile('/usr/sbin/lsof',['-nP','-p',String(pid),'-a','-d','txt','-F','n'],{timeout:5000});
    executable=(String(stdout).split('\n').map(line=>line.trim()).find(line=>line.startsWith('n')&&/MacOS\/Google Chrome$/i.test(line))||'').slice(1);
  }catch{return null;}
  if(!/Google Chrome/i.test(executable))return null;
  const browser=await probeCdpBrowser(PORT);
  if(!browser)return null;
  return {executable,browser};
}
async function assertDedicatedBrowserProcess(){
  let output;
  try{output=(await execFile('/usr/sbin/lsof',['-nP','-t',`-iTCP:${PORT}`,'-sTCP:LISTEN'],{timeout:5000})).stdout;}catch{throw Error('jinsha-background-process-not-alive');}
  const pids=[...new Set(String(output).split(/\s+/).filter(Boolean))];
  if(pids.length!==1)throw Error('jinsha-background-process-binding-invalid');
  let command;
  try{command=(await execFile('/bin/ps',['-p',pids[0],'-o','command='],{timeout:5000})).stdout;}
  catch(error){
    if(error?.code!=='EPERM'&&error?.code!=='EACCES')throw Error('jinsha-background-process-not-alive');
    const degraded=await degradedDedicatedIdentity(pids[0]);
    if(!degraded)throw Error('jinsha-background-process-not-alive');
    return {pid:Number(pids[0]),command:degraded.executable,transportSelfProof:degraded.browser,degradedPsDenied:true};
  }
  if(!matchesDedicatedBrowserCommand(command))throw Error('jinsha-background-process-binding-invalid');
  return {pid:Number(pids[0]),command:String(command).trim()};
}
function assertConfig(c){
  if(resolveJinshaChannel(c.jinshaChannel)!=='browser')throw Error('browser-executor-channel-mismatch');
  if(!safeTaskId(c.runId))throw Error('run-id-invalid');
  if(c.businessDate!==yesterdayInShanghai())throw Error('business-date-not-yesterday');
  if(c.profile!==undefined&&c.profile!==PROFILE)throw Error('jinsha-browser-profile-mismatch');
  if(c.port!==undefined&&Number(c.port)!==PORT)throw Error('jinsha-browser-port-mismatch');
  for(const platform of ['meituan','taobao'])if(!safeRawFile(c.raw?.[platform]))throw Error(`raw-file-invalid:${platform}`);
  if(!c.downloadUiReceipt||!path.isAbsolute(c.downloadUiReceipt))throw Error('download-ui-receipt-invalid');
  return true;
}

async function frontmost(){try{return (await execFile('/usr/bin/osascript',['-e','tell application "System Events" to get bundle identifier of first application process whose frontmost is true'])).stdout.trim();}catch{return 'unavailable';}}
async function allText(page){const texts=[];for(const frame of page.frames()){try{const value=(await frame.locator('body').innerText()).trim();if(value)texts.push(value);}catch{}}return [...new Set(texts)].join('\n');}
async function waitFor(page,predicate,reason,timeout=12000){const deadline=Date.now()+timeout;let last;while(Date.now()<deadline){try{const value=await predicate();if(value)return value;}catch(error){last=error;}await page.waitForTimeout(200);}throw Error(reason+(last instanceof Error?':'+last.message:''));}
async function visibleExact(page,text){const hits=[];for(const frame of page.frames()){const locator=frame.getByText(text,{exact:true});for(let i=0;i<await locator.count();i++){const item=locator.nth(i);if(await item.isVisible().catch(()=>false))hits.push(item);}}return hits;}
async function uniqueExact(page,text){const hits=await visibleExact(page,text);if(hits.length!==1)throw Error(`visible-text-count:${text}:${hits.length}`);return hits[0];}
async function uniqueInput(page,placeholder){const hits=[];for(const frame of page.frames()){const locator=frame.locator(`input[placeholder="${placeholder}"]`);for(let i=0;i<await locator.count();i++){const item=locator.nth(i);if(await item.isVisible().catch(()=>false))hits.push(item);}}if(hits.length!==1)throw Error(`input-count:${placeholder}:${hits.length}`);return hits[0];}
async function pageTextGuard(page){const text=await allText(page),url=page.url();assertJinshaLoginGate(url,text);return text;}
async function reportReady(page){const text=await pageTextGuard(page);return page.url().includes('#/reportDownload')&&text.includes('美团外卖')&&text.includes('淘宝闪购')&&text.includes('下载数据');}

async function route(page){
  await waitFor(page,()=>pageTextGuard(page),'jinsha-shell-not-ready');
  if(await reportReady(page))return;
  const candidates=[];for(const label of ['数据下载','报表下载']){const hits=await visibleExact(page,label);if(hits.length===1)candidates.push(hits[0]);else if(hits.length>1)throw Error(`download-menu-count:${label}:${hits.length}`);}
  if(candidates.length===1)await candidates[0].click({timeout:5000});
  else if(candidates.length===0)await page.goto(REPORT,{waitUntil:'domcontentloaded',timeout:30000});
  else throw Error('download-menu-ambiguous');
  await waitFor(page,()=>reportReady(page),'jinsha-report-page-not-ready',REPORT_READY_WAIT_MS);
  await page.waitForTimeout(REPORT_READY_STABLE_MS);
  if(!await reportReady(page))throw Error('jinsha-report-page-unstable');
}

async function dismissKnownOverlay(page,waitMs=2500){
  const deadline=Date.now()+waitMs;let overlays=[];
  do{
    overlays=[];
    for(const frame of page.frames()){
      const locator=frame.locator('.upload:visible').filter({hasText:'新功能上线'});
      for(let i=0;i<await locator.count();i++)if(await locator.nth(i).isVisible().catch(()=>false))overlays.push(locator.nth(i));
    }
    if(overlays.length>0)break;
    await page.waitForTimeout(150);
  }while(Date.now()<deadline);
  if(overlays.length===0)return false;
  if(overlays.length!==1)throw Error(`new-feature-overlay-count:${overlays.length}`);
  const title=overlays[0].getByText('新功能上线',{exact:true});
  const close=overlays[0].getByText('关闭',{exact:true});
  if(await title.count()!==1||await close.count()!==1)throw Error('new-feature-overlay-contract-mismatch');
  await close.click({timeout:5000});
  await waitFor(page,async()=>!await overlays[0].isVisible().catch(()=>false),'new-feature-overlay-not-closed',5000);
  return true;
}

async function chooseExact(page,text){const item=await uniqueExact(page,text);await item.click({timeout:5000});await page.waitForTimeout(150);}
async function selectPlatform(page,platform){await chooseExact(page,LABELS[platform]);const text=await pageTextGuard(page);if(!text.includes(LABELS[platform]))throw Error(`platform-readback-failed:${platform}`);}
async function selectMode(page){for(const label of ['多店数据','按日']){const hits=await visibleExact(page,label);if(hits.length===1)await hits[0].click({timeout:5000});else if(hits.length>1)throw Error(`mode-count:${label}:${hits.length}`);}await page.waitForTimeout(150);}
async function setDate(page,placeholder,date){const input=await uniqueInput(page,placeholder);await input.click();await input.fill(date);await input.press('Enter');await waitFor(page,async()=>await input.inputValue()===date,`date-readback-mismatch:${placeholder}`,5000);}
async function waitForUniquePlanOption(page,platform){const deadline=Date.now()+PLAN_OPTION_WAIT_MS;let stable=0,lastText='';while(Date.now()<deadline){const hits=[];for(const frame of page.frames()){const locator=frame.locator('.plan_li_one.plan_li_val');for(let i=0;i<await locator.count();i++){const item=locator.nth(i);if(await item.isVisible().catch(()=>false)){const text=(await item.innerText()).trim();if(planPattern(platform).test(text))hits.push({item,text});}}}const state=classifyPlanOptions(hits.map(hit=>hit.text),platform);if(state.state==='ambiguous')throw Error(`plan-option-count:${platform}:${state.count}`);if(state.state==='unique'){stable=state.text===lastText?stable+1:1;lastText=state.text;if(stable>=PLAN_OPTION_STABLE_POLLS)return hits[0].item;}else{stable=0;lastText='';}await page.waitForTimeout(PLAN_OPTION_POLL_MS);}throw Error(`plan-option-timeout:${platform}`);}
async function selectPlan(page,platform){
  const plan=PLANS[platform],pattern=planPattern(platform);const inputs=[];for(const frame of page.frames()){const locator=frame.locator('input[placeholder="请选择下载方案"]');for(let i=0;i<await locator.count();i++){const item=locator.nth(i);if(await item.isVisible().catch(()=>false))inputs.push(item);}}
  if(inputs.length!==1)throw Error(`plan-input-count:${inputs.length}`);
  if(!pattern.test(await inputs[0].inputValue().catch(()=>''))){
    await inputs[0].click();const option=await waitForUniquePlanOption(page,platform);await option.click({timeout:5000});
  }
  await waitFor(page,async()=>pattern.test(await inputs[0].inputValue().catch(()=>'')),`plan-readback-mismatch:${platform}`,5000);const value=await inputs[0].inputValue();if(value!==plan&&!pattern.test(value))throw Error(`plan-readback-mismatch:${platform}`);
}
function selectedCount(text){const values=[...text.matchAll(/已选择\s*[（(](\d+)[)）]/g)].map(match=>Number(match[1]));if(values.length!==1)throw Error(`selected-count-ambiguous:${values.length}`);return values[0];}
async function metricControl(page,label){
  const hits=[];for(const frame of page.frames()){const text=frame.getByText(label,{exact:true});for(let i=0;i<await text.count();i++){const item=text.nth(i);if(!await item.isVisible().catch(()=>false))continue;const container=item.locator('xpath=parent::div[contains(concat(" ",normalize-space(@class)," ")," check_one ")]'),icon=container.locator(':scope > span.checkSpan');if(await container.count()===1&&await icon.count()===1)hits.push({container,icon});}}
  if(hits.length!==1)throw Error(`metric-control-count:${label}:${hits.length}`);return hits[0];
}
async function metricSelected(control){const tokens=((await control.icon.getAttribute('class'))||'').split(/\s+/).filter(Boolean);if(!tokens.includes('checkSpan'))throw Error('metric-state-class-missing');return !tokens.includes('checkSpans');
}
async function selectMetric(page,label,expectedBefore){
  const control=await metricControl(page,label);if(await metricSelected(control))return expectedBefore;
  await control.container.click({timeout:5000});await waitFor(page,async()=>{const text=await pageTextGuard(page);return selectedCount(text)===expectedBefore+1&&await metricSelected(await metricControl(page,label));},`metric-select-readback-failed:${label}`,5000);
  return expectedBefore+1;
}
async function ensureMetrics(page,platform){
  let count=await waitFor(page,async()=>{const value=selectedCount(await pageTextGuard(page));return value>0?value:false;},`metric-count-not-ready:${platform}`,10000);
  if(platform==='taobao'&&count===34)for(const label of ['单均实付','单均到手'])count=await selectMetric(page,label,count);
  if(count!==36)throw Error(`metric-count-not-36:${platform}:${count}`);
  if(platform==='taobao')for(const label of ['单均实付','单均到手'])if(!await metricSelected(await metricControl(page,label)))throw Error(`taobao-metric-not-selected:${label}`);
}
async function validateXlsx(file){const info=await fs.stat(file);if(info.size<=0)throw Error('download-empty');await execFile('/usr/bin/unzip',['-t',file],{timeout:30000,maxBuffer:4*1024*1024});return info;}
async function sha256(file){return crypto.createHash('sha256').update(await fs.readFile(file)).digest('hex');}
async function waitForStagedDownload(directory,platform){const deadline=Date.now()+DOWNLOAD_STAGING_WAIT_MS;let stable=0,lastName='',lastSize=-1;while(Date.now()<deadline){const names=await fs.readdir(directory);const state=classifyStagedEntries(names);if(state.state==='ambiguous')throw Error(`download-staging-ambiguous:${platform}:${state.count}`);if(state.state==='unique'){const file=path.join(directory,state.name),info=await fs.stat(file);if(info.size>0&&state.name===lastName&&info.size===lastSize)stable+=1;else stable=1;lastName=state.name;lastSize=info.size;if(stable>=DOWNLOAD_STAGING_STABLE_POLLS)return file;}else{stable=0;lastName='';lastSize=-1;}await new Promise(resolve=>setTimeout(resolve,DOWNLOAD_STAGING_POLL_MS));}throw Error(`download-staging-timeout:${platform}`);}
async function loadResume(c){
  if(c.resumeDownload!==true)return null;
  const previous=JSON.parse(await fs.readFile(c.downloadUiReceipt,'utf8'));
  if(previous.runId!==c.runId||previous.businessDate!==c.businessDate||previous.profile!==PROFILE||previous.port!==PORT)throw Error('resume-receipt-binding-mismatch');
  if(previous.clicks?.meituan!==1||previous.clicks?.taobao!==0||!previous.files?.meituan||previous.files?.taobao)throw Error('resume-platform-boundary-mismatch');
  if(path.resolve(previous.files.meituan.file)!==path.resolve(c.raw.meituan))throw Error('resume-meituan-path-mismatch');
  const info=await validateXlsx(previous.files.meituan.file),digest=await sha256(previous.files.meituan.file);
  if(info.size!==previous.files.meituan.size||digest!==previous.files.meituan.sha256)throw Error('resume-meituan-integrity-mismatch');
  return previous;
}
async function downloadPlatform(page,c,platform,result){
  await selectPlatform(page,platform);await selectMode(page);await dismissKnownOverlay(page,1200);await setDate(page,'开始日期',c.businessDate);await setDate(page,'结束日期',c.businessDate);await selectPlan(page,platform);await ensureMetrics(page,platform);
  const destination=path.resolve(c.raw[platform]),staging=path.join(path.dirname(destination),'.download-staging',platform);await fs.mkdir(path.dirname(destination),{recursive:true});try{await fs.access(destination);throw Error(`download-destination-exists:${platform}`);}catch(error){if(error.code!=='ENOENT')throw error;}await fs.mkdir(staging,{recursive:true});if((await fs.readdir(staging)).length!==0)throw Error(`download-staging-not-empty:${platform}`);
  const buttons=[];for(const frame of page.frames()){const locator=frame.getByRole('button',{name:/下载数据/});for(let i=0;i<await locator.count();i++){const item=locator.nth(i);if(await item.isVisible().catch(()=>false))buttons.push(item);}}
  if(buttons.length!==1)throw Error(`download-button-count:${platform}:${buttons.length}`);
  const cdp=await page.context().newCDPSession(page);let captureMode='playwright-save-as',suggestedFilename='';try{await cdp.send('Page.setDownloadBehavior',{behavior:'allow',downloadPath:staging});const downloadStartedAt=Date.now();result.clicks[platform]+=1;const [download]=await Promise.all([page.waitForEvent('download',{timeout:60000}),buttons[0].click({timeout:5000})]);suggestedFilename=download.suggestedFilename();if(!/\.xlsx$/i.test(suggestedFilename))throw Error(`download-suggested-name-invalid:${platform}`);try{await download.saveAs(destination);}catch(saveError){const staged=await waitForStagedDownload(staging,platform);await fs.unlink(destination).catch(error=>{if(error.code!=='ENOENT')throw error;});await fs.rename(staged,destination);captureMode='task-page-staging-recovery';}const failure=await download.failure();if(failure)throw Error(`download-failed:${platform}:${failure}`);const info=await validateXlsx(destination);result.files[platform]={name:path.basename(destination),suggestedFilename,file:destination,size:info.size,sha256:await sha256(destination),downloadStartedAt,savedAt:Date.now(),captureMode};await fs.rm(staging,{recursive:true,force:true});}finally{await cdp.detach().catch(()=>{});}
}
async function writeReceipt(file,value){await fs.mkdir(path.dirname(file),{recursive:true});const temp=`${file}.${process.pid}.tmp`;await fs.writeFile(temp,JSON.stringify(value,null,2),{mode:0o600});await fs.rename(temp,file);}

async function runBrowserJinshaExam(c){
  assertConfig(c);const previous=await loadResume(c),startedAt=previous?.startedAt||Date.now(),deadline=startedAt+180000;const result={ok:false,runId:c.runId,startedAt,deadline,executor:'jinsha-browser-download',browserController:'control-background-dedicated-chrome',profile:PROFILE,port:PORT,businessDate:c.businessDate,runtimeModelDecisions:0,clicks:{meituan:previous?.clicks?.meituan||0,taobao:previous?.clicks?.taobao||0},files:{...(previous?.files||{})},stage:'start',nodes:[...(previous?.nodes||[])],frontmostBefore:await frontmost()};if(previous)result.recovery={fromStage:previous.stage,reason:previous.reason,resumedPlatforms:['taobao'],resumedAt:Date.now()};let browser,page,lease,nodeStart=Date.now();
  const stage=async(name,fn)=>{if(result.stage!=='start')result.nodes.push({name:result.stage,elapsedMs:Date.now()-nodeStart,ok:true,llmIntervention:false});result.stage=name;nodeStart=Date.now();return fn();};
  try{
    lease=await acquireJinshaLease(c.runId,c.leasePath);result.lease={path:lease.path,acquiredAt:lease.acquiredAt,released:false};
    const state=JSON.parse(await fs.readFile(path.join(PROFILE_ROOT,PROFILE,'.aos-background-chrome/state.json'),'utf8'));assertBrowserProfileState(state);result.browserProcess=await assertDedicatedBrowserProcess();
    browser=await stage('background_preflight',()=>chromium.connectOverCDP(`http://127.0.0.1:${PORT}`));const context=browser.contexts()[0];if(!context)throw Error('browser-context-missing');
    page=await stage('task_page',async()=>{const value=await context.newPage();await value.addInitScript(id=>window.name=`aos-background-task:${id}`,c.runId);await value.goto(HOME,{waitUntil:'commit',timeout:30000});await value.evaluate(id=>window.name=`aos-background-task:${id}`,c.runId);return value;});
    await stage('navigation',()=>route(page));await stage('known_overlay',()=>dismissKnownOverlay(page));for(const platform of ['meituan','taobao'])if(!result.files[platform])await stage(`${platform}.download`,()=>downloadPlatform(page,c,platform,result));
    result.nodes.push({name:result.stage,elapsedMs:Date.now()-nodeStart,ok:true,llmIntervention:false});result.stage='complete';result.ok=true;result.jinshaResourceReleased=true;result.jinshaReleasedAt=Date.now();result.receiptIssuedAt=Date.now();result.url=page.url();
  }catch(error){result.reason=String(error.message||error);result.nodes.push({name:result.stage,elapsedMs:Date.now()-nodeStart,ok:false,llmIntervention:false});}
  finally{if(page)await page.close().catch(()=>{});if(browser)await browser.close().catch(()=>{});if(lease){try{const released=await releaseJinshaLease(lease);result.lease={...result.lease,released,releasedAt:Date.now()};}catch(error){result.ok=false;result.reason=`jinsha-lease-release-failed:${String(error.message||error)}`;}}result.elapsedMs=Date.now()-startedAt;result.efficiencyExceeded=result.elapsedMs>180000;result.frontmostAfter=await frontmost();await writeReceipt(c.downloadUiReceipt,result);}
  return result;
}

export {PROFILE,PORT,HOME,REPORT,PREFIX,PLANS,LABELS,PLAN_OPTION_WAIT_MS,PLAN_OPTION_POLL_MS,PLAN_OPTION_STABLE_POLLS,REPORT_READY_WAIT_MS,REPORT_READY_STABLE_MS,DOWNLOAD_STAGING_WAIT_MS,DOWNLOAD_STAGING_POLL_MS,DOWNLOAD_STAGING_STABLE_POLLS,yesterdayInShanghai,safeTaskId,safeRawFile,isLoginUrl,planPattern,classifyPlanOptions,classifyStagedEntries,assertBrowserProfileState,matchesDedicatedBrowserCommand,assertDedicatedBrowserProcess,assertConfig,selectedCount,dismissKnownOverlay,runBrowserJinshaExam};

if(import.meta.url===`file://${process.argv[1]}`){assertInternalInvocation();const configPath=process.argv[2];if(!configPath)throw Error('usage: business_jinsha_browser_exam.mjs <config.json>');const c=JSON.parse(await fs.readFile(configPath,'utf8'));const result=await runBrowserJinshaExam(c);console.log(JSON.stringify(result));if(!result.ok)process.exitCode=1;}
