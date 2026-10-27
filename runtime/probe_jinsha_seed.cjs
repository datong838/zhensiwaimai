#!/usr/bin/env node
// 只读诊断 + 最小页面维护：检查 9230 金鲨 seed 判据；未达标时尝试点击「数据中心」触发 iframe 路由。
// 零外发副作用；仅操作共享岗 9230 页面状态。
const { chromium } = require('/Users/ddt/work/projects/ai_agent/aos-platform/plugins/browser/headless-playwright/node_modules/playwright-core');

const PORT = process.argv[2] || '9230';
const CLICK = process.argv.includes('--click');

function isTaobaoSeedRecoveryUrl(u) {
  try { const x = new URL(u); return x.origin === 'https://melody.shop.ele.me' && x.href.startsWith('https://melody.shop.ele.me/app/chain/95708808') && x.pathname !== '/login'; } catch { return false; }
}

async function allFrameText(page) {
  const parts = [];
  for (const f of page.frames()) {
    try { parts.push(await f.evaluate(() => document.body ? document.body.innerText : '')); } catch {}
  }
  return parts.join('\n');
}

async function seedState(page) {
  const url = page.url();
  if (!isTaobaoSeedRecoveryUrl(url)) return { ok: false, why: `url-not-recoverable:${url.slice(0, 90)}` };
  const frames = page.frames().map(f => f.url());
  const stats = frames.find(u => u.includes('melody-stats-next.ele.me'));
  const hasAnalysis = frames.some(u => u.includes('melody-stats-next.ele.me/new/#/chain/business-analysis'));
  const text = await allFrameText(page);
  const marks = { 品牌版: text.includes('品牌版'), 数据中心: text.includes('数据中心'), 今日实时数据: text.includes('今日实时数据') };
  return { ok: hasAnalysis && marks.品牌版 && marks.数据中心 && marks.今日实时数据, url, statsFrame: stats || 'NONE', hasAnalysis, marks, frameCount: frames.length };
}

(async () => {
  const browser = await chromium.connectOverCDP(`http://127.0.0.1:${PORT}`);
  const ctx = browser.contexts()[0];
  const pages = ctx.pages();
  console.log('pageCount:', pages.length);
  for (const p of pages) console.log('  page:', p.url().slice(0, 110));

  let page = pages.find(p => isTaobaoSeedRecoveryUrl(p.url()));
  if (!page) { console.log('NO_RECOVERABLE_PAGE'); await browser.close(); process.exit(0); }

  let st = await seedState(page);
  console.log('seed before:', JSON.stringify(st));

  if (!st.ok && CLICK) {
    // 尝试点击主文档「数据中心」入口
    try {
      const loc = page.locator('text=数据中心').first();
      await loc.click({ timeout: 8000 });
      console.log('clicked 数据中心, waiting 12s...');
      await page.waitForTimeout(12000);
    } catch (e) { console.log('click failed:', String(e.message).slice(0, 160)); }
    st = await seedState(page);
    console.log('seed after click:', JSON.stringify(st));
  }

  await browser.close();
  process.exit(st.ok ? 0 : 2);
})().catch(e => { console.error('ERR', e.message); process.exit(1); });
