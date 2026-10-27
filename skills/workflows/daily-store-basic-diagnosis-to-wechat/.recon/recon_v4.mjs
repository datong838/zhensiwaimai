#!/usr/bin/env node
// 侦察 v4：点页面「下载」按钮，抓导出文件 + 导出接口。
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
    const OO = XMLHttpRequest.prototype.open, OS = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function (m, u, ...rest) { this.__u = u; this.__m = m; return OO.call(this, m, u, ...rest); };
    XMLHttpRequest.prototype.send = function (b) {
      const url = this.__u, method = this.__m;
      this.addEventListener('load', () => {
        try { if (/Export|export|Download|download|pageQueryOpenTaskMerchantList|queryOpenOpTaskFactors|oShopOpTask/.test(String(url))) push({ url, reqBody: String(b || '').slice(0, 600), respLen: String(this.responseText || '').length, respHead: String(this.responseText || '').slice(0, 400), via: 'xhr', method }); } catch (e) {}
      });
      return OS.call(this, b);
    };
  });
}

async function main() {
  const lease = await acquirePostLease(`diag-recon4-${Date.now()}`);
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

    // 选「服务功能丰富度不足」(3家·小) 先看导出结构
    await page.locator('label', { hasText: '服务功能丰富度不足' }).first().click({ timeout: 6000 }).catch(e => console.log('radio err', e.message));
    await page.waitForTimeout(6000);

    const btn = page.locator('.AgencyDiagnose--downLoad--1B_iAco').first();
    console.log('download div count:', await btn.count());
    const dlP = page.waitForEvent('download', { timeout: 60000 }).catch(e => { console.log('dl event err', e.message); return null; });
    await btn.click({ timeout: 8000 }).catch(e => console.log('click err', e.message));
    const dl = await dlP;
    if (dl) {
      const suggested = dl.suggestedFilename() || 'download.bin';
      const target = path.join(RECON, 'diag-export-' + suggested.replace(/[^\w.\-\u4e00-\u9fa5]/g, '_'));
      await dl.saveAs(target);
      console.log('DOWNLOADED:', JSON.stringify({ suggested, target, size: fs.statSync(target).size }));
    } else {
      console.log('NO DOWNLOAD EVENT');
      await page.waitForTimeout(5000);
    }

    await page.waitForTimeout(2000);
    const caps = await page.evaluate(() => window.__cap || []);
    console.log('\n=== CAPTURED (recon4) ===');
    for (const c of caps) {
      console.log('---', c.via, c.method || '', c.url.split('?')[0]);
      console.log('   reqBody:', (c.reqBody || '').slice(0, 400));
      console.log('   respLen:', c.respLen, 'head:', (c.respHead || '').replace(/\n/g, ' ').slice(0, 220));
    }
    await page.screenshot({ path: path.join(RECON, 'diag-v4.png') }).catch(() => {});
    await page.goto(HOME, { waitUntil: 'domcontentloaded', timeout: 30000 }).catch(() => {});
    console.log('[restore] url =', page.url());
  } finally {
    await browser?.close().catch(() => {});
    if (lease) await releasePostLease(lease).catch(() => {});
  }
}
main().catch(e => { console.error(JSON.stringify({ status: 'failed', reason: String(e && e.message || e).slice(0, 600) })); process.exitCode = 1; });
