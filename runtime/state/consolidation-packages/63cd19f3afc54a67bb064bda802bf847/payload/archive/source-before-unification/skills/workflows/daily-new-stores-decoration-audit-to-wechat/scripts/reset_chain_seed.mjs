#!/usr/bin/env node
// 2026-10-11 共享岗页面复位：活动巡检（activity_collector）会把 9230 页面留在
// /app/shop/<id>/activity__myActivity（shop 域），而金鲨下载流
// （daily-taobao-download-to-jinsha）要求页面 URL 落在 chain 前缀下才可 recoverable
// （isTaobaoSeedRecoveryUrl ⇒ 否则 taobao-auth-seed-recovery-not-unique:0）。
// 「谁弄脏谁恢复」：巡检结束后把页面导航回 chain 数据中心 seed 态。
// 只做导航，不做任何业务点击；不抛错（复位失败仅输出 JSON，不拖垮巡检流结果）。
import { createRequire } from 'node:module';
import { connectToPost } from '../../../posts/taobao-brand-post/scripts/connect.mjs';
import { acquirePostLease, releasePostLease } from '../../../posts/taobao-brand-post/scripts/lease.mjs';
const require = createRequire(import.meta.url);
const fs = require('node:fs');

const CHAIN_PREFIX = 'https://melody.shop.ele.me/app/chain/95708808';
const CHAIN_HOME = 'https://melody.shop.ele.me/app/chain/95708808/stats__center#app.chainshop.stats.center';

async function main() {
  const lease = await acquirePostLease(`chain-seed-reset-${Date.now()}`);
  if (!lease) {
    console.log(JSON.stringify({ status: 'skipped', reason: 'post-lease-busy' }));
    return;
  }
  let browser;
  try {
    const conn = await connectToPost();
    browser = conn.browser;
    const pages = browser.contexts().flatMap((c) => c.pages()).filter((p) => p.url().startsWith('https://melody.shop.ele.me/'));
    if (pages.length !== 1) {
      console.log(JSON.stringify({ status: 'skipped', reason: `melody-tab-not-unique:${pages.length}` }));
      return;
    }
    const page = pages[0];
    if (page.url().startsWith(CHAIN_PREFIX)) {
      console.log(JSON.stringify({ status: 'already-seed', url: page.url() }));
      return;
    }
    await page.goto(CHAIN_HOME, { waitUntil: 'domcontentloaded', timeout: 30000 });
    console.log(JSON.stringify({ status: 'reset', url: page.url() }));
  } finally {
    await browser?.close().catch(() => {});
    if (lease) await releasePostLease(lease).catch(() => {});
  }
}
main().catch((e) => {
  console.error(JSON.stringify({ status: 'failed', reason: String(e.message || e).slice(0, 300) }));
  process.exitCode = 1;
});
