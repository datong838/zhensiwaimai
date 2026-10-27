#!/usr/bin/env node
// 采集器：连 9231 服务商平台「经营任务→基础诊断」，采集 14 个基础诊断指标的「未完成」任务商户列表（含门店ID），
// 并下载「门店分配(已分配门店·根角色)」XLSX。只读 + 触发站点自身下载；收尾复位 home；flushExit 保证进程退出。
//
// 关键实现（2026-10-13 实测）：
//  - 站点自带「下载」的 CSV 列 = 门店名称/问题分析/当前值/目标值/状态 —— 【不含门店ID】，故不可用于关联。
//  - 改用列表接口 pageQueryOpenTaskMerchantList（响应含 shop_id），在页面上下文内重放：
//      * 需要请求头 `token`（缺失则 401 401002）；Content-Type: application/json；credentials:'include'
//      * 一次加载页面即产生一条可用凭证（secretkey/timestamp/openUserId/shopId/unitId 都取自被截获请求体）
//      * 签名不覆盖 pageSize/agentCode ⇒ 可换 agentCode 批量拉 14 指标，且 pageSize=1000 一次取全量
//      * 分页兜底：若 rows < totalCount 则递增 current 继续拉
import { createRequire } from 'node:module';
import { connectToPost } from '../../../posts/taobao-svc-post/scripts/connect.mjs';
import { acquirePostLease, releasePostLease } from '../../../posts/taobao-svc-post/scripts/lease.mjs';
import { assertAuthenticated, assertOrigin } from '../../../posts/taobao-svc-post/scripts/auth.mjs';
const require = createRequire(import.meta.url);
const fs = require('node:fs');
const path = require('node:path');

const HOME = 'https://open.shop.ele.me/manager/base/home';
const DIAG = 'https://open.shop.ele.me/manager/base/abnormal-diagnosis';
const ALLOC = 'https://open.shop.ele.me/manager/base/store-allocation';
const ROOT_ROLE_PREFIX = '上海臻肆文化传播有限公司';
const PAGE_SIZE = 1000;
const MAX_PAGES = 30;

const METRICS = [
  ['material_service_set_cnt', '服务功能丰富度不足'],
  ['material_shop_set_cnt', '店装丰富度不足'],
  ['material_peak_open_duration_7d', '高峰营业时长低'],
  ['material_open_time_avg_7d', '营业时长低'],
  ['material_base_delivery_price', '最低起送价高'],
  ['material_cooking_over_click_rate_7d', '出餐完成上报率低'],
  ['material_ontime_delivery_rate_7d', '送达准时率低'],
  ['material_shop_responsibility_cancel_rate_7d', '商责取消率高'],
  ['material_negative_reply_rate_7d', '差评回复率低'],
  ['material_im_reply_5min_rate_7d', '在线联系回复率低'],
  ['material_shop_rating', '顾客评分低'],
  ['material_market_set_cnt', '有效活动丰富度不足'],
  ['material_item_set_cnt', '菜单丰富度不足'],
  ['material_quality_entree_proportion_rate', '优质商品率低'],
];

function flushExit(code, payload) {
  process.stdout.write(JSON.stringify(payload) + '\n', () => process.exit(code));
  setTimeout(() => process.exit(code), 3000).unref();
}

async function installInterceptor(page) {
  await page.addInitScript(() => {
    window.__cap = [];
    const push = (r) => { try { window.__cap.push(r); } catch (e) {} };
    const OO = XMLHttpRequest.prototype.open, OS = XMLHttpRequest.prototype.send, SRH = XMLHttpRequest.prototype.setRequestHeader;
    XMLHttpRequest.prototype.open = function (m, u, ...rest) { this.__u = u; this.__m = m; this.__h = {}; return OO.call(this, m, u, ...rest); };
    XMLHttpRequest.prototype.setRequestHeader = function (k, v) { try { this.__h[k] = v; } catch (e) {} return SRH.call(this, k, v); };
    XMLHttpRequest.prototype.send = function (b) {
      const url = this.__u, method = this.__m, headers = this.__h;
      this.addEventListener('load', () => {
        try { if (/pageQueryOpenTaskMerchantList/.test(String(url))) push({ url, reqBody: String(b || ''), headers: headers || {}, via: 'xhr', method }); } catch (e) {}
      });
      return OS.call(this, b);
    };
  });
}

async function loginGuard(page) {
  assertOrigin(page.url());
  const body = await page.evaluate(() => (document.body && document.body.innerText) || '');
  assertAuthenticated(body);
}

function pickRows(list) {
  return (list || []).map(r => ({
    shop_id: r.shop_id, shop_name: r.shop_name, task_name: r.task_name,
    task_status: r.task_status, current_value: r.current_value, target_value: r.target_value,
  }));
}

