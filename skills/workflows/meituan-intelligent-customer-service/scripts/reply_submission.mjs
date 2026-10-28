import fs from 'node:fs/promises';
import path from 'node:path';
import { createHash, randomUUID } from 'node:crypto';

const digest = value => createHash('sha256').update(value).digest('hex');

export function replyBinding({ sessionId, customerText, reply }) {
  if (typeof sessionId !== 'string' || !/^\d{19}$/.test(sessionId)
      || typeof customerText !== 'string' || !customerText.trim() || customerText.length > 400
      || typeof reply !== 'string' || !reply.trim()) throw Error('reply-submission-binding-invalid');
  return { schemaVersion: 1, workflowId: 'meituan-customer-reply', port: 9233,
    sessionSha256: digest(sessionId), customerTextSha256: digest(customerText), replySha256: digest(reply) };
}

function intentPath(root, binding) {
  for (const key of ['sessionSha256', 'customerTextSha256', 'replySha256']) {
    if (!/^[0-9a-f]{64}$/.test(binding[key] || '')) throw Error('reply-submission-hash-invalid');
  }
  return path.join(root, binding.sessionSha256, binding.customerTextSha256 + '.json');
}

export async function inspectReplySubmission(root, binding) {
  const file = intentPath(root, binding);
  let bytes;
  try {
    if (!(await fs.lstat(file)).isFile()) throw Error('not-regular-file');
    bytes = await fs.readFile(file, 'utf8');
  } catch (error) {
    if (error.code === 'ENOENT') return null;
    return { state: 'blocked', reason: 'prior-reply-submission-unreadable', readOnly: true };
  }
  try {
    const previous = JSON.parse(bytes);
    if (!Object.entries(binding).every(([k, v]) => previous[k] === v)
        || !['attempted', 'unknown', 'verified'].includes(previous.state)) throw Error('binding-or-state');
    return { state: previous.state, reason: 'prior-reply-submission-read-only', readOnly: true,
      file, sha256: digest(bytes), verifiedBy: previous.verifiedBy ?? null };
  } catch {
    return { state: 'blocked', reason: 'prior-reply-submission-invalid', readOnly: true,
      file, sha256: digest(bytes) };
  }
}

export function assertReplyDraft(actual, expected) {
  if (actual !== expected) throw Error(expected === '' ? 'composer-not-empty' : 'reply-draft-fulltext-mismatch');
}

export async function submitReplyOnce(root, request, send, verify) {
  if (typeof send !== 'function' || typeof verify !== 'function') throw Error('reply-submission-callback-required');
  const binding = replyBinding(request);
  const prior = await inspectReplySubmission(root, binding);
  if (prior) return { ...prior, newSubmitCalls: 0 };
  const file = intentPath(root, binding);
  await fs.mkdir(path.dirname(file), { recursive: true, mode: 0o700 });
  for (const folder of [root, path.dirname(file)]) {
    if (!(await fs.lstat(folder)).isDirectory() || (await fs.lstat(folder)).isSymbolicLink()) {
      throw Error('reply-submission-directory-invalid');
    }
  }
  const intent = { ...binding, intentId: randomUUID(), state: 'attempted',
    createdAt: new Date().toISOString(), date: new Intl.DateTimeFormat('en-CA', {
      timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date()) };
  const bytes = JSON.stringify(intent, null, 2) + '\n';
  let handle;
  try {
    handle = await fs.open(file, 'wx', 0o600);
  } catch (error) {
    if (error.code !== 'EEXIST') throw error;
    return { ...(await inspectReplySubmission(root, binding)), newSubmitCalls: 0, readOnly: true };
  }
  try { await handle.writeFile(bytes); await handle.sync(); } finally { await handle.close(); }
  let verifiedBy = null;
  let reason = 'reply-submission-awaits-read-only-verification';
  try {
    await send(); // Exactly one submission call. Any exception is uncertain; never retry.
    const proof = await verify();
    if (['echo', 'list-gone'].includes(proof)) verifiedBy = proof;
  } catch { reason = 'reply-submission-or-verification-exception'; }
  const result = { ...intent, state: verifiedBy ? 'verified' : 'unknown', verifiedBy,
    reason: verifiedBy ? null : reason, newSubmitCalls: 1 };
  if (await fs.readFile(file, 'utf8') !== bytes) throw Error('reply-submission-owner-changed');
  const temporary = file + '.' + intent.intentId + '.tmp';
  const writer = await fs.open(temporary, 'wx', 0o600);
  try { await writer.writeFile(JSON.stringify(result, null, 2) + '\n'); await writer.sync(); }
  finally { await writer.close(); }
  await fs.rename(temporary, file);
  return { ...result, file, readOnly: false };
}
