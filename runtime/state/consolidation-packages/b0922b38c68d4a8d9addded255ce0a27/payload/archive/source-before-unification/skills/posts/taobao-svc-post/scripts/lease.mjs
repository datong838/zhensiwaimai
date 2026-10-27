import fs from 'node:fs/promises';

// taobao-svc-post 工位互斥锁（L2 物理互斥）：锁路径按端口区分，使不同工位可并发、同工位多流水线互斥。
// 契约（对齐 daemon.acquire_post_group_lock → SKIPPED_BUSY）：
//   - 他人持有且未过期 → 返回 null（忙；调用方应跳过，绝不得驱动浏览器）
//   - 同 runId 重复获取 → 幂等返回现有租约
//   - 过期锁（> ttlMs）→ 覆盖自愈
//   - 无锁 → 写入并返回新租约
const DEFAULT_LEASE_PATH = '/tmp/zhensi-post-9231.lock';
const DEFAULT_LEASE_TTL_MS = 30 * 60 * 1000;

export async function acquirePostLease(runId, leasePath = DEFAULT_LEASE_PATH, ttlMs = DEFAULT_LEASE_TTL_MS) {
  const now = Date.now();
  let existing = null;
  try { existing = JSON.parse(await fs.readFile(leasePath, 'utf8')); } catch {}
  if (existing) {
    const age = now - (existing.acquiredAt || 0);
    const stale = age > ttlMs;
    const ownerMismatch = existing.runId !== runId;
    if (stale) {
      try { await fs.unlink(leasePath); } catch {}
    } else if (ownerMismatch) {
      return null; // 忙：调用方应跳过
    } else {
      return { ...existing, leasePath }; // 同 runId 幂等返回
    }
  }
  const lease = { runId, pid: process.pid, acquiredAt: now, leasePath };
  await fs.writeFile(leasePath, JSON.stringify(lease), { mode: 0o600 });
  return lease;
}

export async function releasePostLease(lease) {
  if (!lease) return false;
  try {
    const cur = JSON.parse(await fs.readFile(lease.leasePath, 'utf8'));
    if (cur.runId !== lease.runId) return false;
    await fs.unlink(lease.leasePath);
    return true;
  } catch { return false; }
}
