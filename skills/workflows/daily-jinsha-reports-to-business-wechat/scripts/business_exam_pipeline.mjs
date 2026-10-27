import fs from 'node:fs/promises';
import crypto from 'node:crypto';
import path from 'node:path';
import { constants } from 'node:fs';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { runBuildReports } from '../../../.daily-jinsha-reports-core/scripts/build_reports.mjs';
import { assertJinshaReleased } from '../../../.daily-jinsha-reports-core/scripts/download_receipt_contract.mjs';
import { mayFallbackFromWecom, resolveWechatChannel } from './wechat_channel_policy.mjs';
import { resolveJinshaChannel } from './jinsha_channel_policy.mjs';
import { runBrowserJinshaExam } from './business_jinsha_browser_exam.mjs';
import { FIXED, assertFrozenCoreHashes, assertInternalInvocation, assertProductionConfig, assertStagePermission } from './business_workflow_policy.mjs';

const exec = promisify(execFile);
const EXPECTED_GROUP = '上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰';
const EXPECTED_AUTHORIZATION = 'zhensi-business-main-wechat-shanghai-zhensi-operations-ding-fandang-daily-v2-reauthorized-20260917';
const EXPECTED_WECOM_ENTERPRISE = '上海臻肆文化传播有限公司';
const EXPECTED_WECOM_SPACE = '金鲨昨日双平台日报业务群';
const EXPECTED_WECOM_AUTHORIZATION = 'zhensi-business-wecom-jinsha-daily-v1';
const [configPath, mode] = process.argv.slice(2);

assertInternalInvocation();
if (!configPath || !['--download', '--prepare', '--send', '--verify-only'].includes(mode)) {
  throw Error('usage: business_exam_pipeline.mjs <config.json> --download|--prepare|--send|--verify-only');
}

const c = JSON.parse(await fs.readFile(configPath, 'utf8'));
assertProductionConfig(c,configPath);
await assertFrozenCoreHashes();
const workflowState=JSON.parse(await fs.readFile(c.workflowState,'utf8'));
if(workflowState.runId!==c.runId||workflowState.businessDate!==c.businessDate||workflowState.runtimeModelDecisions!==0)throw Error('workflow-state-binding-mismatch');
assertStagePermission(workflowState.phase,mode);
const requestedWechatChannel = resolveWechatChannel(c.wechatChannel);
const group = c.group ?? EXPECTED_GROUP;
const authorization = c.authorization ?? EXPECTED_AUTHORIZATION;
const wecomEnterprise = c.wecomEnterprise ?? EXPECTED_WECOM_ENTERPRISE;
const wecomSpace = c.wecomSpace ?? EXPECTED_WECOM_SPACE;
const wecomAuthorization = c.wecomAuthorization ?? EXPECTED_WECOM_AUTHORIZATION;
if (['auto','desktop','mobile'].includes(requestedWechatChannel) && group !== EXPECTED_GROUP) throw Error('target-group-mismatch');
if (['auto','desktop','mobile'].includes(requestedWechatChannel) && authorization !== EXPECTED_AUTHORIZATION) throw Error('standing-authorization-missing');
if (['auto','wecom'].includes(requestedWechatChannel) && wecomEnterprise !== EXPECTED_WECOM_ENTERPRISE) throw Error('wecom-enterprise-mismatch');
if (['auto','wecom'].includes(requestedWechatChannel) && wecomSpace !== EXPECTED_WECOM_SPACE) throw Error('wecom-space-mismatch');
if (['auto','wecom'].includes(requestedWechatChannel) && wecomAuthorization !== EXPECTED_WECOM_AUTHORIZATION) throw Error('wecom-standing-authorization-missing');
if (!c.runId || !c.businessDate) throw Error('run-binding-missing');

