#!/usr/bin/env node
// 一次性侦察：连 9231 服务商平台「经营任务→基础诊断」，抓：
//  1) 指标清单接口 queryOpenOpTaskFactors（14 个指标的 agentCode/名称）
//  2) 任务商户列表接口 pageQueryOpenTaskMerchantList 的 请求体 + 响应体
//  3) 页面表格列（是否含「问题分析」）、分页控件、任务状态过滤器
// 只读 + 拦截，不触发任何下载；收尾复位 home。
import { createRequire } from 'node:module';
import { connectToPost } from '../../../posts/taobao-svc-post/scripts/connect.mjs';
import { acquirePostLease, releasePostLease } from '../../../posts/taobao-svc-post/scripts/lease.mjs';
const require = createRequire(import.meta.url);
const fs = require('node:fs');
const path = require('node:path');

const RECON = path.dirname(new URL(import.meta.url).pathname);
const HOME = 'https://open.shop.ele.me/manager/base/home';
const DIAG = 'https://open.shop.ele.me/manager/base/abnormal-diagnosis';

const TARGET = /pageQueryOpenTaskMerchantList|queryOpenOpTaskFactors|OpTaskFactor/;

async function installInterceptor(page) {
  await page.addInitScript(() => {
    window.__cap = [];
    const push = (rec) => { try { window.__cap.push(rec); } catch (e) {} };
    const of = window.fetch;
    window.fetch = async function (...args) {
      let url = '';
      let body = '';
      try {
        const a0 = args[0];
        url = (a0 && a0.url) ? a0.url : String(a0);
        body = (args[1] && args[1].body) ? String(args[1].body) : '';
      } catch (e) {}
      const res = await of.apply(this, args);
      try {
        if (typeof url === 'string' && /pageQueryOpenTaskMerchantList|queryOpenOpTaskFactors|OpTaskFactor/.test(url)) {
          const clone = res.clone();
          clone.text().then(t => push({ url, reqBody: body, respBody: t, via: 'fetch' })).catch(() => {});
        }
      } catch (e) {}
      return res;
    };
    const OO = XMLHttpRequest.prototype.open;
    const OS = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function (m, u, ...rest) { this.__u = u; this.__m = m; return OO.call(this, m, u, ...rest); };
    XMLHttpRequest.prototype.send = function (b) {
      const url = this.__u, method = this.__m;
      this.addEventListener('load', () => {
        try {
          if (typeof url === 'string' && /pageQueryOpenTaskMerchantList|queryOpenOpTaskFactors|OpTaskFactor/.test(url)) {
            push({ url, reqBody: String(b || ''), respBody: this.responseText, via: 'xhr', method });
          }
        } catch (e) {}
      });
      return OS.call(this, b);
    };
  });
}

async function main() {
  const lease = await acquirePostLease(`diag-recon-${Date.now()}`);
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

    const url = page.url();
    console.log('=== URL ===', url);
    console.log('=== TITLE ===', await page.title().catch(() => ''));

    // 1) 页面结构：指标项（radio）、任务状态过滤器、表格列、分页
    const info = await page.evaluate(() => {
      const txt = (document.body && document.body.innerText) || '';
      const radios = [...document.querySelectorAll('label.ant-radio-wrapper, .ant-radio-wrapper, [class*="radio-wrapper"], label[class*="item"]')]
        .map(e => (e.innerText || '').replace(/\s+/g, ' ').trim()).filter(Boolean).slice(0, 40);
      const selItems = [...document.querySelectorAll('.ant-form-item, [class*="form-item"]')]
        .map(e => (e.innerText || '').replace(/\s+/g, ' ').trim()).filter(Boolean).slice(0, 25);
      const ths = [...document.querySelectorAll('th, .ant-table-thead th, [class*="table-header"] [class*="cell"]')]
        .map(e => (e.innerText || '').replace(/\s+/g, ' ').trim()).filter(Boolean).slice(0, 30);
      const pageCtrl = [...document.querySelectorAll('.ant-pagination li, .ant-pagination-options, [class*="pagination"]')]
        .map(e => (e.innerText || e.getAttribute && (e.getAttribute('title') || '')) || '')
        .map(s => String(s).replace(/\s+/g, ' ').trim()).filter(Boolean).slice(0, 20);
      const buttons = [...document.querySelectorAll('button, [role="button"], a')]
        .map(e => (e.innerText || '').replace(/\s+/g, ' ').trim()).filter(Boolean).slice(0, 60);
      return { bodyLen: txt.length, head: txt.slice(0, 600), radios, selItems, ths, pageCtrl, buttons };
    });
    console.log('=== PAGE INFO ===');
    console.log(JSON.stringify(info, null, 2));

    await page.screenshot({ path: path.join(RECON, 'diag-initial.png') }).catch(e => console.log('shot err', e.message));

    // 2) 已捕获的接口
    const caps = await page.evaluate(() => window.__cap || []);
    fs.writeFileSync(path.join(RECON, 'caps.json'), JSON.stringify(caps, null, 2));
    console.log('\n=== CAPTURED API CALLS: ' + caps.length + ' ===');
    for (const c of caps) {
      let parsed = null;
      try { parsed = JSON.parse(c.respBody); } catch (e) {}
      console.log('---', c.via, c.url.split('?')[0]);
      console.log('   reqBody:', (c.reqBody || '').slice(0, 400));
      console.log('   respLen:', (c.respBody || '').length);
      if (parsed) {
        console.log('   code:', parsed.code, 'totalCount:', parsed.totalCount, 'totalPage:', parsed.totalPage);
        const d = parsed.data;
        if (Array.isArray(d) && d.length) console.log('   firstRowKeys:', Object.keys(d[0]).join(','));
        else if (d && !Array.isArray(d)) console.log('   dataKeys:', Object.keys(d).join(','));
      }
    }
  } finally {
    await browser?.close().catch(() => {});
    if (lease) await releasePostLease(lease).catch(() => {});
  }
}
main().catch(e => {
  console.error(JSON.stringify({ status: 'failed', reason: String(e && e.message || e).slice(0, 600) }));
  process.exitCode = 1;
});
