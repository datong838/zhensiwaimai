import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {ensureEvidenceAliases} from './evidence_storage.mjs';
let tests=0;
async function fixture(run) {
  const dir=await fs.mkdtemp(path.join(os.tmpdir(),'zhensi-evidence-alias-test-'));
  const repoRoot=path.join(dir,'repo'),aliasRoot=path.join(dir,'aliases');
  await fs.mkdir(aliasRoot,{recursive:true});
  for(const name of ['top10','taobao-download'])await fs.mkdir(path.join(repoRoot,'runtime/state/business-evidence',name),{recursive:true});
  try { await run({repoRoot,aliasRoot});tests++; } finally { await fs.rm(dir,{recursive:true,force:true}); }
}
await fixture(async options=>{
  const target=path.join(options.repoRoot,'runtime/state/business-evidence/top10/receipt.json');
  await fs.writeFile(target,'original evidence');const before=await fs.stat(target);
  assert.equal((await ensureEvidenceAliases(options)).ok,true);
  const alias=path.join(options.aliasRoot,'zhensi_top10/receipt.json');
  assert.equal(await fs.readFile(alias,'utf8'),'original evidence');
  await ensureEvidenceAliases(options);const after=await fs.stat(target);
  assert.equal(after.ino,before.ino);assert.equal(after.birthtimeMs,before.birthtimeMs);
});
for(const kind of ['directory','file','wrong-link'])await fixture(async options=>{
  const alias=path.join(options.aliasRoot,'zhensi_daily_download');
  if(kind==='directory')await fs.mkdir(alias);
  else if(kind==='file')await fs.writeFile(alias,'do not replace');
  else await fs.symlink(options.repoRoot,alias);
  await assert.rejects(ensureEvidenceAliases(options),/evidence-alias-conflict/);
  assert.ok(await fs.lstat(alias));
  await assert.rejects(fs.lstat(path.join(options.aliasRoot,'zhensi_top10')),/ENOENT/);
});
await fixture(async options=>{
  await fs.rmdir(path.join(options.repoRoot,'runtime/state/business-evidence/taobao-download'));
  await assert.rejects(ensureEvidenceAliases(options),/ENOENT/);
  await assert.rejects(fs.lstat(path.join(options.aliasRoot,'zhensi_top10')),/ENOENT/);
});
await fixture(async options=>{
  const target=path.join(options.repoRoot,'runtime/state/business-evidence/taobao-download');
  await fs.rmdir(target);await fs.symlink(options.aliasRoot,target);
  await assert.rejects(ensureEvidenceAliases(options),/storage-path-symlink-or-escape|evidence-target-invalid/);
});
console.log(JSON.stringify({ok:true,tests,productionActions:0}));
