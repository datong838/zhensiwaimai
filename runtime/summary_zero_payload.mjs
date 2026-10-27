// Reuse a provably unsent frozen summary. Never edits a ledger, task or receipt.
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
const sha=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
const json=async p=>JSON.parse(await fs.readFile(p,'utf8'));
export async function preserveZeroSendSummary({marker,markerPath,summaryCard,ledger,workflow,group,queueRoot}){
 if(marker.state!=='blocked'||marker.sendAttempts!==0||marker.newSendAttempts!==0||
    ![undefined,0].includes(marker.physicalSendAttempts)||marker.groupName!==group||marker.payloadType!=='image'||
    marker.payloads?.length!==1||path.resolve(marker.payloads[0].path)!==path.resolve(summaryCard))throw Error('summary-zero-recovery-marker-invalid');
 const eventKey=marker.commonReceipt?.eventKey;
 if(!/^[a-f0-9]{64}$/.test(eventKey||''))throw Error('summary-zero-recovery-event-missing');
 const event=path.join(ledger,'.wechat-messaging/events',eventKey),candidates=[];
 for(const entry of await fs.readdir(event,{withFileTypes:true})){
  if(!entry.isDirectory()||!/^[a-f0-9]{64}$/.test(entry.name))continue;
  const dir=path.join(event,entry.name);let delivery;
  try{delivery=await json(path.join(dir,'delivery.json'));}catch(e){if(e.code==='ENOENT')continue;throw e;}
  if(delivery.type!=='image'||delivery.status!=='blocked'||delivery.sendAttempts!==0||delivery.resolvedGroup!==group)throw Error('summary-zero-recovery-original-not-unsent');
  const payload=path.join(dir,'payload',path.basename(summaryCard));const stat=await fs.lstat(payload);
  if(!stat.isFile()||stat.isSymbolicLink())throw Error('summary-zero-recovery-payload-invalid');
  const bytes=await fs.readFile(payload);if(sha(bytes)!==delivery.sha256)throw Error('summary-zero-recovery-hash-mismatch');
  candidates.push({payload,bytes,sha256:delivery.sha256});
 }
 if(candidates.length!==1)throw Error('summary-zero-recovery-payload-not-unique');
 const frozen=candidates[0],proofs=[];
 for(const entry of await fs.readdir(queueRoot,{withFileTypes:true})){
  if(!entry.isDirectory()||entry.isSymbolicLink())continue;
  const dir=path.join(queueRoot,entry.name);let task;
  try{task=await json(path.join(dir,'task.json'));}catch(e){if(e.code==='ENOENT')continue;throw e;}
  if(task.stage!=='send'||task.request?.context?.workflowId!==workflow||task.request?.context?.eventId!==path.resolve(markerPath))continue;
  const reply=await json(path.join(dir,'response.json'));
  if(task.taskId!==entry.name||reply.taskId!==task.taskId||reply.binding!==task.binding||
     task.request.groupName!==group||task.item?.type!=='image'||task.item.sha256!==frozen.sha256||
     path.resolve(task.item.path)!==path.resolve(frozen.payload)||reply.result?.status!=='blocked'||
     reply.result.sendAttempts!==0||reply.result.resolvedGroup!==group)throw Error('summary-zero-recovery-task-proof-invalid');
  try{await fs.stat(path.join(dir,'send-intent.json'));throw Error('summary-zero-recovery-existing-intent');}catch(e){if(e.code!=='ENOENT')throw e;}
  proofs.push(dir);
 }
 if(proofs.length!==1)throw Error('summary-zero-recovery-task-not-unique');
 const temporary=summaryCard+'.zero-recovery-'+process.pid+'.tmp';
 await fs.writeFile(temporary,frozen.bytes,{mode:0o600});await fs.rename(temporary,summaryCard);
 return {reusedFrozen:true,sha256:frozen.sha256,originalTask:proofs[0],sendAttempts:0};
}
