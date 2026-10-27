import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';

const root = path.resolve(import.meta.dirname, '../../..');
const dead = spawnSync(process.execPath, ['-e','process.exit(0)']);
assert.equal(dead.status,0);assert.ok(Number.isInteger(dead.pid));
const specs = [
  ['taobao-brand-post','acquirePostLease','releasePostLease'],
  ['taobao-svc-post','acquirePostLease','releasePostLease'],
  ['meituan-post','acquirePostLease','releasePostLease'],
  ['jinsha-post','acquireJinshaLease','releaseJinshaLease'],
];
async function isolated(t) {
  const folder=await fs.mkdtemp(path.join(os.tmpdir(),'physical-post-test-'));
  t.after(()=>fs.rm(folder,{recursive:true,force:true}));
  return path.join(folder,'physical.lock');
}
for (const [post,acquireName,releaseName] of specs) {
  let module;
  if (process.env.POST_LEASE_TEST_ORIGINALS === '1') {
    const file=path.join(root,'runtime/state/post-lease-process-ownership-20261028/originals/skills/posts',post,'scripts/lease.mjs');
    module=await import('data:text/javascript;base64,'+Buffer.from(await fs.readFile(file)).toString('base64'));
  } else module=await import(path.join(root,'skills/posts',post,'scripts/lease.mjs'));
  const acquire=module[acquireName],release=module[releaseName],jinsha=post==='jinsha-post';
  async function busy(run,file,ttl=1) {
    if(jinsha)await assert.rejects(()=>acquire(run,file,ttl),/jinsha-lease-busy/);
    else assert.equal(await acquire(run,file,ttl),null);
  }
  test(post+' live owner survives TTL',async t=>{
    const file=await isolated(t);await fs.writeFile(file,JSON.stringify({runId:'other',pid:process.pid,acquiredAt:1}));
    const before=await fs.readFile(file);await busy('new',file);assert.deepEqual(await fs.readFile(file),before);
  });
  test(post+' fresh dead owner is reclaimed immediately',async t=>{
    const file=await isolated(t);await fs.writeFile(file,JSON.stringify({runId:'dead',pid:dead.pid,acquiredAt:Date.now()}));
    const lease=await acquire('new',file,600000);assert.equal(lease.runId,'new');assert.equal(lease.pid,process.pid);
    assert.equal(lease[jinsha?'path':'leasePath'],file);assert.equal(await release(lease),true);
  });
  test(post+' own repeated run preserves original API contract',async t=>{
    const file=await isolated(t),lease=await acquire('same',file,600000);
    if(jinsha)await busy('same',file,600000);else assert.deepEqual(await acquire('same',file,600000),lease);
    assert.equal(await release(lease),true);
  });
  test(post+' same runId cannot adopt another live PID',async t=>{
    const file=await isolated(t);await fs.writeFile(file,JSON.stringify({runId:'same',pid:process.ppid,acquiredAt:Date.now()}));
    const before=await fs.readFile(file);await busy('same',file,600000);assert.deepEqual(await fs.readFile(file),before);
  });
  test(post+' altered owner cannot release and stale token cannot release reacquisition',async t=>{
    const file=await isolated(t),lease=await acquire('same',file,600000);
    if(jinsha)await assert.rejects(()=>release({...lease,pid:lease.pid+1}),/owner-mismatch/);
    else assert.equal(await release({...lease,pid:lease.pid+1}),false);
    assert.equal(await release(lease),true);
    const current=await acquire('same',file,600000);
    if(jinsha)await assert.rejects(()=>release(lease),/owner-mismatch/);else assert.equal(await release(lease),false);
    assert.equal(await release(current),true);
  });
  test(post+' opaque expired owner is not guessed dead',async t=>{
    const file=await isolated(t);await fs.writeFile(file,'{"runId":"opaque","acquiredAt":1}');
    await busy('new',file);assert.equal(await fs.readFile(file,'utf8'),'{"runId":"opaque","acquiredAt":1}');
  });
}
