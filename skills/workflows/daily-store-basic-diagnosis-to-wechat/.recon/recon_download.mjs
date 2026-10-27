#!/usr/bin/env node
// 侦察 v2：连 9231 基础诊断页，选一个指标 → 点「下载」→ 抓下载文件 + 下载接口。
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
      try {
        if (/Export|export|Download|download|pageQueryOpenTaskMerchantList|queryOpenOpTaskFactors/.test(url)) {
          res.clone().text().then(t => push({ url, reqBody: body, respBody: t.slice(0, 60000), via: 'fetch' })).catch(() => {});
        }
      } catch (e) {}
      return res;
    };
    const OO = XMLHttpRequest.prototype.open, OS = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function (m, u, ...rest) { this.__u = u; this.__m = m; return OO.call(this, m, u, ...rest); };
    XMLHttpRequest.prototype.send = function (b) {
      const url = this.__u, method = this.__m;
      this.addEventListener('load', () => {
        try { if (/Export|export|Download|download|pageQueryOpenTaskMerchantList|queryOpenOpTaskFactors/.test(String(url))) push({ url, reqBody: String(b || ''), respBody: String(this.responseText || '').slice(0, 60000), via: 'xhr', method }); } catch (e) {}
      });
      return OS.call(this, b);
    };
  });
}

async function main() {
  const lease = await acquirePostLease(`diag-recon2-${Date.now()}`);
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

    // 选择「高峰营业时长低(212)」这个多页指标，验证下载是否含全量 + 门店ID
    const metricLabel = '高峰营业时长低';
    const radio = page.locator('label', { hasText: metricLabel }).first();
    await radio.click({ timeout: 6000 }).catch(e => console.log('radio click err', e.message));
    await page.waitForTimeout(6000);
    console.log('selected metric:', metricLabel);

    // 点「下载」
    const btn = page.getByRole('button', { name: /^下载$/ }).first();
    const cnt = await btn.count();
    console.log('下载 button count:', cnt);
    let dlInfo = null;
    if (cnt) {
      const dlP = page.waitForEvent('download', { timeout: 60000 }).catch(e => { console.log('download event err', e.message); return null; });
      await btn.click({ timeout: 8000 }).catch(e => console.log('click err', e.message));
      const dl = await dlP;
      if (dl) {
        const suggested = dl.suggestedFilename() || 'download.bin';
        const target = path.join(RECON, 'diag-download-' + suggested.replace(/[^\w.\-\u4e00-\u9fa5]/g, '_'));
        await dl.saveAs(target);
        dlInfo = { suggested, target, size: fs.statSync(target).size };
        console.log('DOWNLOADED:', JSON.stringify(dlInfo));
      }
    }
    await page.waitForTimeout(2000);

    const caps = await page.evaluate(() => window.__cap || []);
    fs.writeFileSync(path.join(RECON, 'caps2.json'), JSON.stringify(caps, null, 2));
    console.log('\n=== CAPTURED (recon2): ' + caps.length + ' ===');
    for (const c of caps) {
      const u = c.url.split('?')[0];
      console.log('---', c.via, c.method || '', u);
      console.log('   reqBody:', (c.reqBody || '').slice(0, 350));
      console.log('   respLen:', (c.respBody || '').length, 'head:', (c.respBody || '').slice(0, 160).replace(/\n/g, ' '));
    }
    await page.screenshot({ path: path.join(RECON, 'diag-after-download.png') }).catch(() => {});
    await page.goto(HOME, { waitUntil: 'domcontentloaded', timeout: 30000 }).catch(() => {});
    console.log('[restore] url =', page.url());
  } finally {
    await browser?.close().catch(() => {});
    if (lease) await releasePostLease(lease).catch(() => {});
  }
}
main().catch(e => { console.error(JSON.stringify({ status: 'failed', reason: String(e && e.message || e).slice(0, 600) })); process.exitCode = 1; });
