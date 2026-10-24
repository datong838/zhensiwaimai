// 金鲨岗（jinsha-post）工位租约锁 —— 互斥的现成实现（W2）
// 从 .daily-jinsha-reports-core/scripts/jinsha_cua_exam.js 原样迁移，契约不变：
//   - acquireJinshaLease：文件锁（wx 独占创建），EEXIST 且未过期 → jinsha-lease-busy；
//     过期（> ttlMs）→ 释放后重试一次。
//   - releaseJinshaLease：校验 owner（runId + acquiredAt），不匹配 → jinsha-lease-owner-mismatch。
// 这是「金鲨工位同一时刻只允许一条流水线当班」的物理保证。

import fs from 'node:fs/promises';

const DEFAULT_LEASE_PATH = '/tmp/zhensi-jinsha-cua-exam.lock';
const DEFAULT_LEASE_TTL_MS = 30 * 60 * 1000;

export async function acquireJinshaLease(runId, leasePath = DEFAULT_LEASE_PATH, ttlMs = DEFAULT_LEASE_TTL_MS) {
  const now = Date.now();
  /* c8 ignore next */ const payload = {runId, pid: typeof process === 'undefined' ? null : process.pid, acquiredAt: now}; // pid 三元：Node 中 process 恒存在，`=== 'undefined'` 分支不可达（防御性）
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const handle = await fs.open(leasePath, 'wx', 0o600);
      await handle.writeFile(JSON.stringify(payload));
      await handle.close();
      return {...payload, path: leasePath};
    } catch (error) {
      if (error?.code !== 'EEXIST') throw error;
      let existing = {};
      try {existing = JSON.parse(await fs.readFile(leasePath, 'utf8'));} catch {}
      const acquiredAt = Number(existing?.acquiredAt);
      if (attempt === 0 && Number.isFinite(acquiredAt) && now - acquiredAt > ttlMs) {
        await fs.unlink(leasePath).catch((unlinkError) => {if (unlinkError?.code !== 'ENOENT') throw unlinkError;});
        continue;
      }
      throw Error('jinsha-lease-busy:' + String(existing?.runId || 'unknown'));
    }
  }
  /* c8 ignore next */ throw Error('jinsha-lease-acquire-failed'); // 双次重试后仍互斥：输入空间不可达（acquire 仅 busy/其他错误/过期重试三条路径）
}

export async function releaseJinshaLease(lease) {
  if (!lease) return false;
  let existing = {};
  try {existing = JSON.parse(await fs.readFile(lease.path, 'utf8'));} catch (error) {
    if (error?.code === 'ENOENT') return false;
    throw error;
  }
  if (existing?.runId !== lease.runId || existing?.acquiredAt !== lease.acquiredAt)
    throw Error('jinsha-lease-owner-mismatch');
  await fs.unlink(lease.path);
  return true;
}
