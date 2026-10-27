#!/usr/bin/env node
// 一次性侦察：连 9230，导航服务商平台两页，截图 + dump 关键元素，末尾复位回 chain seed。
import { createRequire } from 'node:module';
import { connectToPost } from '../../../posts/taobao-brand-post/scripts/connect.mjs';
import { acquirePostLease, releasePostLease } from '../../../posts/taobao-brand-post/scripts/lease.mjs';
const require = createRequire(import.meta.url);
const fs = require('node:fs');
const path = require('node:path');

const RECON = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..', '.recon');
const CHAIN_HOME = 'https://melody.shop.ele.me/app/chain/95708808/stats__center#app.chainshop.stats.center';
const EFFECT_URL = 'https://open.shop.ele.me/manager/base/operations-effect';
const ALLOC_URL = 'https://open.shop.ele.me/manager/base/store-allocation';

async function dumpPage(page, tag) {
  await page.waitForTimeout(4000);
  const url = page.url();
  const title = await page.title().catch(() => '');
  const info = await page.evaluate(() => {
    const txt = (document.body && document.body.innerText) || '';
    const buttons = [...document.querySelectorAll('button, [role="button"], a')]
      .map(e => (e.innerText || '').replace(/\s+/g, ' ').trim()).filter(Boolean).slice(0, 60);
    return {
      bodyLen: txt.length,
      hasLoginWord: /登录|扫码|账号密码/.test(txt),
      head: txt.slice(0, 400),
      buttons,
      selects: [...document.querySelectorAll('.ant-select, .cook-select, [class*="select"]')].length,
      tables: [...document.querySelectorAll('table, .ant-table, .cook-table, [class*="table"]')].length,
      iframes: [...document.querySelectorAll('iframe')].map(f => f.src).slice(0, 10),
    };
  }).catch(e => ({ err: String(e.message || e) }));
  console.log(`\n===== [${tag}] ${url} =====`);
  console.log('title:', title);
  console.log(JSON.stringify(info, null, 2));
  const shot = path.join(RECON, `${tag}.png`);
  await page.screenshot({ path: shot, fullPage: false }).catch(e => console.log('shot err', e.message));
  console.log('screenshot:', shot);
  return { url, title, info };
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
    await dumpPage(page, 'operations-effect');

    await page.goto(ALLOC_URL, { waitUntil: 'domcontentloaded', timeout: 45000 });
    await dumpPage(page, 'store-allocation');

    // 复位回 chain seed（谁弄脏谁恢复）
    await page.goto(CHAIN_HOME, { waitUntil: 'domcontentloaded', timeout: 30000 }).catch(() => {});
    console.log('\n[restore] url =', page.url());
  } finally {
    await browser?.close().catch(() => {});
    if (lease) await releasePostLease(lease).catch(() => {});
  }
}
main().catch(e => { console.error(JSON.stringify({ status: 'failed', reason: String(e.message || e).slice(0, 500) })); process.exitCode = 1; });