async function collectDiagnosis(page) {
  await page.goto(HOME, { waitUntil: 'domcontentloaded', timeout: 45000 });
  await page.waitForTimeout(3000);
  await page.goto(DIAG, { waitUntil: 'domcontentloaded', timeout: 45000 });
  await page.waitForTimeout(9000);
  await loginGuard(page);

  let caps = await page.evaluate(() => (window.__cap || []).filter(c => /pageQueryOpenTaskMerchantList/.test(c.url)));
  if (!caps.length) {
    // 兜底：页面未自动发起列表请求时，点一次首个指标触发
    await page.locator('label', { hasText: '服务功能丰富度不足' }).first().click({ timeout: 6000 }).catch(() => {});
    await page.waitForTimeout(6000);
    caps = await page.evaluate(() => (window.__cap || []).filter(c => /pageQueryOpenTaskMerchantList/.test(c.url)));
  }
  const base = caps[caps.length - 1];
  if (!base) throw new Error('diag-credential-capture-failed');
  if (!base.headers || !base.headers.token) throw new Error('diag-token-header-missing');

  const out = await page.evaluate(async ({ rec, metrics, pageSize, maxPages }) => {
    const result = {};
    for (const [code, name] of metrics) {
      const body = JSON.parse(rec.reqBody);
      body.agentCode = code; body.pageSize = pageSize; body.current = 1; body.shopIdListIn = '';
      let current = 1, collected = [], total = null;
      while (current <= maxPages) {
        body.current = current;
        const r = await fetch(rec.url, { method: 'POST', headers: { ...rec.headers }, body: JSON.stringify(body), credentials: 'include' });
        const j = await r.json();
        if (j.code !== 0) { result[name] = { error: 'code-' + j.code, message: j.message, rows: [] }; break; }
        if (total === null) total = j.totalCount || 0;
        const rows = Array.isArray(j.data) ? j.data : [];
        collected = collected.concat(rows);
        if (!rows.length || collected.length >= total) { result[name] = { totalCount: total, rows: collected }; break; }
        current += 1;
        if (current > maxPages) { result[name] = { totalCount: total, rows: collected, truncated: true }; }
      }
    }
    return result;
  }, { rec: base, metrics: METRICS, pageSize: PAGE_SIZE, maxPages: MAX_PAGES });

  const metrics = {};
  for (const [code, name] of METRICS) {
    const r = out[name] || {};
    metrics[name] = { agentCode: code, totalCount: r.totalCount ?? null, rows: pickRows(r.rows) };
  }
  return { metrics, credentialUrl: base.url.split('?')[0] };
}

async function grabDownload(page, btnName, baseName, outdir) {
  const btn = page.getByRole('button', { name: btnName }).first();
  if (!(await btn.count())) throw new Error(`download-button-missing:${btnName}`);
  const dlP = page.waitForEvent('download', { timeout: 90000 });
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

async function downloadAlloc(page, outdir) {
  await page.goto(ALLOC, { waitUntil: 'domcontentloaded', timeout: 45000 });
  await page.waitForTimeout(7000);
  await loginGuard(page);
  await page.getByText('外卖店', { exact: true }).first().click({ timeout: 5000 }).catch(() => {});
  await page.waitForTimeout(1200);
  await page.getByText('已分配门店', { exact: true }).first().click({ timeout: 5000 }).catch(() => {});
  await page.waitForTimeout(2000);
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
  const lease = await acquirePostLease(`basic-diag-collect-${Date.now()}`);
  if (!lease) { flushExit(0, { status: 'skipped', reason: 'post-lease-busy', port: 9231 }); return; }
  let browser, result;
  try {
    const conn = await connectToPost();
    browser = conn.browser;
    const page = conn.page;
    await installInterceptor(page);
    const diag = await collectDiagnosis(page);
    const alloc = await downloadAlloc(page, outdir);
    await page.goto(HOME, { waitUntil: 'domcontentloaded', timeout: 30000 }).catch(() => {});
    const counts = {};
    for (const [k, v] of Object.entries(diag.metrics)) counts[k] = v.rows.length;
    result = { status: 'complete', checkedAt: new Date().toISOString(), alloc, metricCounts: counts, restoredUrl: page.url() };
    fs.writeFileSync(path.join(outdir, 'diagnosis.json'), JSON.stringify(diag, null, 2));
  } finally {
    await browser?.close().catch(() => {});
    await releasePostLease(lease).catch(() => {});
  }
  flushExit(0, result);
}
main().catch(e => {
  const msg = String((e && e.message) || e);
  const code = msg.includes('service-login-required') ? 'service-login-required' : 'basic-diag-collect-failed';
  flushExit(1, { status: 'unknown', code, reason: msg.slice(0, 400) });
});
