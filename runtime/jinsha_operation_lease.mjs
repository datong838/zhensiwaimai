// Business entry wrapper; the original post remains the only physical lock owner API.
import { randomUUID } from 'node:crypto';
import { acquireJinshaLease, releaseJinshaLease } from '../skills/posts/jinsha-post/scripts/lease.mjs';

export async function withJinshaOperationLease(operation, {
  runId = 'appeal-operation-' + randomUUID(), acquire = acquireJinshaLease, release = releaseJinshaLease,
} = {}) {
  if (typeof operation !== 'function' || typeof acquire !== 'function' || typeof release !== 'function') {
    throw Error('jinsha-operation-lease-contract-invalid');
  }
  const lease = await acquire(runId);
  if (!lease) throw Error('jinsha-lease-busy');
  try { return await operation(); }
  finally { await release(lease); }
}
