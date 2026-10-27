#!/usr/bin/env node
// 下载机制探针 v2：稳定定位 问题类型 select，查询→下载，落盘两页 Excel。
import { createRequire } from 'node:module';
import { connectToPost } from '../../../posts/taobao-svc-post/scripts/connect.mjs';
import { acquirePostLease, releasePostLease } from '../../../posts/taobao-svc-post/scripts/lease.mjs';
const require = createRequire(import.meta.url);
const fs = require('node:fs');
const path = require('node:path');
const RECON = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..', '.recon');
const HOME = 'https://open.shop.ele.me/manager/base/home';
const EFFECT = 'https://open.shop.ele.me/manager/base/operations-effect';
const ALLOC = 'https://open.shop.ele.me/manager/base/store-allocation';

async function selectByFormLabel(page, label, optionText) {
  const item = page.locator('.ant-form-item, [class*="form-item"]').filter({ hasText: label }).first();
  const sel = item.locator('.ant-select').first();
  const n = await sel.count();
  console.log(`[select:${label}] item/select count =`, n);
  await sel.click({ timeout: 6000 });
  await page.waitForTimeout(800);
  const opts = await page.locator('.ant-select-dropdown:visible .ant-select-item-option').allInnerTexts().catch(() => []);
  console.log(`[select:${label}] options =`, JSON.stringify(opts));
  await page.locator('.ant-select-dropdown:visible .ant-select-item-option', { hasText: optionText }).first().click({ timeout: 6000 });
  await page.waitForTimeout(600);
  const shown = await item.innerText().catch(() => '');
  console.log(`[select:${label}] item text now =`, shown.replace(/\s+/g, ' ').trim().slice(0, 80));
}

async function tryDownload(page, btnName, saveName) {
  const btn = page.getByRole('button', { name: btnName }).first();
  console.log(`[download:${saveName}] btn count =`, await btn.count());
  const dlPromise = page.waitForEvent('download', { timeout: 45000 }).then(d => d).catch(e => ({ __err: String(e.message) }));
  await btn.click({ timeout: 8000 }).catch(e => console.log('click err', e.message));
  const dl = await dlPromise;
  if (dl && dl.__err) { console.log(`[download:${saveName}] NO download event:`, dl.__err); 
    const toast = await page.locator('.ant-message, .ant-notification, [class*="message"], [class*="toast"]').allInnerTexts().catch(()=>[]);
    console.log(`[download:${saveName}] toasts =`, JSON.stringify(toast).slice(0,300)); return null; }
  const target = path.join(RECON, saveName);
  await dl.saveAs(target).catch(e => console.log('saveAs err', e.message));
  console.log(`[download:${saveName}] suggested =`, dl.suggestedFilename(), '→ size=', fs.existsSync(target) ? fs.statSync(target).size : 'N/A');
  return target;
}

async function main() {
  const lease = await acquirePostLease(`dl-probe-${Date.now()}`);
  if (!lease) { console.log('busy'); return; }
  let browser;
  try {
    const conn = await connectToPost(); browser = conn.browser; const page = conn.page;
    fs.mkdirSync(RECON, { recursive: true, mode: 0o700 });

    // ---- 运营效果 ----
    await page.goto(HOME, { waitUntil: 'domcontentloaded', timeout: 45000 }); await page.waitForTimeout(5000);
    await page.goto(EFFECT, { waitUntil: 'domcontentloaded', timeout: 45000 }); await page.waitForTimeout(7000);
    await selectByFormLabel(page, '问题类型', '新店未养活');
    const q = page.getByRole('button', { name: /查\s*询/ }).first();
    console.log('[query] count=', await q.count());
    await q.click({ timeout: 8000 }).catch(e => console.log('query err', e.message));
    await page.waitForTimeout(5000);
    await tryDownload(page, '数据下载', 'effect-download.xlsx');
    await page.waitForTimeout(2000);

    // ---- 门店分配 ----
    await page.goto(ALLOC, { waitUntil: 'domcontentloaded', timeout: 45000 }); await page.waitForTimeout(7000);
    await page.getByText('外卖店', { exact: true }).first().click({ timeout: 5000 }).catch(()=>{}); await page.waitForTimeout(1500);
    await page.getByText('已分配门店', { exact: true }).first().click({ timeout: 5000 }).catch(()=>{}); await page.waitForTimeout(1500);
    await tryDownload(page, '下载数据', 'alloc-download.xlsx');

    await page.goto(HOME, { waitUntil: 'domcontentloaded' }).catch(()=>{});
    console.log('\n[restore]', page.url());
  } finally { await browser?.close().catch(()=>{}); if (lease) await releasePostLease(lease).catch(()=>{}); }
}
main().catch(e => { console.error(String((e && e.stack) || e)); process.exitCode = 1; });
