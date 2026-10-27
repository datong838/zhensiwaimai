#!/usr/bin/env node
// 侦察（9231 服务商平台）：导航 operations-effect / store-allocation，截图 + dump 关键元素，末尾复位。
import { createRequire } from 'node:module';
import { connectToPost } from '../../../posts/taobao-svc-post/scripts/connect.mjs';
import { acquirePostLease, releasePostLease } from '../../../posts/taobao-svc-post/scripts/lease.mjs';
const require = createRequire(import.meta.url);
const fs = require('node:fs');
const path = require('node:path');

const RECON = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..', '.recon');
const HOME = 'https://open.shop.ele.me/manager/base/home';
const EFFECT_URL = 'https://open.shop.ele.me/manager/base/operations-effect';
const ALLOC_URL = 'https://open.shop.ele.me/manager/base/store-allocation';

async function dumpPage(page, tag) {
  await page.waitForTimeout(5000);
  const info = await page.evaluate(() => {
    const txt = (document.body && document.body.innerText) || '';
    const pick = (kw) => [...document.querySelectorAll('button, [role="button"], a, span, div')]
      .filter(e => (e.innerText || '').replace(/\s+/g, '') === kw)
      .map(e => ({ tag: e.tagName, cls: e.className, txt: (e.innerText || '').trim() })).slice(0, 6);
    const allBtn = [...document.querySelectorAll('button, [role="button"]')]
      .map(e => (e.innerText || '').replace(/\s+/g, ' ').trim()).filter(Boolean).slice(0, 40);
    return {
      url: location.href, bodyLen: txt.length,
      head: txt.slice(0, 300),
      downloadBtns: pick('数据下载'),
      downloadBtns2: pick('下载数据'),
      queryBtns: pick('查询'),
      selectLike: [...document.querySelectorAll('.ant-select, .cook-select, .next-select, [class*="select"]')].length,
      tableHeaders: [...document.querySelectorAll('th, [class*="thead"] [class*="cell"], [class*="table"] [class*="header"] [class*="cell"]')]
        .map(e => (e.innerText || '').replace(/\s+/g, ' ').trim()).filter(Boolean).slice(0, 30),
      allBtn,
      iframes: [...document.querySelectorAll('iframe')].map(f => f.src).slice(0, 8),
      tabs: [...document.querySelectorAll('[class*="tab"]')].map(e => (e.innerText || '').replace(/\s+/g, ' ').trim()).filter(Boolean).slice(0, 20),
    };
  }).catch(e => ({ err: String(e.message || e) }));
  console.log(`\n===== [${tag}] =====`);
  console.log(JSON.stringify(info, null, 2));
  await page.screenshot({ path: path.join(RECON, `svc-${tag}.png`), fullPage: false }).catch(() => {});
  await page.screenshot({ path: path.join(RECON, `svc-${tag}-full.png`), fullPage: true }).catch(() => {});
  return info;
}

async function main() {
  const lease = await acquirePostLease(`unsheltered-recon-${Date.now()}`);
  if (!lease) { console.log(JSON.stringify({ status: 'skipped', reason: 'post-lease-busy' })); return; }
  let browser;
  try {
    const conn = await connectToPost();
    browser = conn.browser;
    const page = conn.page;
    fs.mkdirSync(RECON, { recursive: true, mode: 0o700 });

    await page.goto(EFFECT_URL, { waitUntil: 'domcontentloaded', timeout: 45000 });
    await dumpPage(page, 'effect');
    await page.goto(ALLOC_URL, { waitUntil: 'domcontentloaded', timeout: 45000 });
    await dumpPage(page, 'alloc');
    await page.goto(HOME, { waitUntil: 'domcontentloaded', timeout: 30000 }).catch(() => {});
    console.log('\n[restore] url =', page.url());
  } finally {
    await browser?.close().catch(() => {});
    if (lease) await releasePostLease(lease).catch(() => {});
  }
}
main().catch(e => { console.error(JSON.stringify({ status: 'failed', reason: String(e.message || e).slice(0, 500) })); process.exitCode = 1; });
