#!/usr/bin/env node
// zhensi_waimai_back Node 端单元测试 + c8 覆盖率（目标：代码覆盖率 + 逻辑覆盖率均 ≥98%）。
// 覆盖：
//   lease.mjs（4 岗，各自契约不同：3 简单岗 busy→null + 同 runId 幂等；jinsha 岗 busy→throw + owner-mismatch→throw）
//   connect.mjs（3 简单岗 connectToPost；jinsha 岗 connectJinsha + 页面断言助手）
//   verify_dependencies.mjs（4 岗真实 sealed 均 clean + meituan/jinsha fixture 副本覆盖 drift/bad-json/绝对路径分支）
//   business_workflow_executor.mjs（纯函数 + 证明校验 + 状态机全 phase + executeRun 尾段 + main）
// 全部离线、零生产副作用：lease/connect/executor 用临时文件；verify 用 fixture 副本子进程；
// executor 经 tests/shim_loader.mjs 把 playwright-core / policy 校验器 / child_process 全部重定向到可控桩，
// 并把 FIXED.runsRoot 指向临时目录（allocateRun/loadRun/attemptMarker 全变 hermetic）。
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {mkdtempSync} from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {fileURLToPath, pathToFileURL} from 'node:url';

const execFileP = promisify(execFile);
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const SIMPLE_POSTS = ['meituan-post', 'taobao-brand-post', 'taobao-svc-post'];
const JINSHA_POST = 'jinsha-post';

// executor 的 policy 由 shim_loader 在导入时把 FIXED.runsRoot 重定向到本临时目录（hermetic）
globalThis.__TEST_RUNS_ROOT__ = mkdtempSync(path.join(os.tmpdir(), 'zhensi-runs-'));

// e2e 测试串行化：所有 e2e 测试共享 globalThis.__EXEC_EXEC_FILE__（受控桩），
// 而 node --test 默认并发执行子测试，会导致互相污染。用互斥链把 e2e 测试逐个串行化。
let _execChain = Promise.resolve();
function withExecLock(body) {
  const run = _execChain.then(() => body());
  _execChain = run.then(() => {}, () => {});
  return run;
}
function e2eTest(name, fn) {
  return test(name, async () => withExecLock(() => fn()));
}

// connect.mjs 测试串行化：connectToPost/connectJinsha 经 shim 调用 chromium.connectOverCDP，
// 而缺 context（抛错）/ 空 pages（→newPage）分支需临时覆盖 globalThis.__TEST_CONNECT_OVERRIDE__；
// node --test 默认并发，故所有 connect 测试经同一互斥链串行化，避免全局覆盖互相踩踏。
let _connectChain = Promise.resolve();
function withConnectLock(body) {
  const run = _connectChain.then(() => body());
  _connectChain = run.then(() => {}, () => {});
  return run;
}

const POLICY = path.join(ROOT, 'skills/workflows/daily-jinsha-reports-to-business-wechat/scripts/business_workflow_policy.mjs');
const EXEC = path.join(ROOT, 'skills/workflows/daily-jinsha-reports-to-business-wechat/scripts/business_workflow_executor.mjs');

// 真实 policy（测试自身直接导入，绕过 shim 的 executor-only 注入），取真实 FIXED/PLATFORMS/buildProductionConfig 等
const _policy = await import(POLICY);
const {FIXED, PLATFORMS, buildProductionConfig, previousBusinessDate, desktopAttemptIdentity} = _policy;

function tmpDir(prefix) { return fs.mkdtemp(path.join(os.tmpdir(), prefix)); }
async function writeJson(p, v) { await fs.mkdir(path.dirname(p), {recursive: true}); await fs.writeFile(p, JSON.stringify(v, null, 2), {mode: 0o600}); }
async function readJsonOptional(p){ try { return JSON.parse(await fs.readFile(p, 'utf8')); } catch { return null; } }
function shaOf(buf){ return crypto.createHash('sha256').update(buf).digest('hex'); }
async function fileId(p){ const b = await fs.readFile(p); return {file: p, name: path.basename(p), size: b.length, sha256: shaOf(b)}; }

// 计算 attemptMarker 落盘的 marker 路径（基于临时 runsRoot，hermetic）
function markerDirPath(){ return path.join(globalThis.__TEST_RUNS_ROOT__, '..', '..', 'state', 'jinsha-report-send-shanghai-zhensi-operations-ding-fandang-reauthorized-20260917-v2.desktop-attempts'); }
async function writeMarker(cfgPreflightPath, markerBody){
  const files = {meituan: {sha256: 'm-sha-'+Math.random()}, taobao: {sha256: 't-sha-'+Math.random()}};
  await writeJson(cfgPreflightPath, {ok: true, files});
  const identity = desktopAttemptIdentity(FIXED.group, [files.meituan, files.taobao]);
  const dir = markerDirPath(); await fs.mkdir(dir, {recursive: true});
  const p = path.join(dir, `${identity}.json`);
  await writeJson(p, markerBody);
  return p;
}
async function rmMarker(p){ await fs.rm(p, {force: true}); }

// ============================================================ lease.mjs（3 简单岗）
for (const post of SIMPLE_POSTS) {
  test(`lease[${post}] 全分支`, async () => {
    const mod = await import(path.join(ROOT, `skills/posts/${post}/scripts/lease.mjs`));
    const dir = await tmpDir(`lease-${post}-`);
    const lock = path.join(dir, 'lease.lock');
    const a = await mod.acquirePostLease('runA', lock);
    assert.ok(a && a.leasePath === lock);
    const a2 = await mod.acquirePostLease('runA', lock); // 同 runId 幂等
    assert.ok(a2);
    assert.strictEqual(await mod.acquirePostLease('runB', lock), null); // 他人持有 → 忙
    assert.strictEqual(await mod.releasePostLease(a), true);
    assert.strictEqual(await mod.releasePostLease({...a}), false); // 已删除
    await fs.writeFile(lock, JSON.stringify({runId: 'old', acquiredAt: 0})); // 过期锁
    const b = await mod.acquirePostLease('runC', lock);
    assert.ok(b);
    assert.strictEqual(await mod.releasePostLease({runId: 'OTHER', leasePath: lock}), false); // owner 不匹配
    await mod.releasePostLease(b);
    assert.strictEqual(await mod.releasePostLease(null), false);
    await fs.writeFile(lock, 'not-json{{'); // 损坏锁 → 当作无锁重写
    const c = await mod.acquirePostLease('runD', lock);
    assert.ok(c);
    await mod.releasePostLease(c);
  });
}

// lease.mjs（3 简单岗）：过期锁且 unlink 失败 → 空 catch 吞掉（覆盖 L21 空 catch 分支）
// 构造：父目录去写权限 + 锁文件只读 → readFile 可读（解析出 stale）但 unlink/writeFile 均 EACCES（被吞 / 抛错）
for (const post of SIMPLE_POSTS) {
  test(`lease[${post}] 过期锁 unlink 失败被空 catch 吞（覆盖空 catch 分支）`, async () => {
    const mod = await import(path.join(ROOT, `skills/posts/${post}/scripts/lease.mjs`));
    const parent = await tmpDir(`lease-ro-${post}-`);
    const lock = path.join(parent, 'lease.lock');
    await fs.writeFile(lock, JSON.stringify({runId: 'old', acquiredAt: 0}), {mode: 0o400}); // 过期锁 + 文件只读
    await fs.chmod(parent, 0o500); // 父目录去写权限：unlink 子文件 EACCES；readFile 因 x 权限仍可；writeFile 因文件只读 EACCES
    try {
      await assert.rejects(async () => mod.acquirePostLease('runC', lock), /EACCES|EPERM/);
    } finally {
      await fs.chmod(parent, 0o700); await fs.chmod(lock, 0o600);
    }
  });
}

// ============================================================ lease.mjs（jinsha 岗：互斥契约）
test('lease[jinsha-post] 全分支（互斥 + owner 校验）', async () => {
  const mod = await import(path.join(ROOT, `skills/posts/${JINSHA_POST}/scripts/lease.mjs`));
  const dir = await tmpDir('lease-jinsha-');
  const lock = path.join(dir, 'lease.lock');
  const a = await mod.acquireJinshaLease('runA', lock); // 无锁 → 新建
  assert.ok(a && a.path === lock);
  await assert.rejects(async () => mod.acquireJinshaLease('runA', lock), /jinsha-lease-busy/); // 同 runId 不幂等 → 忙
  await assert.rejects(async () => mod.acquireJinshaLease('runB', lock), /jinsha-lease-busy/); // 他人持有 → 忙
  await assert.rejects(async () => mod.releaseJinshaLease({runId: 'OTHER', acquiredAt: Date.now(), path: lock}), /jinsha-lease-owner-mismatch/); // owner 不匹配
  assert.strictEqual(await mod.releaseJinshaLease(a), true);
  assert.strictEqual(await mod.releaseJinshaLease({...a}), false); // 已删除
  await fs.writeFile(lock, JSON.stringify({runId: 'old', pid: 9, acquiredAt: 0})); // 过期锁 → 释放后重试
  const b = await mod.acquireJinshaLease('runC', lock);
  assert.ok(b);
  await mod.releaseJinshaLease(b);
  assert.strictEqual(await mod.releaseJinshaLease(null), false);
  await fs.writeFile(lock, 'not-json{{'); // 损坏锁 → 解析失败被吞 → 当作忙碌
  await assert.rejects(async () => mod.acquireJinshaLease('runD', lock), /jinsha-lease-busy/);
});

// jinsha lease：releaseJinshaLease 读锁文件抛【非 ENOENT】错误（目录路径 → EISDIR）→ 抛出（覆盖 L42-43）
test('lease[jinsha-post] releaseJinshaLease 非 ENOENT 错误抛出（覆盖 L42-43）', async () => {
  const mod = await import(path.join(ROOT, `skills/posts/${JINSHA_POST}/scripts/lease.mjs`));
  const dir = await tmpDir('lease-jinsha-nonenoent-'); // 目录作为锁路径 → readFile 抛 EISDIR（非 ENOENT）
  await assert.rejects(async () => mod.releaseJinshaLease({runId: 'X', acquiredAt: 0, path: dir}), /EISDIR|EACCES/);
});

