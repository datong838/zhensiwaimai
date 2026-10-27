// Same fixed catalog and activation contract as business_storage.py; never writes state.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
export const REPO_ROOT=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
export function internalPath(root,relative){
 root=fs.realpathSync(root);
 if(typeof relative!=='string'||!relative||path.isAbsolute(relative)||relative.split('/').includes('..'))throw Error('storage-relative-path-invalid');
 const target=path.join(root,relative);let cursor=root;
 for(const part of relative.split('/').filter(Boolean)){cursor=path.join(cursor,part);try{if(fs.lstatSync(cursor).isSymbolicLink())throw Error('storage-path-symlink-or-escape');}catch(error){if(error.code!=='ENOENT')throw error;}}
 if(!target.startsWith(root+path.sep))throw Error('storage-relative-path-invalid');return target;
}
export function businessPath(key,{root=REPO_ROOT}={}){
 root=fs.realpathSync(root);const data=JSON.parse(fs.readFileSync(path.join(root,'runtime/business_storage_catalog.json'),'utf8'));
 if(data.schemaVersion!==1||!data.objects||typeof data.objects!=='object'||Array.isArray(data.objects))throw Error('storage-catalog-invalid');
 for(const candidate of Object.values(data.objects)){if(!path.isAbsolute(candidate.legacy))throw Error('storage-legacy-path-invalid');internalPath(root,candidate.target);}
 if(!Object.hasOwn(data.objects,key))throw Error('storage-key-unknown:'+key);
 const item=data.objects[key];
 const layout=internalPath(root,'runtime/state/storage-layout-v1.json');if(!fs.existsSync(layout))return item.legacy;
 const state=JSON.parse(fs.readFileSync(layout,'utf8'));if(state.schemaVersion!==1||state.root!==root)throw Error('storage-layout-binding-invalid');
 const active=state.objects?.[key];if(active===undefined)return item.legacy;
 if(active.target!==item.target)throw Error('storage-target-binding-invalid');
 const bytes=fs.readFileSync(internalPath(root,active.proof)),proof=JSON.parse(bytes);
 if(crypto.createHash('sha256').update(bytes).digest('hex')!==active.proofSha256||proof.phase!=='activated'||proof.root!==root||proof.id!==active.migrationId||proof.objects?.[key]?.target!==item.target)throw Error('storage-activation-proof-invalid');
 const target=internalPath(root,item.target);if(!fs.existsSync(target)||!fs.statSync(target).isDirectory())throw Error('storage-active-target-missing');return target;
}
