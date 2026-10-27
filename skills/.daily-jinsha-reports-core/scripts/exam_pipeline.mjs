import fs from 'node:fs/promises';
import crypto from 'node:crypto';
import path from 'node:path';
import { constants } from 'node:fs';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { runBuildReports } from './build_reports.mjs';
import { assertJinshaReleased, isCurrentDownloadUi } from './download_receipt_contract.mjs';
const exec = promisify(execFile);
const [configPath, startArg] = process.argv.slice(2);
const c = JSON.parse(await fs.readFile(configPath, 'utf8'));
let downloadUi;
if(startArg==='--wait') {
  const waitStartedAt=Date.now();
  const until=Date.now()+15*60*1000;
  while(Date.now()<until) {
    try {
      const candidate=JSON.parse(await fs.readFile(c.downloadUiReceipt,'utf8'));
      const currentRun=isCurrentDownloadUi(c,candidate,waitStartedAt);
      if(currentRun){downloadUi=candidate;break;}
    }
    catch(error) { if(error.code!=='ENOENT')throw error; }
    await new Promise(resolve=>setTimeout(resolve,150));
  }
  if(!downloadUi)throw Error('download-receipt-wait-expired');
  if(!downloadUi.ok)throw Error('desktop-incomplete-resume-same-run');
  assertJinshaReleased(downloadUi);
}
if(startArg==='--resume') {
  const candidate=JSON.parse(await fs.readFile(c.downloadUiReceipt,'utf8'));
  if(candidate?.runId!==c.runId || candidate?.ok!==true)throw Error('download-receipt-resume-binding-mismatch');
  assertJinshaReleased(candidate);
  downloadUi=candidate;
}
const startedAt = Number(downloadUi?.startedAt || startArg);
if (!Number.isFinite(startedAt) || startedAt < 1e12) throw Error('invalid-start');
const deadline = startedAt + 180000;
const result = {ok: false, runId: c.runId, startedAt, deadline, stage: 'downloads', stageMs: {}};
result.nodes=[];
const mark=async(name,fn)=>{const start=Date.now();let ok=false;try{const v=await fn();ok=true;return v;}finally{result.nodes.push({name,startedAt:start,finishedAt:Date.now(),elapsedMs:Date.now()-start,ok,llmIntervention:false});}};
if(downloadUi){
  result.desktop=downloadUi;
  result.jinshaResourceReleased=true;
  result.jinshaReleasedAt=downloadUi.jinshaReleasedAt;
  result.stageMs.desktop=downloadUi.elapsedMs;
  result.stageMs.handoff=Date.now()-startedAt-downloadUi.elapsedMs;
}
// 180秒只衡量效率；业务步骤和已完成文件不因超时重做。
const check = () => { result.efficiencyExceeded = Date.now() > deadline; };
const budget = () => 30000; // 单个只读文件检查的超时，不是整轮截止。
try {
  const d = {ok:true, executor:'jinsha-download', businessDate:c.businessDate, clickAttempts:{meituan:1,taobao:1}};
  for (const platform of ['meituan','taobao']) {
    check(); const file = c.raw[platform];
    const info = await fs.stat(file);
    const downloadStartedAt=Number(downloadUi?.files?.[platform]?.downloadStartedAt ?? downloadUi?.files?.[platform]?.savedAt ?? startedAt);
    if (!Number.isFinite(downloadStartedAt) || info.mtimeMs < downloadStartedAt - 2000 || info.size === 0) throw Error('not-new-download:'+platform);
    await exec('/usr/bin/unzip',['-t',file],{timeout:budget(),maxBuffer:4*1024*1024});
    d[platform]={file,size:info.size,sha256:crypto.createHash('sha256').update(await fs.readFile(file)).digest('hex')};
  }
  await fs.writeFile(c.downloadReceipt, JSON.stringify(d));
  result.stageMs.downloads=Date.now()-startedAt;
  check(); result.stage='build'; const buildStart=Date.now();
  const buildStatePath=c.buildReceipt+'.checkpoint.json';
  let build;
  try {
    const state=JSON.parse(await fs.readFile(buildStatePath,'utf8'));
    if(state.runId!==c.runId || JSON.stringify(state.raw)!==JSON.stringify(d))throw Error('build-checkpoint-binding-mismatch');
    build=JSON.parse(await fs.readFile(c.buildReceipt,'utf8'));
    for(const item of Object.values(build.files))if(crypto.createHash('sha256').update(await fs.readFile(item.file)).digest('hex')!==item.sha256)throw Error('build-checkpoint-hash-mismatch');
    result.buildReused=true;
  } catch(error) {if(error.code!=='ENOENT')throw error;}
  if(!build)build = await mark('build',()=>runBuildReports({receipt:c.downloadReceipt,buildReceipt:c.buildReceipt,outputDir:c.outputDir,filenameSuffix:c.suffix || '',titleSuffix:c.titleSuffix || ''}));
  if(c.sendNames) {
    for(const platform of ['meituan','taobao']) {
      check(); const name=c.sendNames[platform];
      if(typeof name!=='string'||path.basename(name)!==name||!name.endsWith('.xlsx')||name.includes('\\'))throw Error('unsafe-send-name');
      const item=build.files[platform],destination=path.join(c.outputDir,name);
      if(destination!==item.file)await fs.copyFile(item.file,destination,constants.COPYFILE_EXCL);
      item.file=destination;item.name=name;
    }
    await fs.writeFile(c.buildReceipt,JSON.stringify(build,null,2));
  }
  result.stageMs.build=Date.now()-buildStart;
  await fs.writeFile(buildStatePath,JSON.stringify({runId:c.runId,raw:d}));
  check();
  console.log(JSON.stringify({sendPrecheck:Object.values(build.files).map(x=>({path:x.file,size:x.size,sha256:x.sha256})),elapsedMs:Date.now()-startedAt}));
  result.stage='phone'; const phoneStart=Date.now();
  const phone=await mark('phone',()=>exec(c.python,[c.sender,'--build-receipt',c.buildReceipt,'--send-receipt',c.sendReceipt,'--execute','--keep-work','--authorization','zhensi-test-main-wechat-jinsha-files-v1','--deadline-unix',String(deadline/1000)],{maxBuffer:4*1024*1024}));
  const receipt=JSON.parse(phone.stdout.trim());
  if(!receipt.ok || receipt.sent.length!==2) throw Error('phone-not-two-confirmed-files');
  result.stageMs.phone=Date.now()-phoneStart;
  check(); result.ok=true; result.stage='complete'; result.sent=receipt.sent;
} catch(error) {
  result.reason=String(error.message||error); if(error.stdout) result.phoneOutput=error.stdout;
  const last=result.nodes.at(-1);if(last?.name==='phone')result.stageMs.phone=last.elapsedMs;
} finally {
  result.elapsedMs=Date.now()-startedAt;
  result.businessCompleted=result.ok;
  result.efficiencyPassed=result.ok && result.elapsedMs<=180000;
  result.efficiencyStatus=result.elapsedMs>180000?'效率未达标':(result.ok?'效率达标':'尚未完成');
  await fs.writeFile(c.examReceipt,JSON.stringify(result,null,2));
  console.log(JSON.stringify(result));
}
process.exitCode=result.ok?0:1;