// jinsha lease：acquireJinshaLease 非 EEXIST 抛错（L23）+ 已存在但不可读锁被空 catch 吞（L15）
test('lease[jinsha-post] acquireJinshaLease 非 EEXIST 抛错（L23）+ 锁不可读被吞（L15）', async () => {
  const mod = await import(path.join(ROOT, `skills/posts/${JINSHA_POST}/scripts/lease.mjs`));
  const dir = await tmpDir('lease-jinsha-acquire-');
  // 父目录不存在 → fs.open('wx') 抛 ENOENT（非 EEXIST）→ L23 throw error
  await assert.rejects(async () => mod.acquireJinshaLease('runX', path.join(dir, 'nope', 'lock')), /ENOENT/);
  // 存在但不可读（0o000）的锁文件 → fs.open EEXIST → L15 readFile 抛 EACCES 被空 catch 吞 → 当作无租约 → busy
  const lock = path.join(dir, 'lock');
  await fs.writeFile(lock, JSON.stringify({runId: 'old', acquiredAt: 0}), {mode: 0o000});
  try {
    await assert.rejects(async () => mod.acquireJinshaLease('runX', lock), /jinsha-lease-busy/);
  } finally {
    await fs.chmod(lock, 0o600);
  }
});

// ============================================================ connect.mjs（3 简单岗）
for (const post of SIMPLE_POSTS) {
  test(`connect[${post}] 连接成功`, async () => withConnectLock(async () => {
    const mod = await import(path.join(ROOT, `skills/posts/${post}/scripts/connect.mjs`));
    const r = await mod.connectToPost();
    assert.ok(r.browser && r.context && r.page && r.page.fake === 'page');
  }));
}

// connect.mjs（3 简单岗）：缺 context 抛错 + 空 pages→newPage 分支（覆盖 L7 if(!context) 与 L8 `|| newPage` 假分支）
test('connect[3 简单岗] 缺 context 抛错 + 空 pages→newPage 分支', async () => {
  await withConnectLock(async () => {
    for (const post of SIMPLE_POSTS) {
      const mod = await import(path.join(ROOT, `skills/posts/${post}/scripts/connect.mjs`));
      try {
        globalThis.__TEST_CONNECT_OVERRIDE__ = {contexts: () => [null]};
        await assert.rejects(async () => mod.connectToPost(), /post-.*-context-missing/);
        globalThis.__TEST_CONNECT_OVERRIDE__ = {contexts: () => [{pages: () => [], newPage: async () => ({fake: 'newPage'})}]};
        const r = await mod.connectToPost();
        assert.strictEqual(r.page.fake, 'newPage');
      } finally {
        delete globalThis.__TEST_CONNECT_OVERRIDE__;
      }
    }
  });
});

// ============================================================ connect.mjs（jinsha 岗：连接 + 页面断言助手）
function makeJinshaPage(cfg = {}) {
  const getLoc = (sel) => {
    const c = (cfg.locators && cfg.locators[sel]) || {};
    const loc = {
      count: async () => (c.count ?? 0),
      isVisible: async () => (c.visible ?? false),
      innerText: async () => (c.text ?? ''),
      getAttribute: async () => (c.attr === null ? null : (c.attr ?? '')),
      evaluate: async () => undefined,
      click: async () => {},
      first: () => loc,
      locator: (s) => getLoc(s),
    };
    return loc;
  };
  return {
    title: async () => (cfg.title ?? '金鲨数据'),
    url: () => (cfg.url ?? 'https://data.guoshuyufen.com/dash'), // 注意：connect.mjs 以同步方式调用 page.url() 并立即 .includes，故此处必须返回字符串而非 Promise
    locator: (s) => getLoc(s),
    waitForFunction: async () => {},
    waitForTimeout: async () => {},
  };
}

test('connect[jinsha-post] connectJinsha + 页面断言助手', async () => withConnectLock(async () => {
  const mod = await import(path.join(ROOT, `skills/posts/${JINSHA_POST}/scripts/connect.mjs`));
  const browser = await mod.connectJinsha();
  assert.ok(browser && browser.contexts);

  assert.strictEqual(mod.assertJinshaOrigin('https://data.guoshuyufen.com/x'), true);
  await assert.rejects(async () => mod.assertJinshaOrigin('https://evil.com'), /jinsha-origin-changed/);

  assert.strictEqual(await mod.assertAuthenticated(makeJinshaPage({title: '金鲨数据'}), 'safe body'), true); // body 直传
  await assert.rejects(async () => mod.assertAuthenticated(makeJinshaPage({title: '金鲨数据'}), '需要 验证码'), /jinsha-authentication-required/);
  assert.strictEqual(await mod.assertAuthenticated(makeJinshaPage({title: '臻肆外卖运营', locators: {'body': {text: 'safe body'}}})), true); // body undefined → 读 locator
  await assert.rejects(async () => mod.assertAuthenticated(makeJinshaPage({title: '金鲨数据', url: 'https://data.guoshuyufen.com/#/login'}), 'x'), /jinsha-authentication-required/);
  await assert.rejects(async () => mod.assertAuthenticated(makeJinshaPage({title: '其他'}), 'x'), /jinsha-authentication-required/);

  const pgNoSidebar = makeJinshaPage({locators: {'.app-wrapper': {attr: 'app-wrapper'}}});
  const pgNullAttr = makeJinshaPage({locators: {'.app-wrapper': {attr: null}, '.drawer-bg:visible': {count: 0}}}); // getAttribute 返回 null → 覆盖 `|| ''` 假分支
  const pgDrawer0 = makeJinshaPage({locators: {'.app-wrapper': {attr: 'app-wrapper openSidebar'}, '.drawer-bg:visible': {count: 0}}});
  const pgDrawer1 = makeJinshaPage({locators: {'.app-wrapper': {attr: 'app-wrapper openSidebar'}, '.drawer-bg:visible': {count: 1}}});
  const pgDrawer2 = makeJinshaPage({locators: {'.app-wrapper': {attr: 'app-wrapper openSidebar'}, '.drawer-bg:visible': {count: 2}}});
  await mod.closeDrawer(pgNoSidebar); // 无 openSidebar → 返回
  await mod.closeDrawer(pgNullAttr); // getAttribute 返回 null → `|| ''` 假分支
  await mod.closeDrawer(pgDrawer0); // 遮罩 0 → 返回
  await mod.closeDrawer(pgDrawer1); // 遮罩 1 → 点击 + 等待
  await assert.rejects(async () => mod.closeDrawer(pgDrawer2), /drawer-overlay-count:2/);

  const pgNoOverlay = makeJinshaPage({locators: {'.upload .content': {count: 0}}});
  const pgOverlayOk = makeJinshaPage({locators: {'.upload .content': {count: 1, visible: true, text: '已知公告V5.6'}, '.close': {count: 1}}});
  const pgOverlayUnknown = makeJinshaPage({locators: {'.upload .content': {count: 1, visible: true, text: '神秘新弹窗'}}});
  const pgOverlay2 = makeJinshaPage({locators: {'.upload .content': {count: 2, visible: true, text: 'x'}}});
  assert.strictEqual(await mod.dismissAnnouncement(pgNoOverlay, ['已知公告'], 50), false); // 无遮罩 → false
  assert.strictEqual(await mod.dismissAnnouncement(pgOverlayOk, ['已知公告'], 50), true); // 白名单命中 → 关闭
  await assert.rejects(async () => mod.dismissAnnouncement(pgOverlayUnknown, ['已知公告'], 50), /unknown-page-overlay/);
  await assert.rejects(async () => mod.dismissAnnouncement(pgOverlay2, ['已知公告'], 50), /announcement-overlay-count:2/);
  await assert.rejects(async () => mod.dismissAnnouncement(makeJinshaPage({locators: {'.upload .content': {count: 1, visible: true, text: '已知公告'}, '.close': {count: 2}}}), ['已知公告'], 50), /announcement-close-not-unique:2/);
}));

// ============================================================ verify_dependencies.mjs（直接执行【真脚本】；离线 hermetic：临时 dependencies.json + 绝对/相对夹具，运行后备份还原）
// 关键：脚本由 import.meta.url 推导 SKILL_DIR = dirname/..，故必须执行真实脚本文件才能被 c8 计入覆盖；
// 旧实现把脚本复制到 /tmp 运行，导致真脚本覆盖率为 0。这里在真实 skill 目录临时落 dependencies.json
// （manifest 用绝对路径指向 tmp 夹具，不污染 skill 目录内容），运行后还原。三岗共享真实 skill 目录，用互斥锁串行化避免竞态。
let _verifyChain = Promise.resolve();
function withVerifyLock(body){const run=_verifyChain.then(()=>body());_verifyChain=run.then(()=>{},()=>{});return run;}
async function runRealVerify(post, files, expectFail){
  const script = path.join(ROOT, 'skills/posts', post, 'scripts', 'verify_dependencies.mjs');
  const manifestPath = path.join(ROOT, 'skills/posts', post, 'dependencies.json');
  const backup = await readJsonOptional(manifestPath);
  try {
    await writeJson(manifestPath, {files});
    const r = await execFileP(process.execPath, [script]).catch(e => e);
    if (expectFail) assert.ok((r.exitCode ?? r.code ?? 1) === 1 || String(r.stdout || r.stderr || '').includes('blocked'), `${post} 应失败: ${r.stdout || r.stderr}`);
    else assert.strictEqual(JSON.parse(r.stdout).status, 'clean', `${post}: ${r.stdout}`);
    return r;
  } finally {
    if (backup) await writeJson(manifestPath, backup); else await fs.rm(manifestPath, {force: true});
  }
}
// 与 runRealVerify 同机列，但 manifest 直接写成任意对象（用于「无 files 键 → `|| {}` 分支」）
async function runRealVerifyRaw(post, manifestObj, expectFail){
  const script = path.join(ROOT, 'skills/posts', post, 'scripts', 'verify_dependencies.mjs');
  const manifestPath = path.join(ROOT, 'skills/posts', post, 'dependencies.json');
  const backup = await readJsonOptional(manifestPath);
  try {
    await writeJson(manifestPath, manifestObj);
    const r = await execFileP(process.execPath, [script]).catch(e => e);
    if (expectFail) assert.ok((r.exitCode ?? r.code ?? 1) === 1 || String(r.stdout || r.stderr || '').includes('blocked'), `${post} 应失败: ${r.stdout || r.stderr}`);
    else assert.strictEqual(JSON.parse(r.stdout).status, 'clean', `${post}: ${r.stdout}`);
    return r;
  } finally {
    if (backup) await writeJson(manifestPath, backup); else await fs.rm(manifestPath, {force: true});
  }
}

