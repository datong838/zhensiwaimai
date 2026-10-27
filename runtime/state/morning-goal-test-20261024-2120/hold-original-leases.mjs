import fs from 'node:fs/promises';
const root='/Users/ddt/work/projects/ai_agent/zhensi_waimai_back';
const leases=[];
try {
 for (const [port,post] of [[9230,'taobao-brand-post'],[9231,'taobao-svc-post'],[9232,'jinsha-post'],[9233,'meituan-post']]) {
  const mod=await import(`${root}/skills/posts/${post}/scripts/lease.mjs`);
  const acquire=port===9232?mod.acquireJinshaLease:mod.acquirePostLease;
  const release=port===9232?mod.releaseJinshaLease:mod.releasePostLease;
  const lease=await acquire(`morning-goal-test-20261024-2120-${port}`);
  if(!lease)throw Error(`post-lease-busy:${port}`);
  leases.push({port,lease,release});
 }
 await fs.writeFile(`${root}/runtime/state/morning-goal-test-20261024-2120/leases-ready.json`,JSON.stringify({pid:process.pid,ports:leases.map(x=>x.port),acquiredAt:new Date().toISOString()}));
 console.log('Four original leases held; awaiting inspection completion');
 await new Promise(resolve=>process.stdin.once('data',resolve));
}finally{
 for(const entry of leases.reverse())await entry.release(entry.lease);
 console.log('Original leases released');
}
