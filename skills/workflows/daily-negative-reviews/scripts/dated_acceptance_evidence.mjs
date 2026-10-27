// One dated business acceptance. Read-only; never verifies transport or authorizes resend.
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {FIXED} from './workflow_policy.mjs';
const OLD='2026-10-25', CURRENT='2026-10-26', RUN_DAY='2026-10-26';
const GROUP='上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰';
const CONFIRMATION='runtime/state/user-confirmed-deliveries/20261026-executed-image-submissions-173035.json';
const QUOTES=['今天所有已经执行的任务流的图片提交 我都看了没有问题 只是有个通病；回执待确认/unknow 等','是的 今天已经执行的任务流 都执行成功了 没有 遗漏和错过的'];
const sha=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
function ensure(value,reason){if(!value)throw Error(`dated-acceptance:${reason}`);}
const ledger=(root,image)=>path.join(root,'.local/state',image?'negative-review-summary-send-shanghai-zhensi-operations-ding-fandang-v1.desktop-attempts':'negative-review-send-shanghai-zhensi-operations-ding-fandang-v1.desktop-attempts');
const marker=(root,day,image)=>path.join(ledger(root,image),`${image?'negative-review-summary':'negative-review'}-${day}.json`);
const imageName=`差评分析长图_${OLD}_${OLD}.jpg`, fileName=`差评分析数据_${OLD}_${OLD}.xlsx`;
function payload(receipt,identity,type){
 ensure(receipt.groupName===GROUP&&receipt.payloadType===type&&receipt.sendAttempts===1&&receipt.payloads?.length===1,'receipt-contract');
 const item=receipt.payloads[0];ensure(item.name===identity.name&&item.path===identity.path&&item.size===identity.size&&item.sha256===identity.sha256,'receipt-payload');
}
export function validateDatedAcceptance(bundle,allowedBusinessDate,currentBusinessDate,now=new Date()){
 ensure(allowedBusinessDate===OLD&&currentBusinessDate===CURRENT,'date-scope');
 const {root,confirmation:c,config,state,fileReceipt,imageReceipt,fileMarker,imageMarker,identities,originals}=bundle;
 ensure(config.businessDate===OLD&&config.runDay===RUN_DAY&&state.businessDate===OLD&&state.phase==='sent'&&state.status==='recoverable','old-run');
 ensure(config.runDir===path.join(root,'.local/runs/daily-negative-reviews/20261025')&&config.report===path.join(root,'outputs/yesterday-negative-20261025',fileName)&&config.screenshot===path.join(root,'outputs/yesterday-negative-20261025',imageName),'old-config');
 ensure(c?.source==='explicit-user-confirmation'&&c.businessAccepted===true&&c.date===RUN_DAY&&c.newSendAttempts===0&&c.technicalRecordsModified===false&&c.scope==='already-executed-image-submissions-only; no future slots or unexecuted actions'&&JSON.stringify(c.userQuotes)===JSON.stringify(QUOTES),'user-confirmation');
 const cutoff=Date.parse(c.recordedAt);ensure(Number.isFinite(cutoff)&&c.recordedAt.startsWith(RUN_DAY+'T')&&cutoff<=now.getTime(),'confirmation-time');
 const selected=c.items?.filter(i=>i.workflowId==='negative-reviews-summary');ensure(selected?.length===1,'confirmation-count');const proof=selected[0];
 ensure(/^[a-f0-9-]{36}$/.test(proof.taskId)&&proof.eventId===marker(root,OLD,true)&&proof.groupName===GROUP&&proof.name===imageName&&proof.sendAttempts===1&&proof.technicalStatusPreserved==='unknown','confirmation-binding');
 for(const name of ['task.json','response.json','send-intent.json'])ensure(typeof originals[name]==='string'&&sha(originals[name])===proof.sources?.[name],`original-hash:${name}`);
 const task=JSON.parse(originals['task.json']),response=JSON.parse(originals['response.json']),intent=JSON.parse(originals['send-intent.json']);
 for(const item of [task,response,intent])ensure(item.taskId===proof.taskId&&item.binding===task.binding&&typeof task.binding==='string'&&task.binding.length===64,'task-binding');
 const request=task.request, frozen=task.item, result=response.result;
 ensure(task.stage==='send'&&request.operation==='send'&&request.groupName===GROUP&&request.context?.workflowId==='negative-reviews-summary'&&request.context?.eventId===proof.eventId&&request.items?.length===1,'task-request');
 ensure(result.status==='unknown'&&result.sendAttempts===1&&result.resolvedGroup===GROUP&&result.inputEmpty===true&&result.backend==='system-events-ui-tree','old-unknown-unaccepted');
 const identity=identities.image;
 ensure(identity.name===imageName&&identity.path===config.screenshot&&identity.size>0&&/^[a-f0-9]{64}$/.test(identity.sha256)&&proof.sha256===identity.sha256,'image-identity');
 for(const item of [frozen,request.items[0]])ensure(item.type==='image'&&item.itemId==='0'&&item.name===imageName&&item.sha256===identity.sha256&&item.size===identity.size,'image-payload');
 ensure(request.items[0].path===config.screenshot&&identities.frozen.path===frozen.path&&identities.frozen.sha256===identity.sha256&&identities.frozen.size===identity.size,'frozen-payload');
 ensure(intent.sha256===identity.sha256&&intent.backend==='system-events-ui-tree'&&Number.isFinite(intent.at)&&intent.at*1000<=cutoff&&Math.abs(Date.parse(proof.submittedAt)-intent.at*1000)<2&&proof.submittedAt.startsWith(RUN_DAY+'T'),'submission-intent');
 ensure(identities.file.name===fileName&&identities.file.path===config.report&&identities.file.size>0,'excel-identity');
 for(const receipt of [fileReceipt,fileMarker]){payload(receipt,identities.file,'file');ensure(receipt.state==='verified'&&receipt.verified===true&&receipt.attemptMarker===marker(root,OLD,false),'excel-not-verified');}
 for(const receipt of [imageReceipt,imageMarker]){payload(receipt,identity,'image');ensure(receipt.state==='unknown'&&receipt.verified===false&&receipt.attemptMarker===marker(root,OLD,true),'image-technical-state');}
 return {previousAllowedBusinessDate:OLD,allowedBusinessDate:CURRENT,basis:'dated-explicit-user-business-acceptance',confirmationPath:path.join(root,CONFIRMATION),confirmationSha256:sha(JSON.stringify(c)),taskId:proof.taskId,eventId:proof.eventId,sourceHashes:{...proof.sources},technicalStatusPreserved:'unknown',newSendAttempts:0};
}
async function exists(file){try{await fs.access(file);return true;}catch(e){if(e.code==='ENOENT')return false;throw e;}}
export async function assertNewDatedRunAbsent(root,currentBusinessDate){
 ensure(currentBusinessDate===CURRENT,'date-scope');
 for(const file of [path.join(root,'.local/runs/daily-negative-reviews/20261026'),path.join(root,'outputs/yesterday-negative-20261026'),marker(root,CURRENT,false),marker(root,CURRENT,true)])ensure(!await exists(file),'new-run-has-effect');
 const queue=path.join(root,'skills/wechat-messaging/.runtime/ui-post-queue');
 if(await exists(queue))for(const entry of await fs.readdir(queue,{withFileTypes:true})){
  if(!entry.isDirectory())continue;const file=path.join(queue,entry.name,'task.json');if(!await exists(file))continue;
  const task=JSON.parse(await fs.readFile(file,'utf8'));
  ensure(![marker(root,CURRENT,false),marker(root,CURRENT,true)].includes(task.request?.context?.eventId),'new-event-queue-exists');
 }
 return true;
}
export async function inspectDatedAcceptance(root,allowedBusinessDate,currentBusinessDate,now=new Date()){
 ensure(allowedBusinessDate===OLD&&currentBusinessDate===CURRENT,'date-scope');
 const artifactHashes={};const read=async file=>{const bytes=await fs.readFile(file);artifactHashes[file]=sha(bytes);return JSON.parse(bytes);};
 const config=await read(path.join(root,'.local/runs/daily-negative-reviews/20261025/config.json'));
 const confirmation=await read(path.join(root,CONFIRMATION));const selected=confirmation.items?.filter(i=>i.workflowId==='negative-reviews-summary');ensure(selected?.length===1&&/^[a-f0-9-]{36}$/.test(selected[0].taskId),'confirmation-count');
 const folder=path.join(root,'skills/wechat-messaging/.runtime/ui-post-queue',selected[0].taskId),originals={};
 for(const name of ['task.json','response.json','send-intent.json']){const file=path.join(folder,name);originals[name]=await fs.readFile(file,'utf8');artifactHashes[file]=sha(originals[name]);}
 const task=JSON.parse(originals['task.json']);
 // Paths come from the dated, locally retained artifacts; no credential or network access.
 ensure(config.report===path.join(root,'outputs/yesterday-negative-20261025',fileName)&&config.screenshot===path.join(root,'outputs/yesterday-negative-20261025',imageName),'old-config');
 const frozen=task.item?.path;ensure(typeof frozen==='string'&&frozen.startsWith(ledger(root,true)+path.sep)&&frozen.endsWith('/payload/'+imageName),'frozen-path');
 const identity=async file=>{const bytes=await fs.readFile(file);return {path:file,name:path.basename(file),size:bytes.length,sha256:sha(bytes)};};
 const run=path.join(root,'.local/runs/daily-negative-reviews/20261025');
 const bundle={root,confirmation,config,state:await read(path.join(run,'workflow-state.json')),fileReceipt:await read(path.join(run,'wechat-send/receipt.json')),imageReceipt:await read(path.join(run,'wechat-screenshot-send/receipt.json')),fileMarker:await read(marker(root,OLD,false)),imageMarker:await read(marker(root,OLD,true)),originals,identities:{file:await identity(config.report),image:await identity(config.screenshot),frozen:await identity(frozen)}};
 const evidence=validateDatedAcceptance(bundle,allowedBusinessDate,currentBusinessDate,now);evidence.confirmationSha256=sha(await fs.readFile(path.join(root,CONFIRMATION)));evidence.oldArtifactHashes=artifactHashes;
 await assertNewDatedRunAbsent(root,currentBusinessDate);return evidence;
}

