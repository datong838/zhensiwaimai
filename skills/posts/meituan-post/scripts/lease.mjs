// Physical ownership is serialized; a live/unknown PID remains busy beyond TTL.
import {acquire, release} from '../../shared/lease_core.mjs';
const DEFAULT_LEASE_PATH = '/tmp/zhensi-post-9233.lock';
const DEFAULT_LEASE_TTL_MS = 30 * 60 * 1000;
export async function acquirePostLease(runId, leasePath = DEFAULT_LEASE_PATH, ttlMs = DEFAULT_LEASE_TTL_MS) {
  const result = acquire(runId, leasePath);
  return result.status === 'acquired' ? {...result.lease, leasePath} : null;
}
export async function releasePostLease(lease) {
  if (!lease) return false;
  try { return release(lease, lease.leasePath).status === 'released'; }
  catch { return false; }
}
