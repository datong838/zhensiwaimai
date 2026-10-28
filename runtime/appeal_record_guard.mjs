import fs from 'node:fs/promises';
import { createHash } from 'node:crypto';

const STATES = new Set(['prepared', 'ready_for_confirmation', 'submitted_once', 'verified_submitted', 'skipped', 'blocked', 'unknown']);

export async function readAppealRecord(file) {
  try {
    if (!(await fs.lstat(file)).isFile()) return { exists: true, status: 'unrecognized', file, reason: 'not-regular-file' };
    const bytes = await fs.readFile(file);
    const matches = [...bytes.toString('utf8').matchAll(/^- 记录状态：([^\n\r]*)/gm)];
    const status = matches.length === 1 ? matches[0][1].trim() : '';
    return { exists: true, status: STATES.has(status) ? status : 'unrecognized', file,
      sha256: createHash('sha256').update(bytes).digest('hex') };
  } catch (error) {
    if (error.code === 'ENOENT') return { exists: false, status: '', file };
    return { exists: true, status: 'unrecognized', file, reason: 'record-unreadable' };
  }
}

export function applyPriorAppealRecord(prior, receipt, key, { autoEnabledSkip = false } = {}) {
  if (prior?.exists === false) return 'proceed';
  const status = prior?.status;
  receipt.recordReadbacks ??= [];
  receipt.recordReadbacks.push({ key, status, file: prior?.file, sha256: prior?.sha256, readOnly: true });
  if (status === 'verified_submitted' || status === 'blocked') {
    receipt[status].push(key);
    return 'read-only';
  }
  if (status === 'skipped' && autoEnabledSkip) {
    receipt.skipped.push(key);
    return 'read-only';
  }
  if (['prepared', 'ready_for_confirmation', 'skipped'].includes(status)) return 'proceed';
  receipt.unknown.push(key);
  receipt.warnings.push('prior-record-read-only:' + String(status || 'unrecognized') + ':' + key);
  return 'stop';
}