test('verify_dependencies 4 岗真实脚本 clean + drift + 相对路径 + 空清单', async () => {
  await withVerifyLock(async () => {
    for (const post of [...SIMPLE_POSTS, JINSHA_POST]) {
      const f1 = path.join(await tmpDir(`v-${post}-`), 'f1.txt'); await fs.writeFile(f1, 'hello');
      const f2 = path.join(await tmpDir(`v-${post}-`), 'f2.txt'); await fs.writeFile(f2, 'world');
      const good = {[f1]: shaOf(await fs.readFile(f1)), [f2]: shaOf(await fs.readFile(f2))};
      await runRealVerify(post, good, false);
      await runRealVerify(post, {[f1]: 'deadbeef'.repeat(8), [f2]: shaOf(await fs.readFile(f2))}, true); // drift → status 'drift' 分支
      await runRealVerifyRaw(post, {}, false); // manifest 无 files 键 → `|| {}` 两个分支（空清单直接 clean）
      if (post !== JINSHA_POST) {
        // 相对路径分支：scripts/verify_dependencies.mjs 是真实存在的岗位内文件（jinsha 已在独立测试中覆盖）
        const relFile = 'scripts/verify_dependencies.mjs';
        const relPath = path.join(ROOT, 'skills/posts', post, relFile);
        await runRealVerify(post, {[relFile]: shaOf(await fs.readFile(relPath))}, false);
      }
    }
  });
});

// ============================================================ verify_dependencies.mjs（meituan 真实脚本：drift + bad-json）
test('verify_dependencies drift + bad-json（meituan 真实脚本）', async () => {
  await withVerifyLock(async () => {
    const post = 'meituan-post';
    const f1 = path.join(await tmpDir('v-meituan-'), 'f1.txt'); await fs.writeFile(f1, 'hello');
    const good = {[f1]: shaOf(await fs.readFile(f1))};
    await runRealVerify(post, good, false);
    await runRealVerify(post, {[f1]: 'deadbeef'.repeat(8)}, true);
    const manifestPath = path.join(ROOT, 'skills/posts', post, 'dependencies.json');
    const backup = await readJsonOptional(manifestPath);
    try {
      await fs.writeFile(manifestPath, '{bad json');
      const r = await execFileP(process.execPath, [path.join(ROOT, 'skills/posts', post, 'scripts', 'verify_dependencies.mjs')]).catch(e => e);
      assert.ok((r.exitCode ?? r.code ?? 1) === 1 || String(r.stdout || r.stderr || '').includes('blocked'), 'bad-json 应失败');
    } finally {
      if (backup) await writeJson(manifestPath, backup); else await fs.rm(manifestPath, {force: true});
    }
  });
});

// ============================================================ verify_dependencies.mjs（jinsha 真实脚本：绝对路径 + 相对路径分支 + drift + bad-json）
test('verify_dependencies 绝对路径 + 相对路径分支 + drift + bad-json（jinsha 真实脚本）', async () => {
  await withVerifyLock(async () => {
    const post = JINSHA_POST;
    const absFile = path.join(await tmpDir('v-jinsha-abs-'), 'f2.txt'); await fs.writeFile(absFile, 'world');
    const absHash = shaOf(await fs.readFile(absFile));
    const relFile = 'scripts/verify_dependencies.mjs'; // 相对路径 → 触发 path.isAbsolute 假分支（解析到真实 skill 目录内已有文件）
    const relPath = path.join(ROOT, 'skills/posts', post, relFile);
    const good = {[absFile]: absHash, [relFile]: shaOf(await fs.readFile(relPath))};
    await runRealVerify(post, good, false); // 同时覆盖 绝对路径 与 相对路径 两个分支
    await runRealVerify(post, {[absFile]: 'deadbeef'.repeat(8), [relFile]: shaOf(await fs.readFile(relPath))}, true); // 绝对文件漂移
    const manifestPath = path.join(ROOT, 'skills/posts', post, 'dependencies.json');
    const backup = await readJsonOptional(manifestPath);
    try {
      await fs.writeFile(manifestPath, '{bad json');
      const r = await execFileP(process.execPath, [path.join(ROOT, 'skills/posts', post, 'scripts', 'verify_dependencies.mjs')]).catch(e => e);
      assert.ok((r.exitCode ?? r.code ?? 1) === 1 || String(r.stdout || r.stderr || '').includes('blocked'), 'bad-json 应失败');
    } finally {
      if (backup) await writeJson(manifestPath, backup); else await fs.rm(manifestPath, {force: true});
    }
  });
});

// verify_dependencies.mjs：bad-json 经【父进程 import】触发 .catch（覆盖 L24/L31）。
// 说明：原 subprocess（execFileP）跑脚本时 c8 仅追踪父进程，子进程 .catch 不被计入；dynamic import 在本进程内执行 main()，覆盖父进程可见。
// main() 为 fire-and-forget 异步，其 .catch 在微任务中把 process.exitCode 置 1；先 flush 若干轮次待其执行，再清除，避免污染本进程退出码。
test('verify_dependencies bad-json .catch（父进程 import，覆盖 L24/L31）', async () => {
  await withVerifyLock(async () => {
    for (const post of [...SIMPLE_POSTS, JINSHA_POST]) {
      const script = pathToFileURL(path.join(ROOT, 'skills/posts', post, 'scripts', 'verify_dependencies.mjs')).href;
      const manifestPath = path.join(ROOT, 'skills/posts', post, 'dependencies.json');
      const backup = await readJsonOptional(manifestPath);
      const prevExit = process.exitCode;
      try {
        await fs.writeFile(manifestPath, '{bad json'); // 损坏 manifest → main() JSON.parse 抛错 → .catch
        await import(script).catch(() => {});
        for (let i = 0; i < 50 && process.exitCode === undefined; i++) await new Promise(r => setImmediate(r));
      } catch {} finally {
        process.exitCode = prevExit; // 清除 main() 异步 .catch 置的 exitCode=1（prevExit 初始为 undefined）
        if (backup) await writeJson(manifestPath, backup); else await fs.rm(manifestPath, {force: true});
      }
    }
  });
});

// ============================================================ executor 纯函数（W3 桌面发送证明修复分支）
test('executor 纯函数：desktopBatchItemSentOnce / validDesktopBatchProof', async () => {
  const m = await import(EXEC);
  assert.strictEqual(m.validDesktopBatchProof({
    verified: true, runtimeModelDecisions: 0,
    commonReceipt: {items: [
      {status: 'verified', verificationLevel: 'windows-readback-file-card', sendAttempts: 1},
      {status: 'verified', verificationLevel: 'windows-readback-file-card', sendAttempts: 1},
    ]},
    sendAttempts: 1,
  }), true);
  // transport 层兜底：item 无 sendAttempts，但 item.transport.sendAttempts===1
  assert.strictEqual(m.validDesktopBatchProof({
    verified: true, runtimeModelDecisions: 0,
    commonReceipt: {items: [
      {status: 'verified', verificationLevel: 'file-name-size-ui', sendAttempts: null, transport: {sendAttempts: 1}},
      {status: 'verified', verificationLevel: 'file-name-size-ui', sendAttempts: null, transport: {sendAttempts: 1}},
    ]},
    sendAttempts: 2, newSendAttempts: 2,
  }), true);
  assert.strictEqual(m.validDesktopBatchProof({verified: true, runtimeModelDecisions: 0, commonReceipt: {items: [{status: 'verified', verificationLevel: 'weak-level', sendAttempts: 1}, {status: 'verified', verificationLevel: 'weak-level', sendAttempts: 1}]}, sendAttempts: 1}), false); // 弱级别拒绝
  assert.strictEqual(m.validDesktopBatchProof({verified: false, commonReceipt: {items: []}}), false);
  assert.strictEqual(m.desktopBatchItemSentOnce({status: 'verified', verificationLevel: 'native-text-exact', sendAttempts: 1}), true);
  assert.strictEqual(m.desktopBatchItemSentOnce({status: 'verified', verificationLevel: 'native-text-exact', sendAttempts: null, transport: {sendAttempts: 1}}), true);
  assert.strictEqual(m.desktopBatchItemSentOnce({status: 'verified', verificationLevel: 'native-text-exact'}), false);
  assert.strictEqual(m.desktopBatchItemSentOnce(null), false);
});

// ============================================================ executor P0-2 强验证级别白名单外置（2026-10-03）
test('executor loadStrongDesktopVerificationLevels: 外置等价 / 兜底 / 非法回退', async () => {
  const m = await import(EXEC);
  const dir = await tmpDir('exec-levels-');
  const cfgPath = path.join(dir, 'verification-levels.json');
  // 与内置等价的合法配置
  await fs.writeFile(cfgPath, JSON.stringify({levels: ['file-name-size-ui', 'windows-readback-file-card', 'native-text-exact']}));
  let levels = m.loadStrongDesktopVerificationLevels(cfgPath);
  assert.ok(levels.has('file-name-size-ui') && levels.has('windows-readback-file-card') && levels.has('native-text-exact'));
  assert.strictEqual(levels.size, 3);
  // 新增/裁剪级别生效（外置可改）
  await fs.writeFile(cfgPath, JSON.stringify({levels: ['file-name-size-ui', 'new-strong-level']}));
  levels = m.loadStrongDesktopVerificationLevels(cfgPath);
  assert.ok(levels.has('new-strong-level') && !levels.has('windows-readback-file-card'));
  // 文件不存在 → 静默回退内置
  levels = m.loadStrongDesktopVerificationLevels(path.join(dir, 'no-such.json'));
  assert.ok(levels.has('native-text-exact') && levels.size === 3);
  // JSON 非法 / levels 非数组 → 回退内置
  await fs.writeFile(cfgPath, 'not-json{');
  assert.strictEqual(m.loadStrongDesktopVerificationLevels(cfgPath).size, 3);
  await fs.writeFile(cfgPath, JSON.stringify({levels: 'bad'}));
  assert.strictEqual(m.loadStrongDesktopVerificationLevels(cfgPath).size, 3);
  // levels 为空数组 → 回退内置
  await fs.writeFile(cfgPath, JSON.stringify({levels: []}));
  assert.strictEqual(m.loadStrongDesktopVerificationLevels(cfgPath).size, 3);
  // 含非字符串条目 → 过滤后生效
  await fs.writeFile(cfgPath, JSON.stringify({levels: ['ok', 42, null]}));
  assert.deepEqual([...m.loadStrongDesktopVerificationLevels(cfgPath)], ['ok']);
});

