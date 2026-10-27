#!/usr/bin/env node
// 临时只读探针（不进 dependencies.json 封印）：dump 装修编辑页组件面板 DOM，
// 用于核对「已配置」徽标的真实形态与组件标题文本（正负对照取证）。
import fs from 'node:fs';
import { connectToPost } from '../../../posts/taobao-brand-post/scripts/connect.mjs';
import { acquirePostLease, releasePostLease } from '../../../posts/taobao-brand-post/scripts/lease.mjs';

const out = process.argv[2];
const lease = await acquirePostLease(`decor-probe-${Date.now()}`);
if (!lease) { console.log(JSON.stringify({ status: 'skipped', reason: 'post-lease-busy' })); process.exit(0); }
try {
  const conn = await connectToPost();
  const page = conn.browser.contexts().flatMap(c => c.pages()).find(p => p.url().startsWith('https://melody.shop.ele.me/'));
  const dump = {};
  dump.url = page.url();
  const frame = page.frames().find(f => f.url().includes('melody-decorate-pc'));
  dump.frameUrl = frame ? frame.url() : null;
  dump.frames = page.frames().map(f => f.url().slice(0, 120));
  if (frame) {
    dump.titles = await frame.evaluate(() =>
      [...document.querySelectorAll('[class*=moduleTitle]')].map(t => (t.textContent || '').replace(/\s+/g, ''))).catch(e => `ERR:${e.message}`);
    dump.itemCount = await frame.evaluate(() => document.querySelectorAll('[class*=moduleItem]').length).catch(() => -1);
    dump.hasBadgeTextAnywhere = await frame.evaluate(() => (document.body.innerText || '').includes('已配置')).catch(() => null);
    dump.badgeNodes = await frame.evaluate(() => [...document.querySelectorAll('*')]
      .filter(n => n.children.length === 0 && (n.textContent || '').replace(/\s+/g, '') === '已配置')
      .slice(0, 10).map(n => ({ cls: String(n.className).slice(0, 60), parentCls: String(n.parentElement?.className || '').slice(0, 60) }))).catch(() => []);
    dump.panelText = await frame.evaluate(() => (document.body.innerText || '').replace(/\n+/g, ' | ').slice(0, 1200)).catch(() => null);
  }
  fs.writeFileSync(out, JSON.stringify(dump, null, 2));
  console.log(JSON.stringify({ ok: true, out }));
} finally {
  await releasePostLease(lease).catch(() => {});
}
process.exit(0);