// A new daily event is independent of any old transport result. This proves
// absence of effects for the new date; it never accepts or modifies old runs.
export async function inspectIndependentBusinessDay(root,previous,current,now=new Date()){
 const day=d=>new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(d);
 const runDay=day(now),expected=day(new Date(new Date(`${runDay}T12:00:00+08:00`).getTime()-86400000));
 const valid=s=>/^\d{4}-\d{2}-\d{2}$/.test(s||'')&&day(new Date(`${s}T12:00:00+08:00`))===s;
 ensure(valid(previous)&&valid(current)&&previous<current&&current===expected,'independent-date-scope');
 const compact=current.replaceAll('-','');
 const absentPaths=[path.join(root,'.local/runs/daily-negative-reviews',compact),path.join(root,'outputs',`yesterday-negative-${compact}`),marker(root,current,false),marker(root,current,true)];
 for(const file of absentPaths)ensure(!await exists(file),'new-run-has-effect');
 const queue=path.join(root,'skills/wechat-messaging/.runtime/ui-post-queue');
 if(await exists(queue))for(const entry of await fs.readdir(queue,{withFileTypes:true})){
  if(!entry.isDirectory())continue;
  const file=path.join(queue,entry.name,'task.json');if(!await exists(file))continue;
  const task=JSON.parse(await fs.readFile(file,'utf8'));
  ensure(![marker(root,current,false),marker(root,current,true)].includes(task.request?.context?.eventId),'new-event-queue-exists');
 }
 return {previousAllowedBusinessDate:previous,allowedBusinessDate:current,runDay,
  basis:'independent-new-business-day',authorization:'user-20261027-history-must-not-block-new-day',
  checkedAbsentPaths:absentPaths,oldRecordsModified:false,oldDeliveryAccepted:false,
  technicalStatusPreserved:'unknown',newSendAttempts:0};
}

