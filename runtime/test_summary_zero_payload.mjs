import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import {preserveZeroSendSummary} from './summary_zero_payload.mjs';
const json=(p,v)=>fs.writeFile(p,JSON.stringify(v));
async function fixture(workflow='meituan-waimai-appeals-summary'){
 const root=await fs.mkdtemp(path.join(os.tmpdir(),'summary-zero-test-'));const ledger=path.join(root,'ledger'),queueRoot=path.join(root,'queue');
 const eventKey='a'.repeat(64),itemKey='b'.repeat(64),group='原运营群';
 const summaryCard=path.join(root,'card.png'),markerPath=path.join(ledger,'marker.json');
 const dir=path.join(ledger,'.wechat-messaging/events',eventKey,itemKey),q=path.join(queueRoot,'original-task');
 await fs.mkdir(path.join(dir,'payload'),{recursive:true});await fs.mkdir(q,{recursive:true});
 const payload=path.join(dir,'payload/card.png'),bytes=Buffer.from('frozen-original-test-only'),sha256=crypto.createHash('sha256').update(bytes).digest('hex');
 await fs.writeFile(payload,bytes);await fs.writeFile(summaryCard,'regenerated-bytes');
 await json(path.join(dir,'delivery.json'),{type:'image',status:'blocked',sendAttempts:0,resolvedGroup:group,sha256});
 const task={taskId:'original-task',stage:'send',binding:'c'.repeat(64),request:{groupName:group,context:{workflowId:workflow,eventId:markerPath}},item:{type:'image',path:payload,sha256}};
 await json(path.join(q,'task.json'),task);await json(path.join(q,'response.json'),{taskId:task.taskId,binding:task.binding,result:{status:'blocked',sendAttempts:0,resolvedGroup:group}});
 const marker={state:'blocked',sendAttempts:0,newSendAttempts:0,groupName:group,payloadType:'image',payloads:[{path:summaryCard}],commonReceipt:{eventKey}};
 return {args:{marker,markerPath,summaryCard,ledger,workflow,group,queueRoot},root,q,payload,bytes};
}
test('strict zero-send proof restores original bytes without changing evidence',async()=>{
 const f=await fixture();try{const before=await fs.readFile(path.join(f.q,'response.json'));const r=await preserveZeroSendSummary(f.args);assert.equal(r.reusedFrozen,true);assert.deepEqual(await fs.readFile(f.args.summaryCard),f.bytes);assert.deepEqual(await fs.readFile(path.join(f.q,'response.json')),before);}finally{await fs.rm(f.root,{recursive:true,force:true});}
});
test('same zero-send rule works for Taobao independent route',async()=>{
 const f=await fixture('taobao-flash-appeals-summary');try{const r=await preserveZeroSendSummary(f.args);assert.equal(r.reusedFrozen,true);assert.deepEqual(await fs.readFile(f.args.summaryCard),f.bytes);}finally{await fs.rm(f.root,{recursive:true,force:true});}
});
for(const kind of ['unknown','sent','intent','hash','group','duplicate'])test('reject '+kind,async()=>{
 const f=await fixture();try{
  if(kind==='unknown')f.args.marker.state='unknown';
  if(kind==='sent')f.args.marker.sendAttempts=1;
  if(kind==='intent')await json(path.join(f.q,'send-intent.json'),{});
  if(kind==='hash')await fs.writeFile(f.payload,'changed');
  if(kind==='group')f.args.group='另一个群';
  if(kind==='duplicate'){
   const second=path.join(f.args.queueRoot,'second');await fs.mkdir(second);const t=JSON.parse(await fs.readFile(path.join(f.q,'task.json'),'utf8'));t.taskId='second';await json(path.join(second,'task.json'),t);await json(path.join(second,'response.json'),{taskId:'second',binding:t.binding,result:{status:'blocked',sendAttempts:0,resolvedGroup:f.args.group}});
  }
  await assert.rejects(()=>preserveZeroSendSummary(f.args));assert.equal(await fs.readFile(f.args.summaryCard,'utf8'),'regenerated-bytes');
 }finally{await fs.rm(f.root,{recursive:true,force:true});}
});
