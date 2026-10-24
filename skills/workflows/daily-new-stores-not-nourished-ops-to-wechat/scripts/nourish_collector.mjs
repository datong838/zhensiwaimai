#!/usr/bin/env node
// 采集器：连 9231 服务商平台，下载「运营效果(问题类型=新店未养活)」CSV 与「门店分配(已分配门店·根角色)」XLSX。
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
const PROBLEM_TYPE = '新店未养活';
// 角色树根节点（公司级）：门店分配页必须选它才能拿到全部已分配门店，否则只得默认角色名下门店。
const ROOT_ROLE_PREFIX = '上海臻肆文化传播有限公司';

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

async function selectByFormLabel(page, label, optionText) {
  const item = page.locator('.ant-form-item, [class*="form-item"]').filter({ hasText: label }).first();
  const sel = item.locator('.ant-select').first();
  await sel.click({ timeout: 6000 });
  await page.waitForTimeout(700);
  await page.locator('.ant-select-dropdown:visible .ant-select-item-option', { hasText: optionText })
    .first().click({ timeout: 6000 });
  await page.waitForTimeout(500);
  const shown = await item.innerText().catch(() => '');
  if (!shown.includes(optionText)) throw new Error(`select-not-applied:${label}:${optionText}`);
}

async function grabDownload(page, btnName, baseName, outdir) {
  const btn = page.getByRole('button', { name: btnName }).first();
  if (!(await btn.count())) throw new Error(`download-button-missing:${btnName}`);
  const dlP = page.waitForEvent('download', { timeout: 60000 });
  await btn.click({ timeout: 8000 });
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
  await page.waitForTimeout(7000);
  await loginGuard(page);
  // 问题类型 = 新店未养活
  await selectByFormLabel(page, '问题类型', PROBLEM_TYPE);
  await page.getByRole('button', { name: /查\s*询/ }).first().click({ timeout: 8000 });
  await page.waitForTimeout(5000);
  return grabDownload(page, '数据下载', 'effect', outdir);
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
  const dl = await grabDownload(page, '下载数据', 'alloc', outdir);
  return { ...dl, tableTotal: total };
}

async function main() {
  const outdir = process.argv[2];
  if (!outdir) throw new Error('outdir-required');
  fs.mkdirSync(outdir, { recursive: true, mode: 0o700 });
  const lease = await acquirePostLease(`nourish-collect-${Date.now()}`);
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
  const code = msg.includes('service-login-required') ? 'service-login-required' : 'nourish-collect-failed';
  flushExit(1, { status: 'unknown', code, reason: msg.slice(0, 400) });
});
