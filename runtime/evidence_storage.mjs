// Restore only the two historical evidence aliases; never moves or rewrites evidence.
import fs from 'node:fs/promises';
import path from 'node:path';
import {internalPath, REPO_ROOT} from './business_storage.mjs';

export async function ensureEvidenceAliases({repoRoot=REPO_ROOT, aliasRoot='/tmp'}={}) {
  const definitions=[['zhensi_top10','runtime/state/business-evidence/top10'],
    ['zhensi_daily_download','runtime/state/business-evidence/taobao-download']];
  const plans=[];
  for (const [name,relative] of definitions) {
    const target=internalPath(repoRoot,relative);
    const targetStat=await fs.lstat(target);
    if (!targetStat.isDirectory() || targetStat.isSymbolicLink()) throw Error('evidence-target-invalid:'+name);
    const alias=path.join(await fs.realpath(aliasRoot),name);
    let existing;
    try { existing=await fs.lstat(alias); } catch (error) { if(error.code!=='ENOENT')throw error; }
    if (existing && (!existing.isSymbolicLink() || await fs.realpath(alias)!==await fs.realpath(target))) {
      throw Error('evidence-alias-conflict:'+name);
    }
    plans.push({alias,target,exists:Boolean(existing)});
  }
  for (const item of plans) {
    if (item.exists) continue;
    try { await fs.symlink(item.target,item.alias); }
    catch(error) { if(error.code!=='EEXIST')throw error; }
    const stat=await fs.lstat(item.alias);
    if (!stat.isSymbolicLink() || await fs.realpath(item.alias)!==await fs.realpath(item.target)) {
      throw Error('evidence-alias-conflict:'+path.basename(item.alias));
    }
  }
  return {ok:true,aliases:plans.map(({alias,target})=>({alias,target})),evidenceModified:false};
}
