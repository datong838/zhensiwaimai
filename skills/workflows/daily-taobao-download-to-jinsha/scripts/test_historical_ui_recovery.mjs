import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import {inspectHistoricalUIDelivery} from './scheduled_evidence_recovery.mjs';
const tmp=await fs.mkdtemp(path.join(os.tmpdir(),'historical-ui-test-'));
const root=path.join(tmp,'runs'),ledger=path.join(tmp,'ledger'),evidenceFile=path.join(tmp,'ui.json');
const businessDate='2026-10-23',policyVersion='test',runId='00000000-0000-4000-8000-000000000001';
const groupName='上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰';
const dir=path.join(root,`${businessDate}-${runId}`);
const hash=x=>crypto.createHash('sha256').update(x).digest('hex');
try {
 await fs.mkdir(dir,{recursive:true});await fs.mkdir(ledger);
 const images=[];
 for(const name of ['jinsha-store-final.png','jinsha-review-final.png']) {
  const file=path.join(dir,name);await fs.writeFile(file,name);images.push({path:file,sha256:hash(name)});
 }
 const receipt={ok:true,stage:'completed',phase:'completed',cleanupStatus:'completed',businessDate,runId,
 runReview:[],reviewSummary:{controlPolicyVersion:policyVersion},evidenceManifest:{executor:'background-browser-executor',
 channel:'control-background-dedicated-chrome',runId,mode:'execute',groupName,businessDate,
 uploadDecision:{store:'uploaded-complete',review:'uploaded-complete'},images}};
 await fs.writeFile(path.join(dir,'receipt.json'),JSON.stringify(receipt));
 const copies=[];for(const image of images){const dest=path.join(tmp,path.basename(image.path));await fs.copyFile(image.path,dest);copies.push(dest);}
 const evidence={groupName,authorization:'authorized UI delivery',channel:'cua-visible-ui',originalMarkerPreserved:true,
 status:'both-visible-delivery-confirmed',items:images.map((i,index)=>({source:copies[index],sha256:i.sha256,state:'visible-delivery-confirmed',
 sendAttempts:1,at:'2026-10-24T12:49:00+08:00',verification:'actual visible new image'}))};
 const args={root,ledger,businessDate,policyVersion,evidenceFile};
 const run=async(e=evidence)=>{await fs.writeFile(evidenceFile,JSON.stringify(e));return inspectHistoricalUIDelivery(args);};
 assert.equal((await run()).kind,'historical-ui-completed');
 receipt.evidenceManifest.groupName='FEIBING NEO AI数字员工';await fs.writeFile(path.join(dir,'receipt.json'),JSON.stringify(receipt));
 assert.equal((await run()).kind,'historical-ui-completed');
 receipt.evidenceManifest.groupName='wrong';await fs.writeFile(path.join(dir,'receipt.json'),JSON.stringify(receipt));
 assert.equal((await run()).kind,'blocked');
 receipt.evidenceManifest.groupName=groupName;await fs.writeFile(path.join(dir,'receipt.json'),JSON.stringify(receipt));
 for(const mutate of [e=>e.groupName='wrong',e=>e.items.pop(),e=>e.items[0].sha256='0'.repeat(64),
 e=>e.items[0].at='2026-10-23T12:49:00+08:00',e=>e.items[0].sendAttempts=2,e=>e.authorization='']) {
 const e=structuredClone(evidence);mutate(e);assert.equal((await run(e)).kind,'blocked');
 }
 const marker={bridgeVersion:1,groupName,payloadType:'image',state:'unknown',sendAttempts:1,
 payloads:images.map(i=>({...i,name:path.basename(i.path)})),commonReceipt:{status:'unknown',items:[]}};
 await fs.writeFile(path.join(ledger,'unknown.json'),JSON.stringify(marker));
 assert.equal((await run()).reason,'historical-ui-unsettled-original-event');
 await fs.rm(path.join(ledger,'unknown.json'));
 await fs.writeFile(copies[0],'changed');assert.equal((await run()).reason,'historical-ui-copy-drift');
 await fs.copyFile(images[0].path,copies[0]);
 await fs.writeFile(images[0].path,'changed');assert.equal((await run()).reason,'historical-ui-original-drift');
 console.log(JSON.stringify({ok:true,checks:12,newSendAttempts:0}));
} finally {await fs.rm(tmp,{recursive:true,force:true});}
