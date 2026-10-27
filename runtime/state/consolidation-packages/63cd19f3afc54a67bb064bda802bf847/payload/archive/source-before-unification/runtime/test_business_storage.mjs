import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import {businessPath,internalPath} from './business_storage.mjs';
const base=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'zhensi-storage-node-'))),root=path.join(base,'repo'),legacy=path.join(base,'old');
try{
 fs.mkdirSync(path.join(root,'runtime'),{recursive:true});fs.mkdirSync(legacy);
 fs.writeFileSync(path.join(root,'runtime/business_storage_catalog.json'),JSON.stringify({schemaVersion:1,objects:{video:{legacy,target:'data/video'}}}));
 assert.equal(businessPath('video',{root}),legacy);
 assert.throws(()=>businessPath('missing',{root}),/unknown/);
 assert.throws(()=>internalPath(root,'../outside'),/invalid/);
 fs.mkdirSync(path.join(root,'data/video'),{recursive:true});
 assert.equal(businessPath('video',{root}),legacy); // Existing copied directory alone never activates.
 const id='a'.repeat(32),relative='runtime/state/storage-migrations/'+id+'/activation.json',proof=path.join(root,relative);
 fs.mkdirSync(path.dirname(proof),{recursive:true});fs.writeFileSync(proof,JSON.stringify({phase:'activated',root,id,objects:{video:{target:'data/video'}}}));
 fs.writeFileSync(path.join(root,'runtime/state/storage-layout-v1.json'),JSON.stringify({schemaVersion:1,root,objects:{video:{target:'data/video',proof:relative,migrationId:id,proofSha256:crypto.createHash('sha256').update(fs.readFileSync(proof)).digest('hex')}}}));
 assert.equal(businessPath('video',{root}),path.join(root,'data/video'));
 fs.writeFileSync(path.join(root,'data/video/new-checkpoint.json'),'new legitimate state');
 assert.equal(businessPath('video',{root}),path.join(root,'data/video')); // New business writes must remain allowed.
 fs.writeFileSync(proof,'{}');assert.throws(()=>businessPath('video',{root}),/proof-invalid/);
 fs.symlinkSync('/nonexistent/outside',path.join(root,'dangling'));assert.throws(()=>internalPath(root,'dangling/file'),/symlink/);
 console.log(JSON.stringify({ok:true,tests:8,businessActions:0}));
}finally{fs.rmSync(base,{recursive:true,force:true});}