// ============================================================ executor validate* 证明校验（成功 + 失败分支）
test('executor validate* 证明校验（成功 + 失败分支）', async () => {
  const m = await import(EXEC);
  const dir = await tmpDir('exec-validate-');
  const cfg = (over = {}) => ({
    runId: 'R', businessDate: '2026-01-01', runtimeModelDecisions: 0,
    raw: {meituan: path.join(dir, 'raw-meituan'), taobao: path.join(dir, 'raw-taobao')},
    sendNames: {meituan: 'n-meituan', taobao: 'n-taobao'},
    preflightReceipt: path.join(dir, 'preflight.json'),
    downloadUiReceipt: path.join(dir, 'dl.json'),
    buildReceipt: path.join(dir, 'build.json'),
    examReceipt: path.join(dir, 'exam.json'),
    sendReceipt: path.join(dir, 'send.json'),
    verifyReceipt: path.join(dir, 'verify.json'),
    ...over,
  });
  const rawM = await fileId(await (async () => { const p = cfg().raw.meituan; await fs.writeFile(p, 'data'); return p; })());
  const rawT = await fileId(await (async () => { const p = cfg().raw.taobao; await fs.writeFile(p, 'data'); return p; })());

  await writeJson(cfg().downloadUiReceipt, {ok: true, runId: 'R', businessDate: '2026-01-01', runtimeModelDecisions: 0, jinshaResourceReleased: true, clicks: {meituan: 1, taobao: 1}, files: {meituan: rawM, taobao: rawT}});
  await m.validateDownloaded(cfg());
  await writeJson(cfg().downloadUiReceipt, {ok: true, runId: 'R', businessDate: '2026-01-01', runtimeModelDecisions: 0, jinshaResourceReleased: false, clicks: {meituan: 1, taobao: 1}, files: {meituan: rawM, taobao: rawT}});
  await assert.rejects(async () => m.validateDownloaded(cfg()), /download-proof-invalid/);

  const bM = path.join(dir, 'b-meituan'); await fs.writeFile(bM, 'built'); const pM = await fileId(bM);
  const bT = path.join(dir, 'b-taobao'); await fs.writeFile(bT, 'built'); const pT = await fileId(bT);
  await writeJson(cfg().preflightReceipt, {ok: true, runId: 'R', businessDate: '2026-01-01', groupName: FIXED.group, authorization: FIXED.authorization, requestedWechatChannel: 'desktop', stage: 'prepared', files: {meituan: {name: 'n-meituan', path: pM.file, size: pM.size, sha256: pM.sha256}, taobao: {name: 'n-taobao', path: pT.file, size: pT.size, sha256: pT.sha256}}});
  await writeJson(cfg().buildReceipt, {files: {meituan: {name: 'n-meituan', file: pM.file}, taobao: {name: 'n-taobao', file: pT.file}}});
  await writeJson(cfg().examReceipt, {ok: true, stage: 'prepared'});
  await m.validatePrepared(cfg());
  const badPref = JSON.parse(await fs.readFile(cfg().preflightReceipt, 'utf8')); badPref.groupName = 'wrong'; await writeJson(cfg().preflightReceipt, badPref);
  await assert.rejects(async () => m.validatePrepared(cfg()), /prepare-proof-invalid/);

  await writeJson(cfg().preflightReceipt, {ok: true, runId: 'R', businessDate: '2026-01-01', groupName: FIXED.group, authorization: FIXED.authorization, requestedWechatChannel: 'desktop', stage: 'prepared', files: {meituan: {name: 'n-meituan', path: path.join(dir, 'b-meituan')}, taobao: {name: 'n-taobao', path: path.join(dir, 'b-taobao')}}});
  await writeJson(cfg().examReceipt, {ok: true, stage: 'complete', wechatChannel: 'desktop', businessCompleted: true});
  await writeJson(cfg().sendReceipt, {ok: true, channel: 'desktop', groupName: FIXED.group, sent: ['a', 'b'], desktop: {verified: true, runtimeModelDecisions: 0, commonReceipt: {items: [{status: 'verified', verificationLevel: 'windows-readback-file-card', sendAttempts: 1}, {status: 'verified', verificationLevel: 'windows-readback-file-card', sendAttempts: 1}]}, sendAttempts: 1}});
  await m.validateSent(cfg());
  const badSend = JSON.parse(await fs.readFile(cfg().sendReceipt, 'utf8')); badSend.desktop.commonReceipt.items = [{status: 'verified', verificationLevel: 'weak', sendAttempts: 1}, {status: 'verified', verificationLevel: 'weak', sendAttempts: 1}]; await writeJson(cfg().sendReceipt, badSend);
  await assert.rejects(async () => m.validateSent(cfg()), /desktop-send-proof-invalid/);

  // validateVerified 要求 exam.stage==='verified'（与 validateSent 要求的 'complete' 不同），须单独重写
  await writeJson(cfg().examReceipt, {ok: true, stage: 'verified', wechatChannel: 'desktop', businessCompleted: true});
  await writeJson(cfg().verifyReceipt, {ok: true, channel: 'desktop', groupName: FIXED.group, confirmedBusinessLedgerFromDesktopAttempt: true, sent: ['a', 'b']});
  await m.validateVerified(cfg());
  const badV = JSON.parse(await fs.readFile(cfg().verifyReceipt, 'utf8')); badV.confirmedBusinessLedgerFromDesktopAttempt = false; badV.reusedMobileLedger = false; await writeJson(cfg().verifyReceipt, badV);
  await assert.rejects(async () => m.validateVerified(cfg()), /verify-proof-invalid/);
});

// ============================================================ executor buildWorkflowSummary / completionOutput
test('executor buildWorkflowSummary / completionOutput', async () => {
  const m = await import(EXEC);
  const state = {runId: 'R', businessDate: '2026-01-01', policyVersion: 'v1', status: 'active', phase: 'verified', nextAction: 'verify-only', runtimeModelDecisions: 0, createdAt: 1000, updatedAt: 5000, completedAt: 6000, events: [
    {type: 'attempt', stage: 'download', at: 1100}, {type: 'transition', to: 'downloaded', at: 1200},
    {type: 'attempt', stage: 'send', at: 2000}, {type: 'transition', to: 'sent', at: 2500}, {type: 'transition', to: 'complete', at: 5500},
  ]};
  const summary = m.buildWorkflowSummary(state);
  assert.ok(Array.isArray(summary.nodes) && summary.nodes.length >= 1);
  assert.strictEqual(summary.totalElapsedMs, 5000);
  const dir = await tmpDir('exec-comp-');
  const ws = path.join(dir, 'workflow.json'); const cfg = {workflowState: ws, workflowSummary: path.join(dir, 'summary.json'), examReceipt: path.join(dir, 'exam.json')};
  await writeJson(ws, state); await writeJson(cfg.examReceipt, {ok: true}); await writeJson(cfg.workflowSummary, summary);
  const out = m.completionOutput(state, cfg, summary);
  assert.strictEqual(out.ok, true); assert.ok(out.completionReview && out.completionReview.reviewItems);
});

// ============================================================ executor reset* 全分支
test('executor resetZeroSend / resetDownload 全分支', async () => {
  const m = await import(EXEC);
  const dir = await tmpDir('exec-reset-');
  const cfg = {workflowState: path.join(dir, 'w.json'), preflightReceipt: path.join(dir, 'preflight.json'), downloadUiReceipt: path.join(dir, 'dl.json')};
  // resetZeroSend
  assert.strictEqual(await m.resetZeroSendBudgetForMaintenanceResume(cfg, {phase: 'sent', status: 'active', attempts: {send: 0, verify: 0}}), false); // phase 不符
  assert.strictEqual(await m.resetZeroSendBudgetForMaintenanceResume(cfg, {phase: 'prepared', status: 'needs-resume', attempts: {send: 1, verify: 0}}), false); // 无 marker + attempts<MAX
  const st3 = {phase: 'prepared', status: 'needs-resume', attempts: {send: 4, verify: 1}, events: []};
  assert.strictEqual(await m.resetZeroSendBudgetForMaintenanceResume(cfg, st3), true); // 无 marker + attempts>=MAX → 重置
  assert.strictEqual(st3.attempts.send, 0); assert.strictEqual(st3.attempts.verify, 0);
  const mp4 = await writeMarker(cfg.preflightReceipt, {state: 'blocked', sendAttempts: 0, verified: true});
  const st4 = {phase: 'prepared', status: 'needs-resume', attempts: {send: 4, verify: 1}, events: []};
  assert.strictEqual(await m.resetZeroSendBudgetForMaintenanceResume(cfg, st4), true); await rmMarker(mp4); // marker blocked+零发送 → 重置
  const mp5 = await writeMarker(cfg.preflightReceipt, {state: 'ok', sendAttempts: 3, verified: true});
  const st5 = {phase: 'prepared', status: 'needs-resume', attempts: {send: 4, verify: 1}, events: []};
  assert.strictEqual(await m.resetZeroSendBudgetForMaintenanceResume(cfg, st5), false); await rmMarker(mp5); // marker 存在但非 blocked → false
  // resetDownload
  assert.strictEqual(await m.resetDownloadBudgetForMaintenanceResume(cfg, {phase: 'downloaded', status: 'needs-maintenance', attempts: {download: 0}}), false); // phase 不符
  assert.strictEqual(await m.resetDownloadBudgetForMaintenanceResume(cfg, {phase: 'created', status: 'active', attempts: {download: 0}}), false); // status 不符
  assert.strictEqual(await m.resetDownloadBudgetForMaintenanceResume(cfg, {phase: 'created', status: 'needs-maintenance', attempts: {download: 3}, events: []}), true); // 无 receipt 落盘（无证据）→ 视为维护已完成，允许重置（此状态触发 saveState，需 events 数组）
  await writeJson(cfg.downloadUiReceipt, {ok: true});
  assert.strictEqual(await m.resetDownloadBudgetForMaintenanceResume(cfg, {phase: 'created', status: 'needs-maintenance', attempts: {download: 2}}), false); // receipt.ok → 不重置
  await writeJson(cfg.downloadUiReceipt, {ok: false, reason: 'some-random-reason'});
  assert.strictEqual(await m.resetDownloadBudgetForMaintenanceResume(cfg, {phase: 'created', status: 'needs-maintenance', attempts: {download: 2}}), false); // reason 不允许
  await writeJson(cfg.downloadUiReceipt, {ok: false, reason: 'jinsha-background-profile-state-mismatch'});
  const dl6 = {phase: 'created', status: 'needs-maintenance', attempts: {download: 3}, events: []};
  assert.strictEqual(await m.resetDownloadBudgetForMaintenanceResume(cfg, dl6), true); assert.strictEqual(dl6.attempts.download, 0); // 允许 reason → 重置（attempts>=MAX 才进入重置判定）
  // 其余三个允许 reason 分支（download-retry-limit-exceeded / page.goto: Timeout* / plan-option-timeout:*）各使一个 `!==`/`startsWith` 判定为假 → 整体不 return → 重置
  for (const reason of ['download-retry-limit-exceeded', 'page.goto: Timeout 12345', 'plan-option-timeout: network unreachable']) {
    await writeJson(cfg.downloadUiReceipt, {ok: false, reason});
    const st = {phase: 'created', status: 'needs-maintenance', attempts: {download: 3}, events: []};
    assert.strictEqual(await m.resetDownloadBudgetForMaintenanceResume(cfg, st), true); assert.strictEqual(st.attempts.download, 0);
  }
});

