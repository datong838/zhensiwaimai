#!/usr/bin/env node
// 深挖 门店分配 页：角色树 / 已分配·待分配 tab / 运营人列。
import { createRequire } from 'node:module';
import { connectToPost } from '../../../posts/taobao-svc-post/scripts/connect.mjs';
import { acquirePostLease, releasePostLease } from '../../../posts/taobao-svc-post/scripts/lease.mjs';
const require = createRequire(import.meta.url);
const fs = require('node:fs');
const path = require('node:path');
const RECON = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..', '.recon');
const HOME = 'https://open.shop.ele.me/manager/base/home';
const ALLOC = 'https://open.shop.ele.me/manager/base/store-allocation';

async function txt(page) {
  return (await page.evaluate(() => {
    const t = (document.body && document.body.innerText) || '';
    return t;
  })).replace(/\n{2,}/g, '\n');
}

async function main() {
  const lease = await acquirePostLease(`alloc-recon-${Date.now()}`);
  if (!lease) { console.log('busy'); return; }
  let browser;
  try {
    const conn = await connectToPost(); browser = conn.browser; const page = conn.page;
    fs.mkdirSync(RECON, { recursive: true, mode: 0o700 });
    await page.goto(HOME, { waitUntil: 'domcontentloaded', timeout: 45000 }); await page.waitForTimeout(5000);
    await page.goto(ALLOC, { waitUntil: 'domcontentloaded', timeout: 45000 }); await page.waitForTimeout(7000);
    await page.screenshot({ path: path.join(RECON, 'alloc3-initial.png') });

    // 尝试点击所有可展开的 caret（角色树）
    const carets = page.locator('[class*="caret"], [class*="expand"], [class*="arrow"], [class*="tree"] [role="img"]');
    console.log('caret-like count =', await carets.count());
    for (let i = 0; i < Math.min(await carets.count(), 6); i++) {
      await carets.nth(i).click({ timeout: 2500 }).catch(() => {});
      await page.waitForTimeout(600);
    }
    await page.waitForTimeout(1500);
    await page.screenshot({ path: path.join(RECON, 'alloc3-expanded.png') });

    // dump 角色列表面板（左侧）
    const panelText = await page.evaluate(() => {
      const cands = [...document.querySelectorAll('[class*="role"], [class*="member"], [class*="tree"], aside, [class*="sider"], [class*="left"]')];
      return cands.map(e => (e.innerText || '').replace(/\s+/g, ' ').trim()).filter(Boolean).slice(0, 8);
    });
    console.log('\n=== 角色/树 面板候选 ===');
    panelText.forEach((t, i) => console.log(`[${i}]`, t.slice(0, 400)));

    console.log('\n=== 当前页全文（截取）===');
    console.log((await txt(page)).slice(0, 1500));

    // 切到 待分配门店
    await page.getByText('待分配门店', { exact: true }).first().click({ timeout: 5000 }).catch(e=>console.log('tab err', e.message));
    await page.waitForTimeout(4000);
    await page.screenshot({ path: path.join(RECON, 'alloc3-unassigned.png') });
    console.log('\n=== 待分配门店 全文（截取）===');
    console.log((await txt(page)).slice(0, 1000));

    await page.goto(HOME, { waitUntil: 'domcontentloaded' }).catch(()=>{});
    console.log('\n[restore]', page.url());
  } finally { await browser?.close().catch(()=>{}); if (lease) await releasePostLease(lease).catch(()=>{}); }
}
main().catch(e => { console.error(String((e&&e.stack)||e)); process.exitCode = 1; });
