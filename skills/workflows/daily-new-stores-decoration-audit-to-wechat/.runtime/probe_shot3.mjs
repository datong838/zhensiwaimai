#!/usr/bin/env node
// 临时只读探针 v3：点击「店内海报」卡使其选中（active），截图+dump 该卡形态
// （验证：已配置卡被选中后是保留「已配置」标签还是换成按钮——定判据的最后一块证据）
import fs from 'node:fs';
import { connectToPost } from '../../../posts/taobao-brand-post/scripts/connect.mjs';
import { acquirePostLease, releasePostLease } from '../../../posts/taobao-brand-post/scripts/lease.mjs';

const out = process.argv[2] || '.runtime/dump/panel3.png';
const dumpOut = process.argv[3] || '.runtime/dump/cards3.json';
const lease = await acquirePostLease(`decor-shot3-${Date.now()}`);
if (!lease) { console.log(JSON.stringify({ status: 'skipped', reason: 'post-lease-busy' })); process.exit(0); }
try {
  const conn = await connectToPost();
  const page = conn.browser.contexts().flatMap(c => c.pages()).find(p => p.url().startsWith('https://melody.shop.ele.me/'));
  const frame = page.frames().find(f => f.url().includes('melody-decorate-pc'));
  if (!frame || !frame.url().includes('template-config')) {
    console.log(JSON.stringify({ ok: false, reason: 'not-on-config-page' })); process.exit(2);
  }
  // 点「店内海报」卡（真实 click 事件）
  await frame.evaluate(() => {
    for (const t of document.querySelectorAll('[class*=moduleTitle]')) {
      if ((t.textContent || '').trim() === '店内海报') {
        const card = t.closest('[class*=moduleItem]') || t.parentElement;
        card.scrollIntoView({ block: 'center' });
        card.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
        return true;
      }
    }
    return false;
  });
  await page.waitForTimeout(2500);
  await frame.locator('body').screenshot({ path: out });
  const cards = await frame.evaluate(() => {
    const rows = [];
    for (const t of document.querySelectorAll('[class*=moduleTitle]')) {
      const card = t.closest('[class*=moduleItem]') || t.parentElement;
      if (!card) continue;
      const imgs = [...card.querySelectorAll('img')].map(i => ({ cls: String(i.className).slice(0, 40), src: i.src.slice(-50) }));
      const btns = [...card.querySelectorAll('button')].map(b => (b.textContent || '').replace(/\s+/g, ''));
      rows.push({ title: (t.textContent || '').trim(), active: /activeModule/i.test(String(card.className)), imgs, btns });
    }
    return rows;
  });
  fs.writeFileSync(dumpOut, JSON.stringify({ url: page.url(), cards }, null, 2));
  console.log(JSON.stringify({ ok: true, out, dumpOut }));
} finally {
  await releasePostLease(lease).catch(() => {});
}
process.exit(0);