// ============================================================ executor 运行环境搭建助手（hermetic）
function makeRun(phase, attempts = {download: 0, send: 0, verify: 0}) {
  return (async () => {
    const dir = await tmpDir('exec-e2e-');
    const runDir = path.join(dir, 'run'); await fs.mkdir(runDir, {recursive: true});
    const day = '20260930', suffix = '01', runId = `jinsha-business-production-${day}-${suffix}`;
    const businessDate = previousBusinessDate(day);
    const config = buildProductionConfig({runDir, runId, businessDate, outputDir: dir});
    await fs.writeFile(config.raw.meituan, 'rawdata'); await fs.writeFile(config.raw.taobao, 'rawdata');
    const builtM = path.join(dir, 'built-meituan'), builtT = path.join(dir, 'built-taobao');
    await fs.writeFile(builtM, 'built'); await fs.writeFile(builtT, 'built');
    const state = {schemaVersion: 1, policyVersion: 'jinsha-business-code-enforced-v1', runId, businessDate, phase, status: 'active', nextAction: 'download', runtimeModelDecisions: 0, attempts: {...attempts}, events: [], createdAt: 1000};
    await writeJson(config.workflowState, state);
    await writeJson(path.join(runDir, 'config.json'), config);
    return {dir, runDir, config, runId, businessDate, builtM, builtT};
  })();
}
function happySim(ctx) {
  const {config, businessDate, runId, builtM, builtT} = ctx;
  return async (cmd, args) => {
    const stage = args && args[2]; // runInternalStage 调用 execFile(process.execPath, [PIPELINE, configPath, mode], opts) → mode 为 args 数组的第 3 个元素
    if (stage === '--download') {
      const m = await fileId(config.raw.meituan), t = await fileId(config.raw.taobao);
      await writeJson(config.downloadUiReceipt, {ok: true, runId, businessDate, runtimeModelDecisions: 0, jinshaResourceReleased: true, clicks: {meituan: 1, taobao: 1}, files: {meituan: m, taobao: t}});
    } else if (stage === '--prepare') {
      const bM = await fileId(builtM), bT = await fileId(builtT);
      await writeJson(config.examReceipt, {ok: true, stage: 'prepared'});
      await writeJson(config.preflightReceipt, {ok: true, runId, businessDate, groupName: FIXED.group, authorization: FIXED.authorization, requestedWechatChannel: 'desktop', stage: 'prepared', files: {meituan: {name: config.sendNames.meituan, path: builtM, size: bM.size, sha256: bM.sha256}, taobao: {name: config.sendNames.taobao, path: builtT, size: bT.size, sha256: bT.sha256}}});
      await writeJson(config.buildReceipt, {files: {meituan: {name: config.sendNames.meituan, file: builtM}, taobao: {name: config.sendNames.taobao, file: builtT}}});
    } else if (stage === '--send') {
      await writeJson(config.examReceipt, {ok: true, stage: 'complete', wechatChannel: 'desktop', businessCompleted: true});
      await writeJson(config.sendReceipt, {ok: true, channel: 'desktop', groupName: FIXED.group, sent: ['a', 'b'], desktop: {verified: true, runtimeModelDecisions: 0, commonReceipt: {items: [{status: 'verified', verificationLevel: 'windows-readback-file-card', sendAttempts: 1}, {status: 'verified', verificationLevel: 'windows-readback-file-card', sendAttempts: 1}]}, sendAttempts: 1}});
    } else if (stage === '--verify-only') {
      await writeJson(config.examReceipt, {ok: true, stage: 'verified', wechatChannel: 'desktop', businessCompleted: true});
      await writeJson(config.verifyReceipt, {ok: true, channel: 'desktop', groupName: FIXED.group, confirmedBusinessLedgerFromDesktopAttempt: true, sent: ['a', 'b']});
    }
    return {ok: true, stdout: '', stderr: ''};
  };
}

// ============================================================ executor executeRun：全 phase 成功 → complete
e2eTest('executor executeRun 全 phase 成功 → complete', async () => {
  const m = await import(EXEC);
  const ctx = await makeRun('created');
  globalThis.__EXEC_EXEC_FILE__ = happySim(ctx);
  try {
    const s = await m.executeRun({config: ctx.config, state: JSON.parse(await fs.readFile(ctx.config.workflowState, 'utf8')), runDir: ctx.runDir});
    assert.strictEqual(s.phase, 'complete'); assert.strictEqual(s.status, 'complete');
    const summary = JSON.parse(await fs.readFile(ctx.config.workflowSummary, 'utf8'));
    assert.ok(Array.isArray(summary.nodes) && summary.nodes.length >= 4);
  } finally { delete globalThis.__EXEC_EXEC_FILE__; }
});

// ============================================================ executor downloadPhase：retry → block(needs-maintenance)
e2eTest('executor downloadPhase 重试上限 → block(needs-maintenance)', async () => {
  const m = await import(EXEC);
  const ctx = await makeRun('created');
  globalThis.__EXEC_EXEC_FILE__ = async (cmd, args) => {
    if (args[2] === '--download') await writeJson(ctx.config.downloadUiReceipt, {ok: false, reason: 'retry', clicks: {}, files: {}});
    return {ok: true, stdout: '', stderr: ''};
  };
  try {
    await assert.rejects(async () => m.executeRun({config: ctx.config, state: JSON.parse(await fs.readFile(ctx.config.workflowState, 'utf8')), runDir: ctx.runDir}), /download-retry-limit-exceeded/);
  } finally { delete globalThis.__EXEC_EXEC_FILE__; }
});

// ============================================================ executor downloadPhase：resume-taobao → 续下后 downloaded
e2eTest('executor downloadPhase resume-taobao → 续下后跑完全链路', async () => {
  const m = await import(EXEC);
  const ctx = await makeRun('created');
  let first = true;
  globalThis.__EXEC_EXEC_FILE__ = async (cmd, args) => {
    const stage = args[2];
    if (stage === '--download') {
      if (first) { first = false; await writeJson(ctx.config.downloadUiReceipt, {ok: true, runId: ctx.runId, businessDate: ctx.businessDate, runtimeModelDecisions: 0, jinshaResourceReleased: true, clicks: {meituan: 1, taobao: 0}, files: {meituan: await fileId(ctx.config.raw.meituan)}}); }
      else { await writeJson(ctx.config.downloadUiReceipt, {ok: true, runId: ctx.runId, businessDate: ctx.businessDate, runtimeModelDecisions: 0, jinshaResourceReleased: true, clicks: {meituan: 1, taobao: 1}, files: {meituan: await fileId(ctx.config.raw.meituan), taobao: await fileId(ctx.config.raw.taobao)}}); }
    } else if (stage === '--prepare') {
      const bM = await fileId(ctx.builtM), bT = await fileId(ctx.builtT);
      await writeJson(ctx.config.examReceipt, {ok: true, stage: 'prepared'});
      await writeJson(ctx.config.preflightReceipt, {ok: true, runId: ctx.runId, businessDate: ctx.businessDate, groupName: FIXED.group, authorization: FIXED.authorization, requestedWechatChannel: 'desktop', stage: 'prepared', files: {meituan: {name: ctx.config.sendNames.meituan, path: ctx.builtM, size: bM.size, sha256: bM.sha256}, taobao: {name: ctx.config.sendNames.taobao, path: ctx.builtT, size: bT.size, sha256: bT.sha256}}});
      await writeJson(ctx.config.buildReceipt, {files: {meituan: {name: ctx.config.sendNames.meituan, file: ctx.builtM}, taobao: {name: ctx.config.sendNames.taobao, file: ctx.builtT}}});
    } else if (stage === '--send') {
      await writeJson(ctx.config.examReceipt, {ok: true, stage: 'complete', wechatChannel: 'desktop', businessCompleted: true});
      await writeJson(ctx.config.sendReceipt, {ok: true, channel: 'desktop', groupName: FIXED.group, sent: ['a', 'b'], desktop: {verified: true, runtimeModelDecisions: 0, commonReceipt: {items: [{status: 'verified', verificationLevel: 'windows-readback-file-card', sendAttempts: 1}, {status: 'verified', verificationLevel: 'windows-readback-file-card', sendAttempts: 1}]}, sendAttempts: 1}});
    } else if (stage === '--verify-only') {
      await writeJson(ctx.config.examReceipt, {ok: true, stage: 'verified', wechatChannel: 'desktop', businessCompleted: true});
      await writeJson(ctx.config.verifyReceipt, {ok: true, channel: 'desktop', groupName: FIXED.group, confirmedBusinessLedgerFromDesktopAttempt: true, sent: ['a', 'b']});
    }
    return {ok: true, stdout: '', stderr: ''};
  };
  try {
    const s = await m.executeRun({config: ctx.config, state: JSON.parse(await fs.readFile(ctx.config.workflowState, 'utf8')), runDir: ctx.runDir});
    assert.strictEqual(s.phase, 'complete');
    const saved = JSON.parse(await fs.readFile(path.join(ctx.runDir, 'config.json'), 'utf8'));
    assert.strictEqual(saved.resumeDownload, true);
  } finally { delete globalThis.__EXEC_EXEC_FILE__; }
});

// ============================================================ executor preparePhase：失败 → block(needs-maintenance)
e2eTest('executor preparePhase 失败（ok:false）→ block', async () => {
  const m = await import(EXEC);
  const ctx = await makeRun('downloaded');
  globalThis.__EXEC_EXEC_FILE__ = async () => ({ok: false, stdout: '', stderr: 'prepare failed'});
  try {
    await assert.rejects(async () => m.executeRun({config: ctx.config, state: JSON.parse(await fs.readFile(ctx.config.workflowState, 'utf8')), runDir: ctx.runDir}), /prepare-stage-failed/);
  } finally { delete globalThis.__EXEC_EXEC_FILE__; }
});

