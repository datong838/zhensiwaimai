import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { acquirePostLease, releasePostLease } from '../../../skills/posts/meituan-post/scripts/lease.mjs';
import { resetIM } from '../../im_env_reset_20261008.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ATTEMPT = path.join(HERE, '2200-attempt.json');
const runId = `maintenance-2200-${Date.now()}`;
const lease = await acquirePostLease(runId);
if (!lease) {
  console.log(JSON.stringify({attempted:false, reason:'meituan-post-physical-lease-busy'}));
  process.exit(3);
}
try {
  const attempt = {
    startedAt: new Date().toISOString(), kind: '2200-maintenance',
    imResetAttempts: 1, leaseOwnerPid: process.pid,
    source: 'runtime/im_env_reset_20261008.mjs', productionActions: 0,
  };
  fs.writeFileSync(ATTEMPT, JSON.stringify(attempt, null, 2) + '\n', {flag:'wx'});
  const result = await resetIM();
  console.log(JSON.stringify({attempted:true, result}));
  process.exitCode = result.ok ? 0 : 4;
} finally {
  await releasePostLease(lease);
}
