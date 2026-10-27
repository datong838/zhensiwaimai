#!/usr/bin/env node
// 临时只读探针：截图装修编辑页组件面板（大同 2026-10-12 质疑「已配置」识别不准的目视取证）。
import { connectToPost } from '../../../posts/taobao-brand-post/scripts/connect.mjs';
import { acquirePostLease, releasePostLease } from '../../../posts/taobao-brand-post/scripts/lease.mjs';

const out = process.argv[2] || '.runtime/dump/panel.png';
const lease = await acquirePostLease(`decor-shot-${Date.now()}`);
if (!lease) { console.log(JSON.stringify({ status: 'skipped', reason: 'post-lease-busy' })); process.exit(0); }
try {
  const conn = await connectToPost();
  const page = conn.browser.contexts().flatMap(c => c.pages()).find(p => p.url().startsWith('https://melody.shop.ele.me/'));
  let frame = page.frames().find(f => f.url().includes('melody-decorate-pc'));
  if (!frame || !frame.url().includes('template-config')) {
    // 不在编辑页：走菜单进入（复用 collector 的导航太重，这里只提示）
    console.log(JSON.stringify({ ok: false, reason: 'not-on-config-page', frameUrl: frame ? frame.url() : null }));
    process.exit(2);
  }
  await page.waitForTimeout(1500);
  const panel = frame.locator('[class*=moduleItem]').first();
  await panel.waitFor({ timeout: 8000 }).catch(() => {});
  await frame.locator('body').screenshot({ path: out }).catch(async () => {
    await page.screenshot({ path: out });
  });
  console.log(JSON.stringify({ ok: true, out, url: page.url() }));
} finally {
  await releasePostLease(lease).catch(() => {});
}
process.exit(0);