// ============================================================ executor runInternalStage 异常 → 当阶段 block
e2eTest('executor runInternalStage 抛异常 → 当阶段 block', async () => {
  const m = await import(EXEC);
  const ctx = await makeRun('downloaded');
  globalThis.__EXEC_EXEC_FILE__ = async () => { throw new Error('pipeline crashed'); };
  try {
    await assert.rejects(async () => m.executeRun({config: ctx.config, state: JSON.parse(await fs.readFile(ctx.config.workflowState, 'utf8')), runDir: ctx.runDir}), /prepare-stage-failed/);
  } finally { delete globalThis.__EXEC_EXEC_FILE__; }
});

// ============================================================ executor sendPhase：verify-only（marker 已验证）→ 收口
e2eTest('executor sendPhase verify-only（marker 已验证）→ verified', async () => {
  const m = await import(EXEC);
  const ctx = await makeRun('prepared');
  const mp = await writeMarker(ctx.config.preflightReceipt, {state: 'verified', sendAttempts: 1, verified: true});
  globalThis.__EXEC_EXEC_FILE__ = async (cmd, args) => {
    if (args[2] === '--verify-only') {
      await writeJson(ctx.config.examReceipt, {ok: true, stage: 'verified', wechatChannel: 'desktop', businessCompleted: true});
      await writeJson(ctx.config.verifyReceipt, {ok: true, channel: 'desktop', groupName: FIXED.group, confirmedBusinessLedgerFromDesktopAttempt: true, sent: ['a', 'b']});
    }
    return {ok: true, stdout: '', stderr: ''};
  };
  try {
    const s = await m.executeRun({config: ctx.config, state: JSON.parse(await fs.readFile(ctx.config.workflowState, 'utf8')), runDir: ctx.runDir});
    assert.strictEqual(s.phase, 'complete');
  } finally { await rmMarker(mp); delete globalThis.__EXEC_EXEC_FILE__; }
});

// ============================================================ executor sendPhase：send 失败且 marker 出现 → block(desktop-send-outcome-unknown)
e2eTest('executor sendPhase send 失败 + marker 出现 → block(desktop-send-outcome-unknown)', async () => {
  const m = await import(EXEC);
  const ctx = await makeRun('created', {download: 0, send: 3, verify: 0}); // send 起始=MAX-1 → 循环仅 1 轮；先 download/prepare 走完，使 preflight 存在以支撑 marker 身份
  globalThis.__EXEC_EXEC_FILE__ = async (cmd, args) => {
    const stage = args[2];
    if (stage === '--download') {
      const mm = await fileId(ctx.config.raw.meituan), tt = await fileId(ctx.config.raw.taobao);
      await writeJson(ctx.config.downloadUiReceipt, {ok: true, runId: ctx.runId, businessDate: ctx.businessDate, runtimeModelDecisions: 0, jinshaResourceReleased: true, clicks: {meituan: 1, taobao: 1}, files: {meituan: mm, taobao: tt}});
    } else if (stage === '--prepare') {
      const bM = await fileId(ctx.builtM), bT = await fileId(ctx.builtT);
      await writeJson(ctx.config.examReceipt, {ok: true, stage: 'prepared'});
      await writeJson(ctx.config.preflightReceipt, {ok: true, runId: ctx.runId, businessDate: ctx.businessDate, groupName: FIXED.group, authorization: FIXED.authorization, requestedWechatChannel: 'desktop', stage: 'prepared', files: {meituan: {name: ctx.config.sendNames.meituan, path: ctx.builtM, size: bM.size, sha256: bM.sha256}, taobao: {name: ctx.config.sendNames.taobao, path: ctx.builtT, size: bT.size, sha256: bT.sha256}}});
      await writeJson(ctx.config.buildReceipt, {files: {meituan: {name: ctx.config.sendNames.meituan, file: ctx.builtM}, taobao: {name: ctx.config.sendNames.taobao, file: ctx.builtT}}});
    } else if (stage === '--send') {
      // 模拟「send 子进程报失败，但确实落了桌面发送 marker」→ 触发 desktop-send-outcome-unknown 收口判定
      await writeMarker(ctx.config.preflightReceipt, {state: 'sent', sendAttempts: 1, verified: true});
      return {ok: false, stdout: '', stderr: 'send failed'};
    } else if (stage === '--verify-only') {
      return {ok: false, stdout: '', stderr: 'verify failed'}; // 收口证明也失败
    }
    return {ok: true, stdout: '', stderr: ''};
  };
  try {
    await assert.rejects(async () => m.executeRun({config: ctx.config, state: JSON.parse(await fs.readFile(ctx.config.workflowState, 'utf8')), runDir: ctx.runDir}), /desktop-send-outcome-unknown/);
  } finally { delete globalThis.__EXEC_EXEC_FILE__; }
});

// ============================================================ executor sendPhase：重试上限 → block(needs-resume)
e2eTest('executor sendPhase 重试上限 → block(needs-resume)', async () => {
  const m = await import(EXEC);
  const ctx = await makeRun('prepared', {download: 0, send: 3, verify: 0}); // 仅 1 轮，无 sleep
  globalThis.__EXEC_EXEC_FILE__ = async (cmd, args) => { if (args[2] === '--send') return {ok: false, stdout: '', stderr: 'send failed'}; return {ok: true, stdout: '', stderr: ''}; };
  try {
    await assert.rejects(async () => m.executeRun({config: ctx.config, state: JSON.parse(await fs.readFile(ctx.config.workflowState, 'utf8')), runDir: ctx.runDir}), /desktop-preflight-retry-limit-exceeded/);
  } finally { delete globalThis.__EXEC_EXEC_FILE__; }
});

// ============================================================ executor verifyPhase：收口失败 → block(needs-resume)（含 verify 重试 sleep 分支）
e2eTest('executor verifyPhase 收口失败 → block(needs-resume)', async () => {
  const m = await import(EXEC);
  const ctx = await makeRun('sent', {download: 0, send: 0, verify: 3}); // verify 起始=MAX-1 → 仅 1 轮，含 1 次 sleep
  globalThis.__EXEC_EXEC_FILE__ = async (cmd, args) => { if (args[2] === '--verify-only') return {ok: false, stdout: '', stderr: 'verify failed'}; return {ok: true, stdout: '', stderr: ''}; };
  try {
    await assert.rejects(async () => m.executeRun({config: ctx.config, state: JSON.parse(await fs.readFile(ctx.config.workflowState, 'utf8')), runDir: ctx.runDir}), /desktop-verify-retry-limit-exceeded/);
  } finally { delete globalThis.__EXEC_EXEC_FILE__; }
});

// ============================================================ executor executeRun 尾段：verified→complete 与 非法 phase 兜底
test('executor executeRun 尾段：verified→complete 与 非法 phase 兜底', async () => {
  const m = await import(EXEC);
  const dir = await tmpDir('exec-run-');
  const workflowState = path.join(dir, 'workflow.json');
  const workflowSummary = path.join(dir, 'summary.json');
  const runDir = path.join(dir, 'run'); await fs.mkdir(runDir, {recursive: true});
  const config = {runDir, runId: 'R', businessDate: '2026-01-01', workflowState, workflowSummary, examReceipt: path.join(dir, 'exam.json')};
  await writeJson(config.examReceipt, {ok: true});
  const verifiedState = {schemaVersion: 1, policyVersion: 'jinsha-business-code-enforced-v1', runId: 'R', businessDate: '2026-01-01', phase: 'verified', status: 'active', nextAction: 'verify-only', runtimeModelDecisions: 0, attempts: {download: 0, send: 0, verify: 0}, events: []};
  await writeJson(workflowState, verifiedState);
  const s1 = await m.executeRun({config, state: {...verifiedState}, runDir});
  assert.strictEqual(s1.phase, 'complete'); assert.strictEqual(s1.status, 'complete');
  const bogusState = {...verifiedState, phase: 'bogus-phase', status: 'active'};
  await writeJson(workflowState, bogusState);
  await assert.rejects(async () => m.executeRun({config, state: {...bogusState}, runDir}), /workflow-phase-not-runnable/);
});

// ============================================================ executor allocateRun / loadRun（hermetic：runsRoot 已重定向）
test('executor allocateRun / loadRun', async () => {
  const m = await import(EXEC);
  const run = await m.allocateRun(new Date('2026-09-30T12:00:00+08:00'));
  assert.ok(run.config && run.runDir && run.state); assert.strictEqual(run.state.phase, 'created');
  const loaded = await m.loadRun(run.runDir);
  assert.strictEqual(loaded.config.runId, run.config.runId);
  const bad = JSON.parse(await fs.readFile(run.config.workflowState, 'utf8')); bad.runId = 'tampered';
  await writeJson(run.config.workflowState, bad);
  await assert.rejects(async () => m.loadRun(run.runDir), /workflow-state-binding-mismatch/);
});

// ============================================================ executor main
test('executor main --self-test 与 usage 错误', async () => {
  const m = await import(EXEC);
  const out = []; const orig = console.log; console.log = (...a) => out.push(a.join(' '));
  try {
    await m.main(['--self-test']);
    assert.ok(out[0].includes('"ok":true'));
    await assert.rejects(async () => m.main(['bogus']), /usage:/);
  } finally { console.log = orig; }
});

e2eTest('executor main --resume 跑通全链路 → completionOutput', async () => {
  const m = await import(EXEC);
  const ctx = await makeRun('created');
  globalThis.__EXEC_EXEC_FILE__ = happySim(ctx);
  const out = []; const orig = console.log; console.log = (...a) => out.push(a.join(' '));
  try {
    await m.main(['--resume', ctx.runDir]);
    assert.ok(out.some(s => s.includes('"phase":"complete"')));
  } finally { console.log = orig; delete globalThis.__EXEC_EXEC_FILE__; }
});

// ============================================================ executor 边界分支补全（可达分支用真实测试覆盖）
// L27 readJsonOptional 非 ENOENT 抛错：downloadUiReceipt 指向目录 → readFile 抛 EISDIR
e2eTest('executor resetDownload 读 receipt 非 ENOENT 抛错（覆盖 L27 throw）', async () => {
  const m = await import(EXEC);
  const dir = await tmpDir('exec-reset-dir-');
  const cfg = {workflowState: path.join(dir, 'w.json'), preflightReceipt: path.join(dir, 'pf.json'), downloadUiReceipt: dir}; // 目录作为 receipt 路径
  const st = {phase: 'created', status: 'needs-maintenance', attempts: {download: 3}, events: []};
  await assert.rejects(async () => m.resetDownloadBudgetForMaintenanceResume(cfg, st), /EISDIR|EACCES/);
});

