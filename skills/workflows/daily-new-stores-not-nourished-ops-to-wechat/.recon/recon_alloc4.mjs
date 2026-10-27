#!/usr/bin/env node
// 选根角色(930家)再下载，验证能否拿到全部已分配门店 + 正确运营人。
import { createRequire } from 'node:module';
import { connectToPost } from '../../../posts/taobao-svc-post/scripts/connect.mjs';
import { acquirePostLease, releasePostLease } from '../../../posts/taobao-svc-post/scripts/lease.mjs';
const require = createRequire(import.meta.url);
const fs = require('node:fs');
const path = require('node:path');
const RECON = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..', '.recon');
const HOME = 'https://open.shop.ele.me/manager/base/home';
const ALLOC = 'https://open.shop.ele.me/manager/base/store-allocation';

async function tableCount(page) {
  const t = await page.evaluate(() => (document.body.innerText||''));
  const m = t.match(/共\s*(\d+)\s*条/);
  return m ? m[1] : 'n/a';
}

async function main() {
  const lease = await acquirePostLease(`alloc-root-${Date.now()}`);
  if (!lease) { console.log('busy'); return; }
  let browser;
  try {
    const conn = await connectToPost(); browser = conn.browser; const page = conn.page;
    fs.mkdirSync(RECON, { recursive: true, mode: 0o700 });
    await page.goto(HOME, { waitUntil: 'domcontentloaded', timeout: 45000 }); await page.waitForTimeout(5000);
    await page.goto(ALLOC, { waitUntil: 'domcontentloaded', timeout: 45000 }); await page.waitForTimeout(7000);
    console.log('默认(选中角色) 共N条 =', await tableCount(page));

    // 点根节点
    const root = page.getByText('上海臻肆文化传播有限公司(930家)', { exact: false }).first();
    console.log('root count =', await root.count());
    await root.click({ timeout: 6000 }).catch(e => console.log('root click err', e.message));
    await page.waitForTimeout(5000);
    console.log('选根后 共N条 =', await tableCount(page));
    await page.screenshot({ path: path.join(RECON, 'alloc4-root.png') });

    // 下载
    const btn = page.getByRole('button', { name: '下载数据' }).first();
    const dlP = page.waitForEvent('download', { timeout: 60000 }).catch(e => ({ __err: String(e.message) }));
    await btn.click({ timeout: 8000 }).catch(e=>console.log('dl click err', e.message));
    const dl = await dlP;
    if (dl && dl.__err) console.log('NO download:', dl.__err);
    else {
      const target = path.join(RECON, 'alloc-root.xlsx');
      await dl.saveAs(target);
      console.log('下载:', dl.suggestedFilename(), '→ size=', fs.statSync(target).size);
    }
    await page.goto(HOME, { waitUntil: 'domcontentloaded' }).catch(()=>{});
    console.log('[restore]', page.url());
  } finally { await browser?.close().catch(()=>{}); if (lease) await releasePostLease(lease).catch(()=>{}); }
}
main().catch(e => { console.error(String((e&&e.stack)||e)); process.exitCode = 1; });