const sha256 = async file => crypto.createHash('sha256').update(await fs.readFile(file)).digest('hex');
const safeBusinessName = name => (
  typeof name === 'string' &&
  path.basename(name) === name &&
  name.endsWith('.xlsx') &&
  !/[\\/]/.test(name) &&
  !/(测试|考核)/.test(name)
);

async function download() {
  const channel=resolveJinshaChannel(c.jinshaChannel);
  if(channel==='desktop')throw Error('desktop-jinsha-requires-cua-session');
  const result=await runBrowserJinshaExam(c);
  console.log(JSON.stringify(result));
  if(!result.ok)process.exitCode=1;
}

async function prepare() {
  const downloadUi = JSON.parse(await fs.readFile(c.downloadUiReceipt, 'utf8'));
  if (downloadUi.runId !== c.runId || downloadUi.ok !== true) throw Error('download-receipt-binding-mismatch');
  assertJinshaReleased(downloadUi);
  const startedAt = Number(downloadUi.startedAt);
  const deadline = startedAt + 180000;
  const result = {ok:false, runId:c.runId, groupName:group, startedAt, deadline, stage:'downloads', nodes:[], desktop:downloadUi};
  try {
    const d = {ok:true, executor:'jinsha-download', businessDate:c.businessDate, clickAttempts:{meituan:1,taobao:1}};
    for (const platform of ['meituan','taobao']) {
      const file = c.raw[platform];
      const info = await fs.stat(file);
      const downloadStartedAt = Number(
        downloadUi.files?.[platform]?.downloadStartedAt ??
        downloadUi.files?.[platform]?.savedAt ??
        startedAt
      );
      if (!Number.isFinite(downloadStartedAt) || info.mtimeMs < downloadStartedAt - 2000 || info.size === 0) throw Error('not-new-download:'+platform);
      await exec('/usr/bin/unzip',['-t',file],{timeout:30000,maxBuffer:4*1024*1024});
      d[platform] = {file,size:info.size,sha256:await sha256(file)};
    }
    await fs.mkdir(path.dirname(c.downloadReceipt), {recursive:true});
    await fs.writeFile(c.downloadReceipt, JSON.stringify(d,null,2));
    result.stage='build';
    const buildStart=Date.now();
    let build=await runBuildReports({receipt:c.downloadReceipt,buildReceipt:c.buildReceipt,outputDir:c.outputDir,customer:path.join(FIXED.outputRoot,'客户表最新.xlsx'),meituanReference:path.join(FIXED.outputRoot,'美团全部_2026-08-25至2026-08-25.xlsx'),taobaoTemplate:path.join(FIXED.outputRoot,'淘宝闪购_模版2026-08-24至2026-08-24.xlsx'),filenameSuffix:'',titleSuffix:''});
    result.nodes.push({name:'build',startedAt:buildStart,finishedAt:Date.now(),elapsedMs:Date.now()-buildStart,ok:true,llmIntervention:false});
    for (const platform of ['meituan','taobao']) {
      const name=c.sendNames?.[platform];
      if (!safeBusinessName(name)) throw Error('unsafe-business-send-name:'+platform);
      const item=build.files[platform];
      const destination=path.join(c.outputDir,name);
      if(destination!==item.file) await fs.copyFile(item.file,destination,constants.COPYFILE_EXCL);
      item.file=destination;
      item.name=name;
      item.size=(await fs.stat(destination)).size;
      item.sha256=await sha256(destination);
    }
    await fs.writeFile(c.buildReceipt,JSON.stringify(build,null,2));
    const files=Object.fromEntries(await Promise.all(['meituan','taobao'].map(async platform=>{
      const item=build.files[platform];
      return [platform,{name:item.name,path:item.file,size:item.size,sha256:item.sha256}];
    })));
    const preflight={ok:true,runId:c.runId,groupName:group,businessDate:c.businessDate,authorization,
      requestedWechatChannel,wecomEnterprise,wecomSpace,wecomAuthorization,files,preparedAt:Date.now()};
    await fs.writeFile(c.preflightReceipt,JSON.stringify(preflight,null,2));
    result.ok=true;
    result.stage='prepared';
    result.preflight=preflight;
  } catch(error) {
    result.reason=String(error.message||error);
  } finally {
    result.elapsedMs=Date.now()-startedAt;
    result.businessCompleted=false;
    result.efficiencyStatus=result.elapsedMs>180000?'效率未达标':'尚未完成';
    await fs.writeFile(c.examReceipt,JSON.stringify(result,null,2));
    console.log(JSON.stringify(result));
  }
  if(!result.ok) process.exitCode=1;
}

