#!/usr/bin/env node
// 临时只读探针 v2：关引导弹窗 → 截组件面板 + dump 全部卡片标签结构
// （取证目标：「已配置」徽标的真实载体：img/伪元素/文本？）
import fs from 'node:fs';
import { connectToPost } from '../../../posts/taobao-brand-post/scripts/connect.mjs';
import { acquirePostLease, releasePostLease } from '../../../posts/taobao-brand-post/scripts/lease.mjs';

const out = process.argv[2] || '.runtime/dump/panel2.png';
const dumpOut = process.argv[3] || '.runtime/dump/cards2.json';
const lease = await acquirePostLease(`decor-shot2-${Date.now()}`);
if (!lease) { console.log(JSON.stringify({ status: 'skipped', reason: 'post-lease-busy' })); process.exit(0); }
try {
  const conn = await connectToPost();
  const page = conn.browser.contexts().flatMap(c => c.pages()).find(p => p.url().startsWith('https://melody.shop.ele.me/'));
  const frame = page.frames().find(f => f.url().includes('melody-decorate-pc'));
  if (!frame || !frame.url().includes('template-config')) {
    console.log(JSON.stringify({ ok: false, reason: 'not-on-config-page' })); process.exit(2);
  }
  // 关引导弹窗（1/2 下一步 → 完成/关闭，最多 3 轮），再兜底 class*=close
  for (let i = 0; i < 3; i++) {
    const closed = await frame.evaluate(() => {
      const sels = ['.index_close__V-lf9', '[class*=close]', '[class*=Close]'];
      for (const sel of sels) {
        const els = [...document.querySelectorAll(sel)].filter(e => {
          const r = e.getBoundingClientRect();
          return r.width > 0 && r.width < 60 && r.height > 0 && r.height < 60;
        });
        if (els.length) { els[0].click(); return 'closed:' + sel; }
      }
      return null;
    }).catch(() => null);
    if (closed) { await page.waitForTimeout(1200); break; }
    // 无关闭钮：点「下一步」推进引导
    await frame.evaluate(() => {
      const btn = [...document.querySelectorAll('button')].find(b => /下一步|完成|知道了/.test(b.textContent || ''));
      if (btn) btn.click();
    }).catch(() => {});
    await page.waitForTimeout(1200);
  }
  await page.waitForTimeout(1500);
  await frame.locator('body').screenshot({ path: out });
  const cards = await frame.evaluate(() => {
    const rows = [];
    for (const t of document.querySelectorAll('[class*=moduleTitle]')) {
      const card = t.closest('[class*=moduleItem]') || t.parentElement;
      if (!card) continue;
      const imgs = [...card.querySelectorAll('img')].map(i => ({ cls: String(i.className).slice(0, 50), src: i.src.slice(-60), w: i.getBoundingClientRect().width, h: i.getBoundingClientRect().height }));
      const btns = [...card.querySelectorAll('button')].map(b => (b.textContent || '').replace(/\s+/g, ''));
      const spans = [...card.querySelectorAll('span,div')].filter(e => {
        const r = e.getBoundingClientRect();
        return r.width > 20 && r.width < 70 && r.height >= 14 && r.height <= 26 && e.children.length === 0;
      }).map(e => ({ text: (e.textContent || '').slice(0, 20), cls: String(e.className).slice(0, 50), w: Math.round(e.getBoundingClientRect().width), h: Math.round(e.getBoundingClientRect().height) }));
      rows.push({ title: (t.textContent || '').trim(), imgs, btns, smallNodes: spans });
    }
    return rows;
  });
  fs.writeFileSync(dumpOut, JSON.stringify({ url: page.url(), cards }, null, 2));
  console.log(JSON.stringify({ ok: true, out, dumpOut, n: cards.length }));
} finally {
  await releasePostLease(lease).catch(() => {});
}
process.exit(0);