// Narrow same-day installation proof for the user's explicit 2026-10-27
// acceptance. It allows code maintenance, never resealing or another send.
export async function inspectCurrentAcceptedSubmission(config,group,now=new Date()){
 const root=path.resolve(config.runDir,'../../../..');
 ensure(config.runDay==='2026-10-27'&&config.businessDate==='2026-10-26'&&group===GROUP,'current-acceptance-scope');
 const file=path.join(root,'runtime/state/user-confirmed-deliveries/20261027-executed-image-submissions-user-confirmed.json');
 const bytes=await fs.readFile(file),c=JSON.parse(bytes);
 const quote='这些图片都有一次提交记录，卡在内容回读，我看到都发送成功了，但是你工作流没拿到回执 事情已经发生了你看如何完善维护，不过 工作流确实执行成功了 可以发台账';
 const cutoff=Date.parse(c.recordedAt);
 ensure(c.source==='explicit-user-confirmation'&&c.businessAccepted===true&&c.date===config.runDay&&JSON.stringify(c.userQuotes)===JSON.stringify([quote])&&Number.isFinite(cutoff)&&cutoff<=now.getTime(),'current-user-confirmation');
 const selected=c.items.filter(i=>i.workflowId==='negative-reviews-summary');ensure(selected.length===1,'current-confirmation-count');const proof=selected[0];
 ensure(/^[a-f0-9-]{36}$/.test(proof.taskId)&&proof.eventId===marker(root,config.businessDate,true)&&proof.groupName===GROUP,'current-event-binding');
 const folder=path.join(root,'skills/wechat-messaging/.runtime/ui-post-queue',proof.taskId),originals={};
 for(const name of ['task.json','response.json','send-intent.json']){const raw=await fs.readFile(path.join(folder,name));ensure(sha(raw)===proof.sources[name],'current-original-hash');originals[name]=JSON.parse(raw);}
 const task=originals['task.json'],reply=originals['response.json'],intent=originals['send-intent.json'];
 // Preserve Python's float representation from the original serialized task.
 const bindingCheck=spawnSync(FIXED.wechatPython,['-c','import sys,json,hashlib;t=json.load(sys.stdin);print(hashlib.sha256(json.dumps({k:v for k,v in t.items() if k!="binding"},sort_keys=True,ensure_ascii=False).encode()).hexdigest())'],{input:await fs.readFile(path.join(folder,'task.json')),encoding:'utf8',timeout:10000});
 ensure(bindingCheck.status===0&&task.taskId===proof.taskId&&reply.taskId===proof.taskId&&intent.taskId===proof.taskId&&task.binding===reply.binding&&task.binding===intent.binding&&bindingCheck.stdout.trim()===task.binding,'current-task-binding');
 ensure(task.stage==='send'&&task.request.groupName===GROUP&&task.request.context.workflowId==='negative-reviews-summary'&&task.request.context.eventId===proof.eventId,'current-task-request');
 ensure(reply.result.status==='unknown'&&reply.result.sendAttempts===1&&reply.result.resolvedGroup===GROUP&&reply.result.inputEmpty===true&&reply.result.backend==='system-events-ui-tree','current-image-unknown');
 ensure(task.item.type==='image'&&task.item.name===path.basename(config.screenshot)&&task.item.sha256===proof.sha256&&intent.sha256===proof.sha256&&sha(await fs.readFile(task.item.path))===proof.sha256&&Number.isFinite(intent.at)&&intent.at*1000<=cutoff,'current-image-identity');
 const receipt=JSON.parse(await fs.readFile(config.sendReceipt,'utf8'));
 ensure(receipt.verified===true&&receipt.state==='verified'&&receipt.groupName===GROUP&&receipt.sendAttempts===1&&receipt.payloads?.length===1&&receipt.payloads[0].name===path.basename(config.report)&&receipt.commonReceipt?.items?.[0]?.status==='verified'&&sha(await fs.readFile(config.report))===receipt.payloads[0].sha256,'current-excel-verified');
 return {basis:'current-explicit-user-confirmation-code-maintenance-only',confirmationPath:file,confirmationSha256:sha(bytes),taskId:proof.taskId,technicalStatusPreserved:'unknown',newSendAttempts:0};
}
