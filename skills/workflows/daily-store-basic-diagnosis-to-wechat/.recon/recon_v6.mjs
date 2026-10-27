#!/usr/bin/env node
// 侦察 v6：验证「一份凭证 + 换 agentCode + pageSize=5000」能否一次拉全 14 个指标。
import { createRequire } from 'node:module';
import { connectToPost } from '../../../posts/taobao-svc-post/scripts/connect.mjs';
import { acquirePostLease, releasePostLease } from '../../../posts/taobao-svc-post/scripts/lease.mjs';
const require = createRequire(import.meta.url);
const fs = require('node:fs');
const path = require('node:path');

const RECON = path.dirname(new URL(import.meta.url).pathname);
const HOME = 'https://open.shop.ele.me/manager/base/home';
const DIAG = 'https://open.shop.ele.me/manager/base/abnormal-diagnosis';

const AGENTS = [
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

async function main() {
  const lease = await acquirePostLease(`diag-recon6-${Date.now()}`);
  if (!lease) { console.log(JSON.stringify({ status: 'skipped', reason: 'post-lease-busy' })); return; }
  let browser;
  try {
    const conn = await connectToPost();
    browser = conn.browser;
    const page = conn.page;
    await installInterceptor(page);
    await page.goto(HOME, { waitUntil: 'domcontentloaded', timeout: 45000 });
    await page.waitForTimeout(3000);
    await page.goto(DIAG, { waitUntil: 'domcontentloaded', timeout: 45000 });
    await page.waitForTimeout(9000);
    // 触发一次真实 list 请求（拿一份凭证）
    await page.locator('label', { hasText: '服务功能丰富度不足' }).first().click({ timeout: 6000 }).catch(() => {});
    await page.waitForTimeout(6000);

    const caps = await page.evaluate(() => window.__cap.filter(c => /pageQueryOpenTaskMerchantList/.test(c.url)));
    const base = caps[caps.length - 1];
    if (!base) { console.log('NO BASE REQUEST'); return; }
    console.log('base url:', base.url.split('?')[0]);
    console.log('base headers:', JSON.stringify(base.headers));

    // 换 agentCode + pageSize=5000 批量重放
    const out = await page.evaluate(async ({ rec, agents }) => {
      const res = {};
      for (const [code, name] of agents) {
        try {
          const body = JSON.parse(rec.reqBody);
          body.agentCode = code; body.pageSize = 1000; body.current = 1; body.shopIdListIn = '';
          const r = await fetch(rec.url, { method: 'POST', headers: { ...rec.headers }, body: JSON.stringify(body), credentials: 'include' });
          const j = await r.json();
          res[name] = { http: r.status, code: j.code, totalCount: j.totalCount, rows: Array.isArray(j.data) ? j.data.length : null,
                        hasShopId: Array.isArray(j.data) && j.data[0] ? ('shop_id' in j.data[0]) : null,
                        sample: Array.isArray(j.data) && j.data[0] ? { shop_id: j.data[0].shop_id, shop_name: j.data[0].shop_name, task_name: j.data[0].task_name } : null,
                        msg: j.message };
        } catch (e) { res[name] = { err: String(e) }; }
      }
      return res;
    }, { rec: base, agents: AGENTS });

    console.log('\n=== 换 agentCode 批量重放(pageSize=1000)结果 ===');
    console.log(JSON.stringify(out, null, 2));

    // pageSize 上限探测（用最大指标 731）
    const probe = await page.evaluate(async ({ rec, code }) => {
      const res = {};
      for (const ps of [200, 500, 1000, 1500, 2000]) {
        try {
          const body = JSON.parse(rec.reqBody);
          body.agentCode = code; body.pageSize = ps; body.current = 1; body.shopIdListIn = '';
          const r = await fetch(rec.url, { method: 'POST', headers: { ...rec.headers }, body: JSON.stringify(body), credentials: 'include' });
          const j = await r.json();
          res['ps' + ps] = { code: j.code, totalCount: j.totalCount, rows: Array.isArray(j.data) ? j.data.length : null };
        } catch (e) { res['ps' + ps] = { err: String(e) }; }
      }
      return res;
    }, { rec: base, code: 'material_shop_rating' });
    console.log('\n=== pageSize 上限探测(顾客评分低 731) ===');
    console.log(JSON.stringify(probe, null, 2));

    await page.goto(HOME, { waitUntil: 'domcontentloaded', timeout: 30000 }).catch(() => {});
    console.log('[restore] url =', page.url());
  } finally {
    await browser?.close().catch(() => {});
    if (lease) await releasePostLease(lease).catch(() => {});
  }
}
main().catch(e => { console.error(JSON.stringify({ status: 'failed', reason: String(e && e.message || e).slice(0, 700) })); process.exitCode = 1; });
