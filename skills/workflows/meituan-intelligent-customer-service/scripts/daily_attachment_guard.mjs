// Read original attempts only. Never create a new event to retry an unknown.
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';

function dutySlot(clock) {
  if (!/^\d{6}$/.test(clock)) return null;
  const hour = Number(clock.slice(0, 2)), minute = Number(clock.slice(2, 4)), second = Number(clock.slice(4));
  if (hour > 23 || minute > 59 || second > 59) return null;
  return hour >= 17 ? 17 : hour >= 15 ? 15 : hour >= 12 ? 12 : null;
}

export async function checkDailyAttachmentAttempts({ ledger, group, date = new Date() }) {
  const day = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(date);
  const clock = new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Shanghai', hourCycle: 'h23', hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(date).replaceAll(':', '');
  const slot = dutySlot(clock);
  const base = { runDate: day, slot, newSendAttempts: 0, readOnly: true };
  const blocked = (reason, evidence = {}) => ({ ...base, ok: false, status: 'unknown', reason, ...evidence });
  if (slot === null) return blocked('customer-attachment-no-current-duty');
  let names;
  try { names = await fs.readdir(ledger); }
  catch (error) { if (error.code === 'ENOENT') return { ...base, ok: true }; throw error; }
  const prefix = `meituan-customer-reply-daily-${day}`;
  for (const name of names.sort()) {
    if (!name.startsWith(prefix) || !name.endsWith('.json')) continue;
    const suffix = name.slice(prefix.length, -5);
    // Unclassifiable same-day names are not proof of an independent old duty.
    const stamp = /^-\d{6}$/.test(suffix) ? suffix.slice(1) : null;
    if (stamp && dutySlot(stamp) !== null && dutySlot(stamp) < slot) continue;
    const file = path.join(ledger, name);
    if ((await fs.lstat(file)).isSymbolicLink()) return blocked('customer-attachment-attempt-symlink', { sourcePath: file });
    let bytes, prior;
    try { bytes = await fs.readFile(file); prior = JSON.parse(bytes); }
    catch (error) { return blocked('customer-attachment-attempt-unreadable', { sourcePath: file }); }
    const evidence = { sourcePath: file, sourceSha256: crypto.createHash('sha256').update(bytes).digest('hex'), priorState: prior?.state };
    const payloads = prior?.payloads;
    if (prior?.groupName !== group || prior.payloadType !== 'file' || !Array.isArray(payloads)
        || payloads.length !== 1 || payloads[0]?.name !== `美团客户回复记录-${day}.xlsx`)
      return blocked('customer-attachment-attempt-binding-conflict', evidence);
    if (prior.state === 'verified') continue;
    if (prior.state === 'blocked' && Number.isInteger(prior.sendAttempts) && prior.sendAttempts === 0) continue;
    return blocked('customer-attachment-prior-attempt-read-only-no-new-event', evidence);
  }
  return { ...base, ok: true };
}
