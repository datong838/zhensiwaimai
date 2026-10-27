#!/usr/bin/env node
// 侦察 v3：① 定位「下载」元素并测试导出（是否含门店ID、是否全量）② 测试放大 pageSize 重放是否可行。
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
    const of = window.fetch;
    window.fetch = async function (...args) {
      let url = '', body = '';
      try { const a0 = args[0]; url = (a0 && a0.url) ? a0.url : String(a0); body = (args[1] && args[1].body) ? String(args[1].body) : ''; } catch (e) {}
      const res = await of.apply(this, args);
      try { if (/Export|export|Download|download|pageQueryOpenTaskMerchantList|queryOpenOpTaskFactors/.test(url)) { res.clone().text().then(t => push({ url, reqBody: body, respLen: t.length, respHead: t.slice(0, 300), via: 'fetch' })).catch(() => {}); } } catch (e) {}
      return res;
    };
    const OO = XMLHttpRequest.prototype.open, OS = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function (m, u, ...rest) { this.__u = u; this.__m = m; return OO.call(this, m, u, ...rest); };
    XMLHttpRequest.prototype.send = function (b) {
      const url = this.__u, method = this.__m;
      this.addEventListener('load', () => {
        try { if (/Export|export|Download|download|pageQueryOpenTaskMerchantList|queryOpenOpTaskFactors/.test(String(url))) push({ url, reqBody: String(b || ''), respLen: String(this.responseText || '').length, respHead: String(this.responseText || '').slice(0, 300), via: 'xhr', method }); } catch (e) {}
      });
      return OS.call(this, b);
    };
  });
}

async function main() {
  const lease = await acquirePostLease(`diag-recon3-${Date.now()}`);
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

    // 选「顾客评分低」(731家·最多页) 压测
    await page.locator('label', { hasText: '顾客评分低' }).first().click({ timeout: 6000 }).catch(e => console.log('radio err', e.message));
    await page.waitForTimeout(6000);

    // 1) 定位「下载」元素
    const dlInfo = await page.evaluate(() => {
      const out = [];
      const all = [...document.querySelectorAll('*')];
      for (const e of all) {
        const t = (e.innerText || '').trim();
        if (t === '下载' && e.children.length === 0) {
          out.push({ tag: e.tagName, cls: e.className, id: e.id, outer: e.outerHTML.slice(0, 240),
                     parentTag: e.parentElement && e.parentElement.tagName, parentCls: e.parentElement && e.parentElement.className });
        }
      }
      return out.slice(0, 6);
    });
    console.log('=== 下载元素 ===');
    console.log(JSON.stringify(dlInfo, null, 2));

    // 2) 抓一条真实 list 请求体用于重放测试
    const capsBefore = await page.evaluate(() => window.__cap.filter(c => /pageQueryOpenTaskMerchantList/.test(c.url)).map(c => ({ url: c.url, reqBody: c.reqBody })));
    const lastList = capsBefore[capsBefore.length - 1];
    console.log('\n=== 真实 list 请求体 ===', lastList ? lastList.reqBody.slice(0, 300) : 'NONE');

    // 3) 重放测试：放大 pageSize（在页面上下文内调用，带 cookie）
    if (lastList) {
      const replay = await page.evaluate(async (rec) => {
        const body = JSON.parse(rec.reqBody);
        const out = {};
        for (const ps of [1000]) {
          body.pageSize = ps; body.current = 1;
          try {
            const r = await fetch(rec.url, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body), credentials: 'include' });
            const j = await r.json();
            out['ps' + ps] = { httpStatus: r.status, code: j.code, message: j.message, totalCount: j.totalCount, totalPage: j.totalPage, rows: Array.isArray(j.data) ? j.data.length : null,
                               firstKeys: Array.isArray(j.data) && j.data[0] ? Object.keys(j.data[0]).join(',') : null };
          } catch (e) { out['ps' + ps] = { err: String(e) }; }
        }
        return out;
      }, lastList);
      console.log('\n=== pageSize 重放结果 ===');
      console.log(JSON.stringify(replay, null, 2));
    }

    await page.screenshot({ path: path.join(RECON, 'diag-v3.png') }).catch(() => {});
    await page.goto(HOME, { waitUntil: 'domcontentloaded', timeout: 30000 }).catch(() => {});
    console.log('[restore] url =', page.url());
  } finally {
    await browser?.close().catch(() => {});
    if (lease) await releasePostLease(lease).catch(() => {});
  }
}
main().catch(e => { console.error(JSON.stringify({ status: 'failed', reason: String(e && e.message || e).slice(0, 600) })); process.exitCode = 1; });
