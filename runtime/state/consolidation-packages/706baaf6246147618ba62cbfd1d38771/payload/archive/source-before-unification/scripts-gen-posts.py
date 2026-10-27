#!/usr/bin/env python3
# 生成 taobao-brand-post(9230) / taobao-svc-post(9231) / meituan-post(9233) 三个岗位包。
import os, json, hashlib

BASE = '/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/skills/posts'
NODE_SYMLINK = '/Users/ddt/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules'

POSTS = {
    'taobao-brand-post': dict(port=9230, platform='淘宝闪购·商家版', desc='淘宝品牌商工位：单店数据/活动三项核验。'),
    'taobao-svc-post':   dict(port=9231, platform='淘宝闪购·服务商平台', desc='淘宝服务商工位：意向商户游标增量采集。'),
    'meituan-post':      dict(port=9233, platform='美团·商家端', desc='美团工位：商家端只读客服诉求。'),
}

CONNECT_TPL = """import {chromium} from 'playwright-core';
// 连接本岗位专用工位（端口固定）。登录态/遮罩/业务判定交给调用方（流水线），本文件只负责「连到正确的浏览器」。
const PORT = __PORT__;
export async function connectToPost() {
  const browser = await chromium.connectOverCDP(`http://127.0.0.1:${PORT}`);
  const context = browser.contexts()[0];
  if (!context) throw Error('post-__NAME__-context-missing');
  const page = context.pages()[0] || await context.newPage();
  return { browser, context, page };
}
"""

LEASE_TPL = """import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';

// __NAME__ 工位互斥锁（L2 物理互斥）：锁路径按端口区分，使不同工位可并发、同工位多流水线互斥。
const DEFAULT_LEASE_PATH = '/tmp/zhensi-post-__PORT__.lock';
const DEFAULT_LEASE_TTL_MS = 30 * 60 * 1000;

export async function acquirePostLease(runId, leasePath = DEFAULT_LEASE_PATH, ttlMs = DEFAULT_LEASE_TTL_MS) {
  const now = Date.now();
  let existing = null;
  try { existing = JSON.parse(await fs.readFile(leasePath, 'utf8')); } catch {}
  if (existing) {
    const age = now - (existing.acquiredAt || 0);
    const stale = age > ttlMs;
    const ownerMismatch = existing.runId !== runId;
    if (!stale && ownerMismatch) throw Error(`post-__PORT__-lease-busy:${existing.runId}`);
    if (!stale) throw Error(`post-__PORT__-lease-held:${existing.runId}`);
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
"""

VERIFY_TPL = """#!/usr/bin/env node
// __NAME__ 岗位封印校验器（scripts/verify_dependencies.mjs）。node verify_dependencies.mjs → 一致退出 0。
import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const SKILL_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const MANIFEST = path.join(SKILL_DIR, 'dependencies.json');

async function sha256(file) { return crypto.createHash('sha256').update(await fs.readFile(file)).digest('hex'); }
async function main() {
  const manifest = JSON.parse(await fs.readFile(MANIFEST, 'utf8'));
  const mismatches = [];
  for (const [file, expected] of Object.entries(manifest.files || {})) {
    const resolved = path.isAbsolute(file) ? file : path.join(SKILL_DIR, file);
    const actual = await sha256(resolved);
    if (actual !== expected) mismatches.push({ file, expected, actual });
  }
  const result = { ok: mismatches.length === 0, status: mismatches.length === 0 ? 'clean' : 'drift', fileCount: Object.keys(manifest.files || {}).length, mismatches };
  console.log(JSON.stringify(result, null, 2));
  if (mismatches.length > 0) process.exitCode = 1;
}
main().catch(error => { console.error(JSON.stringify({ ok: false, status: 'blocked', reason: String(error.message || error) })); process.exitCode = 1; });
"""

SKILL_TPL = """# 岗位：__NAME__（__PLATFORM__）

> 状态：已实体化为独立岗位（2026-09-30 岗位实体化方案 / L2）。本目录是「__PLATFORM__」的**专人专岗**，
> 流水线（skills/ 下的工作流）只调用本岗，不自己连接浏览器。

## 工位（端口）
- **__PORT__**（`http://127.0.0.1:__PORT__`）——__DESC__

## 职责边界（软件功能内聚）
- **本岗负责（通用）**：连到正确的工位浏览器（`connect.mjs`）、工位互斥锁（`lease.mjs`，锁路径 `/tmp/zhensi-post-__PORT__.lock`）。
- **流水线负责（专属）**：登录态校验、遮罩处理、分页核对、业务抽取——保持在工作流逻辑内，不进本岗。

## 接口契约
- `connectToPost()` → `{browser, context, page}`：连接本工位；无 context 抛 `post-__NAME__-context-missing`。
- `acquirePostLease(runId)` / `releasePostLease(lease)`：工位互斥。持有锁时其他同端口流水线抛 `post-__PORT__-lease-busy:<runId>`。
- 互斥语义（L2）：不同工位（端口）可并发；同一工位多流水线强制串行。

## 自封印
- `dependencies.json` 钉死本岗文件 sha256；`verify_dependencies.mjs` 校验。改动本岗任何被钉文件须走受控流程重算。
"""


def fill(tpl, **kw):
    out = tpl
    for k, v in kw.items():
        out = out.replace('__%s__' % k.upper(), str(v))
    return out


for name, cfg in POSTS.items():
    port, platform, desc = cfg['port'], cfg['platform'], cfg['desc']
    pdir = os.path.join(BASE, name)
    sdir = os.path.join(pdir, 'scripts')
    os.makedirs(sdir, exist_ok=True)
    link = os.path.join(sdir, 'node_modules')
    if not os.path.islink(link):
        os.symlink(NODE_SYMLINK, link)
    # SKILL.md 在岗位根目录；其余脚本在 scripts/（与 jinsha-post 布局一致，verify_dependencies 按岗位根解析）。
    skill_md = fill(SKILL_TPL, name=name, platform=platform, port=port, desc=desc)
    with open(os.path.join(pdir, 'SKILL.md'), 'w') as fh:
        fh.write(skill_md)
    scripts = {
        'connect.mjs': fill(CONNECT_TPL, name=name, port=port),
        'lease.mjs':   fill(LEASE_TPL, name=name, port=port),
        'verify_dependencies.mjs': fill(VERIFY_TPL, name=name),
    }
    for fn, content in scripts.items():
        with open(os.path.join(sdir, fn), 'w') as fh:
            fh.write(content)
    manifest = {'schemaVersion': 1, 'sealedAt': '2026-09-30T00:0x+08:00',
                'authorizationRef': 'user-20260930-%s-establishment' % name, 'files': {}}
    manifest['files']['SKILL.md'] = hashlib.sha256(open(os.path.join(pdir, 'SKILL.md'), 'rb').read()).digest().hex()
    for fn in ['connect.mjs', 'lease.mjs', 'verify_dependencies.mjs']:
        manifest['files']['scripts/' + fn] = hashlib.sha256(open(os.path.join(sdir, fn), 'rb').read()).digest().hex()
    with open(os.path.join(pdir, 'dependencies.json'), 'w') as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)
        fh.write('\n')
    print('%s: port=%s files=%d' % (name, port, len(manifest['files'])))
print('生成完成')