async function validatePrepared() {
  const p=JSON.parse(await fs.readFile(c.preflightReceipt,'utf8'));
  if(!p.ok || p.runId!==c.runId || p.requestedWechatChannel!==requestedWechatChannel) throw Error('preflight-binding-mismatch');
  if(['auto','desktop','mobile'].includes(requestedWechatChannel) && (p.groupName!==EXPECTED_GROUP || p.authorization!==EXPECTED_AUTHORIZATION)) throw Error('preflight-wechat-binding-mismatch');
  if(['auto','wecom'].includes(requestedWechatChannel) && (p.wecomEnterprise!==EXPECTED_WECOM_ENTERPRISE || p.wecomSpace!==EXPECTED_WECOM_SPACE || p.wecomAuthorization!==EXPECTED_WECOM_AUTHORIZATION)) throw Error('preflight-wecom-binding-mismatch');
  const build=JSON.parse(await fs.readFile(c.buildReceipt,'utf8'));
  for(const platform of ['meituan','taobao']) {
    const expected=p.files[platform];
    const item=build.files[platform];
    if(!expected || !item || item.file!==expected.path || item.name!==expected.name) throw Error('build-preflight-file-mismatch:'+platform);
    if(!safeBusinessName(item.name) || await sha256(item.file)!==expected.sha256 || (await fs.stat(item.file)).size!==expected.size) throw Error('prepared-file-integrity-mismatch:'+platform);
  }
  return p;
}

