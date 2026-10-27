// Read-only business acceptance. Original technical unknown receipts stay intact.
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';
const ROOT=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../../../..');
const GROUP='上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰';
const hash=b=>crypto.createHash('sha256').update(b).digest('hex');
const pythonJson=x=>Array.isArray(x)?'['+x.map(pythonJson).join(', ')+']':x&&typeof x==='object'?'{'+Object.keys(x).sort().map(k=>JSON.stringify(k)+': '+pythonJson(x[k])).join(', ')+'}':JSON.stringify(x);
const read=async p=>JSON.parse(await fs.readFile(p,'utf8'));
export async function userImagePrefix(businessDate,{root=ROOT}={}){
 const file=path.join(root,'runtime/state',`taobao-image-user-prefix-${businessDate}.json`);
 let a;try{a=await read(file);}catch(e){if(e.code==='ENOENT')return null;throw e;}
 const fail=()=>{throw Error('user-image-prefix-evidence-invalid');};
 if(a.source!=='explicit-user-business-confirmation'||a.businessDate!==businessDate||a.groupName!==GROUP||a.name!=='jinsha-store-final.png'||a.confirmation!=='上传金鲨 这个 还差一个 图片 。')fail();
 if(hash(await fs.readFile(a.screenshot))!==a.screenshotSha256||hash(await fs.readFile(a.sourcePath))!==a.sha256)fail();
 const task=await read(path.join(a.taskDirectory,'task.json')), reply=await read(path.join(a.taskDirectory,'response.json'));
 const bare=Object.fromEntries(Object.entries(task).filter(([k])=>k!=='binding'));
 if(task.stage!=='send'||task.item.type!=='image'||task.request.context.workflowId!=='taobao-evidence'||reply.result.resolvedGroup!==GROUP||hash(pythonJson(bare))!==task.binding||reply.binding!==task.binding||reply.taskId!==task.taskId||task.request.groupName!==GROUP||task.item.name!==a.name||task.item.sha256!==a.sha256||reply.result.sendAttempts!==1||reply.result.status!=='unknown')fail();
 const marker=await read(task.request.context.eventId),receipt=await read(a.receiptFile);
 if(marker.groupName!==GROUP||marker.payloadType!=='image'||!/^[a-f0-9]{64}$/.test(marker.commonReceipt?.eventKey||'')||receipt.ok!==true||receipt.phase!=='completed'||receipt.cleanupStatus!=='completed'||receipt.evidenceManifest?.businessDate!==businessDate||marker.payloads?.[0]?.sha256!==a.sha256||marker.payloads?.[1]?.name!=='jinsha-review-final.png'||marker.commonReceipt?.items?.[1])fail();
 const images=receipt.evidenceManifest.images;
 if(images?.[0]?.sha256!==a.sha256||images?.[1]?.sha256!==marker.payloads[1].sha256)fail();
 const event=path.join(path.dirname(task.request.context.eventId),'.wechat-messaging/events',marker.commonReceipt.eventKey);
 for(const child of await fs.readdir(event,{withFileTypes:true})){
  if(!child.isDirectory())continue;
  let d;try{d=await read(path.join(event,child.name,'delivery.json'));}catch(e){if(e.code==='ENOENT')continue;throw e;}
  if(d.sha256===images[1].sha256)fail();
 }
 return {name:a.name,receiptFile:a.receiptFile,source:file,groupName:GROUP,businessDate};
}
