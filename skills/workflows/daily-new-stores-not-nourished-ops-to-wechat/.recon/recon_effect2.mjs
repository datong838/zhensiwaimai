#!/usr/bin/env node
// 聚焦侦察：运营效果分析页为什么内容空白（等待更久 / 探测 SPA 子应用 / dump）。
import { createRequire } from 'node:module';
import { connectToPost } from '../../../posts/taobao-svc-post/scripts/connect.mjs';
import { acquirePostLease, releasePostLease } from '../../../posts/taobao-svc-post/scripts/lease.mjs';
const require = createRequire(import.meta.url);
const fs = require('node:fs');
const path = require('node:path');
const RECON = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..', '.recon');
const HOME = 'https://open.shop.ele.me/manager/base/home';
const EFFECT = 'https://open.shop.ele.me/manager/base/operations-effect';

async function snap(page, tag) {
  const info = await page.evaluate(() => {
    const txt = (document.body && document.body.innerText) || '';
    return {
      url: location.href, bodyLen: txt.length, tail: txt.slice(-400),
      selects: [...document.querySelectorAll('.ant-select, [class*="select"]')].map(e => (e.innerText||'').replace(/\s+/g,' ').trim()).filter(Boolean).slice(0,10),
      btns: [...document.querySelectorAll('button, [role="button"]')].map(e => (e.innerText||'').replace(/\s+/g,' ').trim()).filter(Boolean).slice(0,30),
      ths: [...document.querySelectorAll('th, [class*="thead"] [class*="cell"]')].map(e => (e.innerText||'').replace(/\s+/g,' ').trim()).filter(Boolean).slice(0,30),
      mainHtmlLen: (document.querySelector('#root, #app, main, [class*="content"], [class*="layout"]')?.innerHTML || '').length,
      iframes: [...document.querySelectorAll('iframe')].map(f => f.src).slice(0,8),
    };
  }).catch(e => ({ err: String(e.message) }));
  console.log(`\n== [${tag}] @ +${Date.now()%100000} ==`);
  console.log(JSON.stringify(info, null, 2));
  await page.screenshot({ path: path.join(RECON, `eff2-${tag}.png`) }).catch(()=>{});
}

async function main() {
  const lease = await acquirePostLease(`eff-recon-${Date.now()}`);
  if (!lease) { console.log('busy'); return; }
  let browser;
  try {
    const conn = await connectToPost(); browser = conn.browser; const page = conn.page;
    fs.mkdirSync(RECON, { recursive: true, mode: 0o700 });
    const reqs = [];
    page.on('response', r => { const u=r.url(); if(/operation|effect|metrics|store|download/i.test(u)) reqs.push(`${r.status()} ${u.slice(0,120)}`); });

    await page.goto(HOME, { waitUntil: 'domcontentloaded', timeout: 45000 });
    await page.waitForTimeout(6000);
    await snap(page, 'home');
    await page.goto(EFFECT, { waitUntil: 'domcontentloaded', timeout: 45000 });
    await page.waitForTimeout(6000); await snap(page, 'eff-6s');
    await page.waitForTimeout(8000); await snap(page, 'eff-14s');
    // 尝试 networkidle
    await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(()=>{});
    await snap(page, 'eff-idle');
    console.log('\n=== 相关网络请求 ===');
    console.log(reqs.slice(-25).join('\n'));
    await page.goto(HOME, { waitUntil: 'domcontentloaded' }).catch(()=>{});
    console.log('\n[restore]', page.url());
  } finally { await browser?.close().catch(()=>{}); if (lease) await releasePostLease(lease).catch(()=>{}); }
}
main().catch(e => { console.error(String(e.message||e)); process.exitCode = 1; });