async function send(verifyOnly=false) {
  const p=await validatePrepared();
  const previous=JSON.parse(await fs.readFile(c.examReceipt,'utf8'));
  // A resumed send must receive a fresh bounded authorization window. The
  // original download start may be hours old after maintenance/review.
  const startedAt=Date.now();
  const deadline=startedAt+180000;
  let channel=requestedWechatChannel;
  const selectionStarted=Date.now();
  let selection={requestedChannel:requestedWechatChannel,selectedChannel:requestedWechatChannel,reason:'explicit-channel'};
  const wecomSender=c.wecomSender||path.join(path.dirname(new URL(import.meta.url).pathname),'business_wecom_shared_space_sender.py');
  const result={...previous,ok:false,startedAt,deadline,stage:'delivery-channel-selection',preflight:p,deliverySelection:selection};
  let nodeStart=selectionStarted;
  try {
    if(verifyOnly && previous.wechatChannel) {
      channel=previous.wechatChannel;
      selection={requestedChannel:requestedWechatChannel,selectedChannel:channel,reason:'verify-pinned-to-send-channel'};
    } else if(channel==='auto') {
      const wecomPreflightReceipt=c.wecomPreflightReceipt||`${c.sendReceipt}.wecom-preflight.json`;
      const preflightArgs=[wecomSender,'--build-receipt',c.buildReceipt,'--send-receipt',wecomPreflightReceipt,
        '--enterprise',wecomEnterprise,'--space',wecomSpace,'--preflight-only','--keep-work'];
      const checked=await exec(c.python,preflightArgs,{maxBuffer:4*1024*1024}).then(value=>({ok:true,value})).catch(error=>({ok:false,error}));
      let receipt={};
      try { receipt=JSON.parse((checked.ok?checked.value.stdout:checked.error.stdout||'').trim().split('\n').at(-1)); } catch {}
      if(checked.ok && receipt.ok) {
        channel='wecom';selection={requestedChannel:'auto',selectedChannel:'wecom',reason:'wecom-preflight-passed',wecomPreflight:receipt};
      } else if(mayFallbackFromWecom(receipt.reason)) {
        channel='desktop';selection={requestedChannel:'auto',selectedChannel:'desktop',reason:receipt.reason,wecomPreflight:receipt};
      } else {
        throw Error(receipt.reason||'wecom-preflight-unknown');
      }
    }
    result.deliverySelection=selection;
    result.stage=verifyOnly?`${channel}-verify`:channel;
    nodeStart=Date.now();
    const selectedSender=channel==='wecom'?wecomSender:(channel==='desktop'?(c.desktopSender||path.join(path.dirname(new URL(import.meta.url).pathname),'business_desktop_wechat_file_sender.py')):c.sender);
    const args=[selectedSender,'--build-receipt',c.buildReceipt,'--send-receipt',verifyOnly?c.verifyReceipt:c.sendReceipt,'--keep-work'];
    if(channel==='wecom') args.push('--enterprise',wecomEnterprise,'--space',wecomSpace);
    else args.push('--group',group);
    if(verifyOnly) args.push('--verify-only');
    else args.push('--execute','--authorization',channel==='wecom'?wecomAuthorization:authorization,'--deadline-unix',String(deadline/1000));
    const phone=await exec(c.python,args,{maxBuffer:4*1024*1024});
    const receipt=JSON.parse(phone.stdout.trim());
    const targetOk=channel==='wecom'?receipt.targetName===EXPECTED_WECOM_SPACE:receipt.groupName===EXPECTED_GROUP;
    if(!receipt.ok || !targetOk || receipt.sent.length!==2) throw Error('delivery-not-two-confirmed-files');
    result.nodes=[...(previous.nodes||[]),{name:'delivery-channel-selection',startedAt:selectionStarted,finishedAt:nodeStart,elapsedMs:nodeStart-selectionStarted,ok:true,llmIntervention:false},
      {name:verifyOnly?`${channel}-verify`:channel,startedAt:nodeStart,finishedAt:Date.now(),elapsedMs:Date.now()-nodeStart,ok:true,llmIntervention:false}];
    result.wechatChannel=channel;
    result.ok=true;
    result.stage=verifyOnly?'verified':'complete';
    result.sent=receipt.sent;result.deliveryTarget=channel==='wecom'?EXPECTED_WECOM_SPACE:EXPECTED_GROUP;
    result.businessCompleted=true;
    delete result.reason;
    delete result.phoneOutput;
  } catch(error) {
    const selectionPassed=nodeStart>selectionStarted;
    result.nodes=[...(previous.nodes||[]),{name:'delivery-channel-selection',startedAt:selectionStarted,finishedAt:selectionPassed?nodeStart:Date.now(),elapsedMs:(selectionPassed?nodeStart:Date.now())-selectionStarted,ok:selectionPassed,llmIntervention:false}];
    if(selectionPassed) result.nodes.push({name:verifyOnly?`${channel}-verify`:channel,startedAt:nodeStart,finishedAt:Date.now(),elapsedMs:Date.now()-nodeStart,ok:false,llmIntervention:false});
    result.reason=String(error.message||error);
    if(error.stdout) result.phoneOutput=error.stdout;
  } finally {
    result.elapsedMs=Date.now()-startedAt;
    result.efficiencyPassed=result.businessCompleted && result.elapsedMs<=180000;
    result.efficiencyStatus=result.elapsedMs>180000?'效率未达标':(result.businessCompleted?'效率达标':'尚未完成');
    await fs.writeFile(c.examReceipt,JSON.stringify(result,null,2));
    console.log(JSON.stringify(result));
  }
  if(!result.ok) process.exitCode=1;
}

if(mode==='--download') await download();
if(mode==='--prepare') await prepare();
if(mode==='--send') await send(false);
if(mode==='--verify-only') await send(true);
