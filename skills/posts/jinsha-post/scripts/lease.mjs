// Physical ownership is serialized by the original post lease broker.
import {acquire, release} from '../../shared/lease_core.mjs';
const DEFAULT_LEASE_PATH = '/tmp/zhensi-jinsha-cua-exam.lock';
const DEFAULT_LEASE_TTL_MS = 30 * 60 * 1000;
export async function acquireJinshaLease(runId, leasePath = DEFAULT_LEASE_PATH, ttlMs = DEFAULT_LEASE_TTL_MS) {
  // ttlMs remains API-compatible; age never authorizes takeover of a live PID.
  const result = acquire(runId, leasePath, {style: 'jinsha', reentrant: false});
  if (result.status !== 'acquired') throw Error('jinsha-lease-busy:' + String(result.ownerRunId || 'unknown'));
  return {...result.lease, path: leasePath};
}
export async function releaseJinshaLease(lease) {
  if (!lease) return false;
  const result = release(lease, lease.path);
  if (result.status === 'mismatch') throw Error('jinsha-lease-owner-mismatch');
  return result.status === 'released';
}