// L107 `receipt||{}` 分支（无 downloadUiReceipt → readJsonOptional 返回 null → receipt 为 {}）→ classifyDownloadRecovery({}) 返回 retry-download → 3 轮后 download-retry-limit-exceeded
e2eTest('executor downloadPhase 无 receipt（receipt||{} 分支）→ 重试上限 block(needs-maintenance)', async () => {
  const m = await import(EXEC);
  const ctx = await makeRun('created');
  globalThis.__EXEC_EXEC_FILE__ = async () => ({ok: true, stdout: '', stderr: ''}); // 不写 receipt → readJsonOptional→null → classifyDownloadRecovery({}) → retry-download → 上限
  try {
    await assert.rejects(async () => m.executeRun({config: ctx.config, state: JSON.parse(await fs.readFile(ctx.config.workflowState, 'utf8')), runDir: ctx.runDir}), /download-retry-limit-exceeded/);
  } finally { delete globalThis.__EXEC_EXEC_FILE__; }
});

// L107 `receipt||{}`（receipt 为 null）+ L111 blocked-unknown-download：ok 真但 meituan 文件缺失 → classifyDownloadRecovery 返回 blocked-unknown-download
e2eTest('executor downloadPhase 不可识别回执 → block(blocked-unknown-download)', async () => {
  const m = await import(EXEC);
  const ctx = await makeRun('created');
  globalThis.__EXEC_EXEC_FILE__ = async (cmd, args) => {
    if (args[2] === '--download') {
      // ok 真、clicks 双 1，但 meituan 文件缺失 → 非 downloaded/resume-taobao/retry-download → blocked-unknown-download
      await writeJson(ctx.config.downloadUiReceipt, {ok: true, runId: ctx.runId, businessDate: ctx.businessDate, runtimeModelDecisions: 0, jinshaResourceReleased: true, clicks: {meituan: 1, taobao: 1}, files: {taobao: {file: ctx.config.raw.taobao, size: 1, sha256: 'x'}}});
    }
    return {ok: true, stdout: '', stderr: ''};
  };
  try {
    await assert.rejects(async () => m.executeRun({config: ctx.config, state: JSON.parse(await fs.readFile(ctx.config.workflowState, 'utf8')), runDir: ctx.runDir}), /blocked-unknown-download/);
  } finally { delete globalThis.__EXEC_EXEC_FILE__; }
});

// L81 validateSent 无 desktop 且 无 reusedMobileLedger → desktop-send-proof-missing
test('executor validateSent 无 desktop 且 无 reusedMobileLedger → desktop-send-proof-missing', async () => {
  const m = await import(EXEC);
  const dir = await tmpDir('exec-sent-');
  const cfg = {runId: 'R', businessDate: '2026-01-01', sendReceipt: path.join(dir, 'send.json'), examReceipt: path.join(dir, 'exam.json')};
  await writeJson(cfg.examReceipt, {ok: true, stage: 'complete', wechatChannel: 'desktop', businessCompleted: true});
  await writeJson(cfg.sendReceipt, {ok: true, channel: 'desktop', groupName: FIXED.group, sent: ['a', 'b']}); // 无 desktop / 无 reusedMobileLedger
  await assert.rejects(async () => m.validateSent(cfg), /desktop-send-proof-missing/);
});

// L84 validateVerified confirmedReadback 走 reusedMobileLedger===true 分支
test('executor validateVerified reusedMobileLedger=true 分支', async () => {
  const m = await import(EXEC);
  const dir = await tmpDir('exec-ver-');
  const cfg = {verifyReceipt: path.join(dir, 'verify.json'), examReceipt: path.join(dir, 'exam.json')};
  await writeJson(cfg.examReceipt, {ok: true, stage: 'verified', wechatChannel: 'desktop', businessCompleted: true});
  await writeJson(cfg.verifyReceipt, {ok: true, channel: 'desktop', groupName: FIXED.group, reusedMobileLedger: true, sent: ['a', 'b']});
  await m.validateVerified(cfg);
});

// L61/L62 validateDownloaded 缺 files/clicks → 抛 download-proof-binding-mismatch
test('executor validateDownloaded 缺 files/clicks → download-proof-binding-mismatch', async () => {
  const m = await import(EXEC);
  const dir = await tmpDir('exec-dl-');
  const rawM = await fileId(await (async () => { const p = path.join(dir, 'raw-meituan'); await fs.writeFile(p, 'data'); return p; })());
  const cfg = {runId: 'R', businessDate: '2026-01-01', raw: {meituan: rawM.file, taobao: path.join(dir, 'raw-taobao')}, downloadUiReceipt: path.join(dir, 'dl.json')};
  await writeJson(cfg.downloadUiReceipt, {ok: true, runId: 'R', businessDate: '2026-01-01', runtimeModelDecisions: 0, jinshaResourceReleased: true, clicks: {meituan: 1, taobao: 1}, files: {meituan: rawM}}); // 缺 taobao files 条目
  await assert.rejects(async () => m.validateDownloaded(cfg), /download-proof-binding-mismatch:taobao/);
});

// L42 buildWorkflowSummary 无 complete 终态 transition（if(finalTransition) 假分支）
test('executor buildWorkflowSummary 无 complete 终态 transition', async () => {
  const m = await import(EXEC);
  const state = {runId: 'R', businessDate: '2026-01-01', policyVersion: 'v1', status: 'blocked-unknown-download', phase: 'created', nextAction: 'download', runtimeModelDecisions: 0, createdAt: 1000, updatedAt: 2000, completedAt: null, events: [{type: 'attempt', stage: 'download', at: 1100}, {type: 'blocked', stage: 'download', at: 1200, reason: 'x'}]};
  const s = m.buildWorkflowSummary(state);
  assert.ok(Array.isArray(s.nodes)); assert.strictEqual(s.totalElapsedMs, 1000);
});

// ============================================================ executor 分支补全第二轮（可达分支用真实测试覆盖）
// L42 buildWorkflowSummary finishedAt 的 || 回退分支：completedAt 缺失→updatedAt；两者均缺失→Date.now()
test('executor buildWorkflowSummary finishedAt || 回退分支', async () => {
  const m = await import(EXEC);
  const base = {runId:'R',businessDate:'2026-01-01',policyVersion:'v1',status:'active',phase:'verified',nextAction:'verify-only',runtimeModelDecisions:0,createdAt:1000,events:[]};
  const s1 = {...base, updatedAt:5000}; // completedAt 缺失 → finishedAt=updatedAt=5000
  assert.strictEqual(m.buildWorkflowSummary(s1).totalElapsedMs, 4000);
  const s2 = {...base, updatedAt:undefined}; // completedAt 与 updatedAt 均缺失 → finishedAt=Date.now()
  const sum = m.buildWorkflowSummary(s2);
  assert.ok(sum.totalElapsedMs > 1e9, `Date.now 回退路径 totalElapsedMs=${sum.totalElapsedMs}`);
});

// L61 validateDownloaded：clicks 缺 meituan（!=1）→ 第一操作数短路抛 download-proof-binding-mismatch:meituan（不评估 file）
test('executor validateDownloaded clicks 缺项 → binding-mismatch', async () => {
  const m = await import(EXEC);
  const dir = await tmpDir('exec-dl2-');
  const rawM = await fileId(await (async () => { const p = path.join(dir,'raw-meituan'); await fs.writeFile(p,'data'); return p; })());
  const cfg = {runId:'R',businessDate:'2026-01-01',runtimeModelDecisions:0,raw:{meituan:rawM.file,taobao:path.join(dir,'raw-taobao')},downloadUiReceipt:path.join(dir,'dl.json')};
  await writeJson(cfg.downloadUiReceipt,{ok:true,runId:'R',businessDate:'2026-01-01',runtimeModelDecisions:0,jinshaResourceReleased:true,clicks:{meituan:0,taobao:1},files:{meituan:rawM}});
  await assert.rejects(async () => m.validateDownloaded(cfg), /download-proof-binding-mismatch:meituan/);
});

// L62 validatePrepared：item.name 不匹配（#76 短路）→ mismatch:meituan；name 全对但 item.path≠built.file（#77 第三操作数）→ mismatch:meituan
test('executor validatePrepared 名称/路径不匹配 → mismatch', async () => {
  const m = await import(EXEC);
  const dir = await tmpDir('exec-prep2-');
  const bM = path.join(dir,'b-meituan'); await fs.writeFile(bM,'built'); const pM = await fileId(bM);
  const bT = path.join(dir,'b-taobao'); await fs.writeFile(bT,'built'); const pT = await fileId(bT);
  const mkCfg = (over) => ({runId:'R',businessDate:'2026-01-01',runtimeModelDecisions:0,sendNames:{meituan:'n-meituan',taobao:'n-taobao'},preflightReceipt:path.join(dir,'pf.json'),buildReceipt:path.join(dir,'build.json'),examReceipt:path.join(dir,'exam.json'),...over});
  const basePf = {ok:true,runId:'R',businessDate:'2026-01-01',groupName:FIXED.group,authorization:FIXED.authorization,requestedWechatChannel:'desktop',stage:'prepared',files:{meituan:{name:'n-meituan',path:pM.file,size:pM.size,sha256:pM.sha256},taobao:{name:'n-taobao',path:pT.file,size:pT.size,sha256:pT.sha256}}};
  const baseBuild = {files:{meituan:{name:'n-meituan',file:pM.file},taobao:{name:'n-taobao',file:pT.file}}};
  const pf1 = JSON.parse(JSON.stringify(basePf)); pf1.files.meituan.name = 'WRONG';
  await writeJson(mkCfg().preflightReceipt, pf1); await writeJson(mkCfg().buildReceipt, baseBuild); await writeJson(mkCfg().examReceipt, {ok:true,stage:'prepared'});
  await assert.rejects(async () => m.validatePrepared(mkCfg()), /prepare-proof-binding-mismatch:meituan/); // #76 短路
  const pf2 = JSON.parse(JSON.stringify(basePf)); const build2 = JSON.parse(JSON.stringify(baseBuild)); build2.files.meituan.file = '/wrong/path';
  await writeJson(mkCfg().preflightReceipt, pf2); await writeJson(mkCfg().buildReceipt, build2); await writeJson(mkCfg().examReceipt, {ok:true,stage:'prepared'});
  await assert.rejects(async () => m.validatePrepared(mkCfg()), /prepare-proof-binding-mismatch:meituan/); // #77 第三操作数
});

