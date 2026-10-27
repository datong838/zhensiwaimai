#!/usr/bin/env node
// 侦察 v5：抓 list 请求的【完整请求头】+ 分页 DOM；并测试「同体重放 vs 改 pageSize 重放」。
import { createRequire } from 'node:module';
import { connectToPost } from '../../../posts/taobao-svc-post/scripts/connect.mjs';
import { acquirePostLease, releasePostLease } from '../../../posts/taobao-svc-post/scripts/lease.mjs';
const require = createRequire(import.meta.url);
const fs = require('node:fs');
const path = require('node:path');

const RECON = path.dirname(new URL(import.meta.url).pathname);
const HOME = 'https://open.shop.ele.me/manager/base/home';
const DIAG = 'https://open.shop.ele.me/manager/base/abnormal-diagnosis';

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
        try {
          if (/pageQueryOpenTaskMerchantList/.test(String(url)))
            push({ url, reqBody: String(b || ''), headers: headers || {}, respLen: String(this.responseText || '').length, via: 'xhr', method });
        } catch (e) {}
      });
      return OS.call(this, b);
    };
  });
}

async function main() {
  const lease = await acquirePostLease(`diag-recon5-${Date.now()}`);
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

    // 选最大指标 顾客评分低 (731)
    await page.locator('label', { hasText: '顾客评分低' }).first().click({ timeout: 6000 }).catch(e => console.log('radio err', e.message));
    await page.waitForTimeout(7000);

    // 分页 DOM
    const pag = await page.evaluate(() => {
      const el = document.querySelector('.ant-pagination, [class*="pagination"]');
      return el ? el.outerHTML.slice(0, 1500) : 'NO PAGINATION';
    });
    console.log('=== pagination DOM ===');
    console.log(pag);

    // 表体总条数文字
    const totalTxt = await page.evaluate(() => {
      const t = (document.body.innerText || '');
      const m = t.match(/共\s*(\d+)\s*条/);
      return m ? m[1] : '(no 共N条 text)';
    });
    console.log('=== total text ===', totalTxt);

    const caps = await page.evaluate(() => window.__cap.filter(c => /pageQueryOpenTaskMerchantList/.test(c.url)));
    const last = caps[caps.length - 1];
    console.log('\n=== list req headers ===');
    console.log(JSON.stringify(last ? last.headers : {}, null, 2));
    console.log('=== list req body ===', last ? last.reqBody : 'NONE');

    // 重放 A：同体同头
    if (last) {
      const rA = await page.evaluate(async (rec) => {
        try {
          const r = await fetch(rec.url, { method: 'POST', headers: { ...rec.headers }, body: rec.reqBody, credentials: 'include' });
          const j = await r.json();
          return { http: r.status, code: j.code, message: j.message, totalCount: j.totalCount, rows: Array.isArray(j.data) ? j.data.length : null };
        } catch (e) { return { err: String(e) }; }
      }, last);
      console.log('\n=== 重放A: 同体同头 ===', JSON.stringify(rA));

      // 重放 B：同头 + pageSize=1000
      const rB = await page.evaluate(async (rec) => {
        try {
          const body = JSON.parse(rec.reqBody); body.pageSize = 1000; body.current = 1;
          const r = await fetch(rec.url, { method: 'POST', headers: { ...rec.headers }, body: JSON.stringify(body), credentials: 'include' });
          const j = await r.json();
          return { http: r.status, code: j.code, message: j.message, totalCount: j.totalCount, rows: Array.isArray(j.data) ? j.data.length : null };
        } catch (e) { return { err: String(e) }; }
      }, last);
      console.log('=== 重放B: 改 pageSize=1000 ===', JSON.stringify(rB));

      // 重放 C：同头 + current=2（分页可行性）
      const rC = await page.evaluate(async (rec) => {
        try {
          const body = JSON.parse(rec.reqBody); body.current = 2;
          const r = await fetch(rec.url, { method: 'POST', headers: { ...rec.headers }, body: JSON.stringify(body), credentials: 'include' });
          const j = await r.json();
          return { http: r.status, code: j.code, message: j.message, rows: Array.isArray(j.data) ? j.data.length : null,
                   firstShop: Array.isArray(j.data) && j.data[0] ? j.data[0].shop_id : null };
        } catch (e) { return { err: String(e) }; }
      }, last);
      console.log('=== 重放C: current=2 ===', JSON.stringify(rC));
    }

    await page.screenshot({ path: path.join(RECON, 'diag-v5.png') }).catch(() => {});
    await page.goto(HOME, { waitUntil: 'domcontentloaded', timeout: 30000 }).catch(() => {});
    console.log('[restore] url =', page.url());
  } finally {
    await browser?.close().catch(() => {});
    if (lease) await releasePostLease(lease).catch(() => {});
  }
}
main().catch(e => { console.error(JSON.stringify({ status: 'failed', reason: String(e && e.message || e).slice(0, 600) })); process.exitCode = 1; });
