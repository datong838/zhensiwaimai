#!/usr/bin/env node
// 采集器（岗位 9231 服务商平台 open.shop.ele.me）：
//   1) 代运营 → 运营效果分析 → 直接点「数据下载」（不加任何筛选条件，全量；数据量大，等它下载完）
//   2) 门店分配 → 外卖店 → 已分配门店 → 选公司级根角色 → 点「下载数据」（全量已分配门店，含 运营人）
// 只读 + 触发站点自身下载；不新建标签页；收尾复位到 home。flushExit 保证进程退出（防 CDP 句柄挂起）。
import { createRequire } from 'node:module';
import { connectToPost } from '../../../posts/taobao-svc-post/scripts/connect.mjs';
import { acquirePostLease, releasePostLease } from '../../../posts/taobao-svc-post/scripts/lease.mjs';
import { assertAuthenticated, assertOrigin } from '../../../posts/taobao-svc-post/scripts/auth.mjs';
const require = createRequire(import.meta.url);
const fs = require('node:fs');
const path = require('node:path');

const HOME = 'https://open.shop.ele.me/manager/base/home';
const EFFECT = 'https://open.shop.ele.me/manager/base/operations-effect';
const ALLOC = 'https://open.shop.ele.me/manager/base/store-allocation';
// 角色树根节点（公司级）：门店分配页必须选它才能拿到全部已分配门店，否则只得默认角色名下门店。
const ROOT_ROLE_PREFIX = '上海臻肆文化传播有限公司';
// 全量运营效果导出比参考流（新店未养活子集）大得多，导出可能耗时数分钟。
const EFFECT_DOWNLOAD_TIMEOUT_MS = 300000;
const ALLOC_DOWNLOAD_TIMEOUT_MS = 120000;

function flushExit(code, payload) {
  const out = JSON.stringify(payload);
  process.stdout.write(out + '\n', () => process.exit(code));
  setTimeout(() => process.exit(code), 3000).unref(); // 写入异常时的兜底
}

async function loginGuard(page) {
  assertOrigin(page.url());
  const body = await page.evaluate(() => (document.body && document.body.innerText) || '');
  assertAuthenticated(body); // 命中登录特征 → service-login-required
}

async function grabDownload(page, btnName, baseName, outdir, timeoutMs) {
  const btn = page.getByRole('button', { name: btnName }).first();
  if (!(await btn.count())) throw new Error(`download-button-missing:${btnName}`);
  const dlP = page.waitForEvent('download', { timeout: timeoutMs });
  await btn.click({ timeout: 15000 });
  const dl = await dlP;
  const suggested = dl.suggestedFilename() || '';
  const ext = (path.extname(suggested) || '').toLowerCase() || '.bin';
  const target = path.join(outdir, baseName + ext);
  await dl.saveAs(target);
  const size = fs.statSync(target).size;
  if (!size) throw new Error(`download-empty:${baseName}`);
  return { path: target, suggested, size };
}

async function downloadEffect(page, outdir) {
  await page.goto(HOME, { waitUntil: 'domcontentloaded', timeout: 45000 });
  await page.waitForTimeout(4000);
  await page.goto(EFFECT, { waitUntil: 'domcontentloaded', timeout: 45000 });
  await page.waitForTimeout(8000);
  await loginGuard(page);
  // 不做任何筛选（大同口径：直接点数据下载）。先确认列表已渲染，避免空表导出。
  const body = await page.evaluate(() => (document.body && document.body.innerText) || '');
  if (!body.includes('门店列表')) throw new Error('effect-list-not-rendered');
  const m = body.match(/共\s*(\d+)\s*条/);
  const tableTotal = m ? Number(m[1]) : null;
  if (tableTotal !== null && tableTotal < 1) throw new Error(`effect-empty-table:${tableTotal}`);
  const dl = await grabDownload(page, '数据下载', 'effect', outdir, EFFECT_DOWNLOAD_TIMEOUT_MS);
  return { ...dl, tableTotal };
}

async function downloadAlloc(page, outdir) {
  await page.goto(ALLOC, { waitUntil: 'domcontentloaded', timeout: 45000 });
  await page.waitForTimeout(7000);
  await loginGuard(page);
  // 外卖店 tab（默认已选，仍显式点一次）
  await page.getByText('外卖店', { exact: true }).first().click({ timeout: 5000 }).catch(() => {});
  await page.waitForTimeout(1200);
  // 已分配门店 tab
  await page.getByText('已分配门店', { exact: true }).first().click({ timeout: 5000 }).catch(() => {});
  await page.waitForTimeout(2000);
  // 选根角色（公司级）→ 全量已分配门店
  const rootNode = page.getByText(new RegExp(`^${ROOT_ROLE_PREFIX}`)).first();
  if (!(await rootNode.count())) throw new Error('alloc-root-role-missing');
  await rootNode.click({ timeout: 6000 });
  await page.waitForTimeout(5000);
  const body = await page.evaluate(() => (document.body && document.body.innerText) || '');
  const m = body.match(/共\s*(\d+)\s*条/);
  const total = m ? Number(m[1]) : null;
  if (total !== null && total < 2) throw new Error(`alloc-root-role-too-few:${total}`);
  const dl = await grabDownload(page, '下载数据', 'alloc', outdir, ALLOC_DOWNLOAD_TIMEOUT_MS);
  return { ...dl, tableTotal: total };
}

async function main() {
  const outdir = process.argv[2];
  if (!outdir) throw new Error('outdir-required');
  fs.mkdirSync(outdir, { recursive: true, mode: 0o700 });
  const lease = await acquirePostLease(`taskrate-collect-${Date.now()}`);
  if (!lease) { flushExit(0, { status: 'skipped', reason: 'post-lease-busy', port: 9231 }); return; }
  let browser, result;
  try {
    const conn = await connectToPost();
    browser = conn.browser;
    const page = conn.page;
    const effect = await downloadEffect(page, outdir);
    const alloc = await downloadAlloc(page, outdir);
    await page.goto(HOME, { waitUntil: 'domcontentloaded', timeout: 30000 }).catch(() => {});
    result = { status: 'complete', checkedAt: new Date().toISOString(),
      effect, alloc, restoredUrl: page.url() };
  } finally {
    // 必须先把浏览器断开 + 释放工位锁，再 flushExit（process.exit 会跳过 finally）。
    await browser?.close().catch(() => {});
    await releasePostLease(lease).catch(() => {});
  }
  flushExit(0, result);
}
main().catch(e => {
  // 登录失效 → 明确错误码交上层 blocked；其余 unknown。
  const msg = String((e && e.message) || e);
  const code = msg.includes('service-login-required') ? 'service-login-required' : 'taskrate-collect-failed';
  flushExit(1, { status: 'unknown', code, reason: msg.slice(0, 400) });
});