// L81 validateSent：无 desktop 但 reusedMobileLedger===true → else if 条件为假 → 不抛（通过）
test('executor validateSent 无 desktop 但 reusedMobileLedger=true → 通过', async () => {
  const m = await import(EXEC);
  const dir = await tmpDir('exec-sent2-');
  const cfg = {runId:'R',businessDate:'2026-01-01',sendReceipt:path.join(dir,'send.json'),examReceipt:path.join(dir,'exam.json')};
  await writeJson(cfg.examReceipt, {ok:true,stage:'complete',wechatChannel:'desktop',businessCompleted:true});
  await writeJson(cfg.sendReceipt, {ok:true,channel:'desktop',groupName:FIXED.group,sent:['a','b'],reusedMobileLedger:true});
  await m.validateSent(cfg);
});

// L84 attemptMarker：marker 存在但 verified:false → `marker?.verified===true` 为假（#108）
test('executor attemptMarker marker.verified=false 分支', async () => {
  const m = await import(EXEC);
  const dir = await tmpDir('exec-marker-');
  const cfg = {workflowState:path.join(dir,'w.json'),preflightReceipt:path.join(dir,'pf.json'),downloadUiReceipt:path.join(dir,'dl.json')};
  const mp = await writeMarker(cfg.preflightReceipt, {state:'blocked',sendAttempts:0,verified:false});
  const st = {phase:'prepared',status:'needs-resume',attempts:{send:4,verify:1},events:[]};
  assert.strictEqual(await m.resetZeroSendBudgetForMaintenanceResume(cfg, st), true); // 经 attemptMarker 读取 verified:false 的 marker
  await rmMarker(mp);
});

// L99/L100 resetDownload：receipt 为 null（无文件）→ `receipt?.ok` 短路；receipt.ok:false 且 reason 缺失 → `receipt?.reason` 短路
test('executor resetDownload receipt=null / reason 缺失 分支', async () => {
  const m = await import(EXEC);
  const dir = await tmpDir('exec-reset2-');
  const cfg = {workflowState:path.join(dir,'w.json'),preflightReceipt:path.join(dir,'pf.json'),downloadUiReceipt:path.join(dir,'dl.json')};
  const st1 = {phase:'created',status:'needs-maintenance',attempts:{download:3},events:[]};
  assert.strictEqual(await m.resetDownloadBudgetForMaintenanceResume(cfg, st1), true); // receipt 为 null
  await writeJson(cfg.downloadUiReceipt, {ok:false}); // ok:false 且 reason 缺失
  const st2 = {phase:'created',status:'needs-maintenance',attempts:{download:3},events:[]};
  assert.strictEqual(await m.resetDownloadBudgetForMaintenanceResume(cfg, st2), true);
});

// L122 sendPhase：marker=blocked+零发送 → zeroSendBlocked → retry-send → 发送成功收口（覆盖 #167/#168/#170/#175）
e2eTest('executor sendPhase marker=blocked+零发送 → retry-send → 收口', async () => {
  const m = await import(EXEC);
  const ctx = await makeRun('prepared');
  const mp = await writeMarker(ctx.config.preflightReceipt, {state:'blocked',sendAttempts:0,verified:false});
  globalThis.__EXEC_EXEC_FILE__ = async (cmd, args) => {
    const stage = args[2];
    if (stage === '--download') {
      const mm = await fileId(ctx.config.raw.meituan), tt = await fileId(ctx.config.raw.taobao);
      await writeJson(ctx.config.downloadUiReceipt, {ok:true,runId:ctx.runId,businessDate:ctx.businessDate,runtimeModelDecisions:0,jinshaResourceReleased:true,clicks:{meituan:1,taobao:1},files:{meituan:mm,taobao:tt}});
    } else if (stage === '--prepare') {
      const bM = await fileId(ctx.builtM), bT = await fileId(ctx.builtT);
      await writeJson(ctx.config.examReceipt, {ok:true,stage:'prepared'});
      await writeJson(ctx.config.preflightReceipt, {ok:true,runId:ctx.runId,businessDate:ctx.businessDate,groupName:FIXED.group,authorization:FIXED.authorization,requestedWechatChannel:'desktop',stage:'prepared',files:{meituan:{name:ctx.config.sendNames.meituan,path:ctx.builtM,size:bM.size,sha256:bM.sha256},taobao:{name:ctx.config.sendNames.taobao,path:ctx.builtT,size:bT.size,sha256:bT.sha256}}});
      await writeJson(ctx.config.buildReceipt, {files:{meituan:{name:ctx.config.sendNames.meituan,file:ctx.builtM},taobao:{name:ctx.config.sendNames.taobao,file:ctx.builtT}}});
    } else if (stage === '--send') {
      await writeJson(ctx.config.examReceipt, {ok:true,stage:'complete',wechatChannel:'desktop',businessCompleted:true});
      await writeJson(ctx.config.sendReceipt, {ok:true,channel:'desktop',groupName:FIXED.group,sent:['a','b'],desktop:{verified:true,runtimeModelDecisions:0,commonReceipt:{items:[{status:'verified',verificationLevel:'windows-readback-file-card',sendAttempts:1},{status:'verified',verificationLevel:'windows-readback-file-card',sendAttempts:1}]},sendAttempts:1}});
    } else if (stage === '--verify-only') {
      await writeJson(ctx.config.examReceipt, {ok:true,stage:'verified',wechatChannel:'desktop',businessCompleted:true});
      await writeJson(ctx.config.verifyReceipt, {ok:true,channel:'desktop',groupName:FIXED.group,confirmedBusinessLedgerFromDesktopAttempt:true,sent:['a','b']});
    }
    return {ok:true,stdout:'',stderr:''};
  };
  try {
    const s = await m.executeRun({config:ctx.config,state:JSON.parse(await fs.readFile(ctx.config.workflowState,'utf8')),runDir:ctx.runDir});
    assert.strictEqual(s.phase,'complete');
  } finally { await rmMarker(mp); delete globalThis.__EXEC_EXEC_FILE__; }
});

// L123 sendPhase：发送一直失败且无 markerAfter → 可重试时 sleep 后重试（覆盖 #177）
e2eTest('executor sendPhase 发送失败+无 marker+可重试 → sleep 重试', async () => {
  const m = await import(EXEC);
  const ctx = await makeRun('prepared', {download:0,send:0,verify:0});
  let sendCalls = 0;
  globalThis.__EXEC_EXEC_FILE__ = async (cmd, args) => {
    const stage = args[2];
    if (stage === '--download') {
      const mm = await fileId(ctx.config.raw.meituan), tt = await fileId(ctx.config.raw.taobao);
      await writeJson(ctx.config.downloadUiReceipt, {ok:true,runId:ctx.runId,businessDate:ctx.businessDate,runtimeModelDecisions:0,jinshaResourceReleased:true,clicks:{meituan:1,taobao:1},files:{meituan:mm,taobao:tt}});
    } else if (stage === '--prepare') {
      const bM = await fileId(ctx.builtM), bT = await fileId(ctx.builtT);
      await writeJson(ctx.config.examReceipt, {ok:true,stage:'prepared'});
      await writeJson(ctx.config.preflightReceipt, {ok:true,runId:ctx.runId,businessDate:ctx.businessDate,groupName:FIXED.group,authorization:FIXED.authorization,requestedWechatChannel:'desktop',stage:'prepared',files:{meituan:{name:ctx.config.sendNames.meituan,path:ctx.builtM,size:bM.size,sha256:bM.sha256},taobao:{name:ctx.config.sendNames.taobao,path:ctx.builtT,size:bT.size,sha256:bT.sha256}}});
      await writeJson(ctx.config.buildReceipt, {files:{meituan:{name:ctx.config.sendNames.meituan,file:ctx.builtM},taobao:{name:ctx.config.sendNames.taobao,file:ctx.builtT}}});
    } else if (stage === '--send') { sendCalls++; return {ok:false,stdout:'',stderr:'send failed'}; }
    else if (stage === '--verify-only') { return {ok:false,stdout:'',stderr:'verify failed'}; }
    return {ok:true,stdout:'',stderr:''};
  };
  try {
    await assert.rejects(async () => m.executeRun({config:ctx.config,state:JSON.parse(await fs.readFile(ctx.config.workflowState,'utf8')),runDir:ctx.runDir}), /desktop-preflight-retry-limit-exceeded/);
    assert.ok(sendCalls >= 2, `应经历至少一次 sleep 重试，实际 sendCalls=${sendCalls}`);
  } finally { delete globalThis.__EXEC_EXEC_FILE__; }
});

// L112/L114 downloadPhase 循环跳过分支：attempts.download 已达上限 → while 条件为假 → 跳过循环体直达 needs-maintenance block
e2eTest('executor downloadPhase 起始即达上限 → 跳过循环 block(needs-maintenance)', async () => {
  const m = await import(EXEC);
  const ctx = await makeRun('created', {download:3,send:0,verify:0});
  globalThis.__EXEC_EXEC_FILE__ = async () => ({ok:true,stdout:'',stderr:''});
  try {
    await assert.rejects(async () => m.executeRun({config:ctx.config,state:JSON.parse(await fs.readFile(ctx.config.workflowState,'utf8')),runDir:ctx.runDir}), /download-retry-limit-exceeded/);
  } finally { delete globalThis.__EXEC_EXEC_FILE__; }
});

// L122/L126 sendPhase 循环跳过分支：attempts.send 已达上限 → while 条件为假 → 跳过循环体直达 needs-resume block
e2eTest('executor sendPhase 起始即达上限 → 跳过循环 block(needs-resume)', async () => {
  const m = await import(EXEC);
  const ctx = await makeRun('prepared', {download:0,send:4,verify:0});
  globalThis.__EXEC_EXEC_FILE__ = async () => ({ok:true,stdout:'',stderr:''});
  try {
    await assert.rejects(async () => m.executeRun({config:ctx.config,state:JSON.parse(await fs.readFile(ctx.config.workflowState,'utf8')),runDir:ctx.runDir}), /desktop-preflight-retry-limit-exceeded/);
  } finally { delete globalThis.__EXEC_EXEC_FILE__; }
});

test('executor selfTest', async () => {
  const m = await import(EXEC);
  const r = await m.selfTest();
  assert.strictEqual(r.ok, true); assert.strictEqual(r.runtimeModelDecisions, 0);
});
