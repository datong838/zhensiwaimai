// 收口烟测（smoke test）：验证岗位实体化重构后的接线 + 互斥锁 + 封印，全部离线、零发送。
//
// 规则（大同 2026-10-01）：测试脚本不允许执行正规生产流程；只允许发到「臻肆测试群」。
// 因此本测试：
//   ① 绝不调用 connectToPost()（不连真浏览器 CDP）；
//   ② 绝不调用任何发送器 / --execute；
//   ③ 只做：模块解析 + 租约锁离线往返 + daemon --selftest + 封印校验。
// 顶部 import 隔离闸门后，测试进程内任何真实发送/外连都会直接抛错（能力隔离，不靠约定）。

import './isolation_guard.mjs'; // 顶部安装硬闸门（必须最先 import，确保后续 child_process 捕获的是已打补丁版本）

import { execFile as execFileCb } from 'node:child_process';
import { promisify } from 'node:util';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { dirname, join, resolve } from 'node:path';
import { unlinkSync } from 'node:fs';

const execFile = promisify(execFileCb);
const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, '..');
const NODE = process.execPath;
// 默认用 managed Python（与 daemon 生产解释器一致）；可用 ZHS_PYTHON 覆盖。
const PYTHON = process.env.ZHS_PYTHON ||
  '/Users/ddt/.workbuddy/binaries/python/versions/3.13.12/bin/python3';

const POSTS = [
  { name: 'taobao-brand-post', port: 9230 },
  { name: 'taobao-svc-post', port: 9231 },
  { name: 'meituan-post', port: 9233 },
];
const POST_LOCKS = POSTS.map((p) => `/tmp/zhensi-post-${p.port}.lock`);

let pass = 0;
let fail = 0;
const fails = [];
function record(ok, label, err) {
  if (ok) { pass++; console.log(`  [OK] ${label}`); }
  else { fail++; fails.push(`${label}${err ? ' → ' + err.message : ''}`); console.log(`  [FAIL] ${label}${err ? ' → ' + err.message : ''}`); }
}

async function run() {
  // 0) 清理可能的残留锁（/tmp，非生产目录），保证烟测可重复
  for (const lk of POST_LOCKS) { try { unlinkSync(lk); } catch { /* 不存在即忽略 */ } }

  // 1) 三新岗模块解析 + 租约锁离线往返
  for (const post of POSTS) {
    const base = join(ROOT, 'skills', 'posts', post.name, 'scripts');
    try {
      const lease = await import(join(base, 'lease.mjs'));
      assert.equal(typeof lease.acquirePostLease, 'function');
      assert.equal(typeof lease.releasePostLease, 'function');
      const connect = await import(join(base, 'connect.mjs'));
      assert.equal(typeof connect.connectToPost, 'function');

      const idA = `smoke-${post.port}-${Date.now()}-A`;
      const idB = `smoke-${post.port}-${Date.now()}-B`;
      const lA = await lease.acquirePostLease(idA);
      const held = lA && lA.runId === idA;
      const busy = await lease.acquirePostLease(idB); // 同岗同锁，应 busy → null
      await lease.releasePostLease(lA).catch(() => {});
      const lC = await lease.acquirePostLease(`smoke-${post.port}-${Date.now()}-C`);
      await lease.releasePostLease(lC).catch(() => {});
      record(held && busy === null && lC && lC.runId, `${post.name}: 模块解析 + 租约往返(获取/忙/释放/再获取)`);
    } catch (e) {
      record(false, `${post.name}: 模块解析 + 租约往返`, e);
    }
  }

  // 2) daemon --selftest（含 W2 互斥锁、W4 熔断块）必须 ALL PASS
  try {
    const { stdout } = await execFile(PYTHON, [join(ROOT, 'runtime', 'run_all.py'), '--selftest'],
      { cwd: ROOT, maxBuffer: 1 << 20 });
    record(/ALL PASS/.test(stdout), 'daemon --selftest ALL PASS', new Error(stdout.split('\n').slice(-6).join(' | ')));
  } catch (e) {
    record(false, 'daemon --selftest ALL PASS', e);
  }

  // 3) 四岗 verify_dependencies 必须 clean（金鲨 5 文件 + 三新岗各 4 文件）
  const allPosts = [...POSTS.map((p) => p.name), 'jinsha-post'];
  for (const name of allPosts) {
    try {
      const { stdout } = await execFile(NODE, [join(ROOT, 'skills', 'posts', name, 'scripts', 'verify_dependencies.mjs')],
        { cwd: ROOT, maxBuffer: 1 << 20 });
      const doc = JSON.parse(stdout);
      record(doc.ok === true && doc.status === 'clean', `${name}: verify_dependencies clean (${doc.fileCount} files)`,
        new Error(JSON.stringify(doc.mismatches || {})));
    } catch (e) {
      record(false, `${name}: verify_dependencies clean`, e);
    }
  }

  console.log(`\n烟测结论：PASS ${pass} / FAIL ${fail}${fail ? ' → ' + fails.join('; ') : ''}`);
  process.exit(fail ? 1 : 0);
}

run().catch((e) => { console.error('烟测异常：', e); process.exit(2); });
