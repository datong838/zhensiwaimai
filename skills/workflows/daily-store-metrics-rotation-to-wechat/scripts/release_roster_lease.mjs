import fs from 'node:fs/promises';
import { pathToFileURL } from 'node:url';
import { releasePostLease } from '../../../posts/taobao-brand-post/scripts/lease.mjs';

export const validRosterRunId = value => /^monthly-roster-[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(value);

// Called only after the parent has waited for its exact collector child to exit.
export async function releaseExitedRosterLease(runId, pid, {
  leasePath = '/tmp/zhensi-post-9230.lock', release = releasePostLease,
} = {}) {
  if (!validRosterRunId(runId) || !Number.isInteger(pid) || pid <= 0) throw Error('roster-cleanup-identity-invalid');
  let owner;
  try { owner = JSON.parse(await fs.readFile(leasePath, 'utf8')); }
  catch (error) {
    if (error.code === 'ENOENT') return { released: false, reason: 'lease-absent' };
    throw Error('roster-cleanup-lease-unreadable');
  }
  if (!owner || typeof owner !== 'object' || !Number.isInteger(owner.pid) || owner.pid <= 0 || typeof owner.runId !== 'string') {
    throw Error('roster-cleanup-lease-invalid');
  }
  if (owner.pid !== pid || owner.runId !== runId) return { released: false, reason: 'foreign-lease-preserved' };
  try { process.kill(pid, 0); }
  catch (error) {
    if (error.code !== 'ESRCH') throw Error('roster-cleanup-process-unconfirmed');
    const released = await release({ ...owner, leasePath });
    return { released, reason: released ? 'exited-own-lease-released' : 'lease-changed-or-release-failed' };
  }
  throw Error('roster-cleanup-process-still-alive');
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  releaseExitedRosterLease(process.argv[2], Number(process.argv[3]))
    .then(result => console.log(JSON.stringify(result)))
    .catch(error => { console.error(error.message); process.exitCode = 1; });
}
