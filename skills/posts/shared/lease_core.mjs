import fs from 'node:fs';
import path from 'node:path';
import {spawnSync} from 'node:child_process';

const ROOT = path.resolve(import.meta.dirname, '../../..');
export function transact(request) {
  const manifest = JSON.parse(fs.readFileSync(path.join(ROOT, 'runtime/skills_manifest.json'), 'utf8'));
  const python = process.env.ZENSI_PYTHON || manifest.interpreters.python;
  if (typeof python !== 'string' || !python) throw Error('post-lease-python-unavailable');
  const result = spawnSync(python, [path.join(ROOT, 'runtime/post_lease_file.py')], {
    input: JSON.stringify(request), encoding: 'utf8', timeout: 5000, maxBuffer: 65536,
  });
  if (result.error) throw Error('post-lease-broker-failed:' + result.error.code);
  let receipt;
  try { receipt = JSON.parse(result.stdout); } catch { throw Error('post-lease-broker-no-receipt'); }
  if (result.status !== 0 || receipt.status === 'error') throw Error('post-lease-broker-failed:' + receipt.reason);
  return receipt;
}

export function acquire(runId, leasePath, {style = 'post', reentrant = true} = {}) {
  return transact({operation: 'acquire', path: leasePath, runId, pid: process.pid, style, reentrant});
}

export function release(lease, leasePath) {
  return transact({operation: 'release', path: leasePath, lease});
}
