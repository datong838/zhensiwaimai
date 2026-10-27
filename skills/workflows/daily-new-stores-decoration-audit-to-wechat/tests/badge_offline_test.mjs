#!/usr/bin/env node
// 离线正负对照（不碰 9230 岗位）：用独立 Chrome 实例 + 模拟 DOM 验证徽标判据 readComponentBadges。
// ★ 2026-10-12 大同纠错后判据 v2：「已配置」徽标是 44×20 橙色 svg 图片（class 含 moduleIcon），
//   DOM 无文本；「去配置」按钮未配置卡/已配置选中卡都会出现，不作判据；
//   「新组件」（class 含 newTag）= 未配置。模拟 DOM class 名按真机形态复刻。
import { createRequire } from 'node:module';
import { readComponentBadges } from '../scripts/decoration_collector.mjs';
const require = createRequire(import.meta.url);
const { chromium } = require('../../../../vendor/node_modules/playwright');

const COMPS = [
  { key: '顶部招牌', aliases: ['顶部招牌', '门店招牌'] },
  { key: '店内海报', aliases: ['店内海报'] },
  { key: '门店头像', aliases: ['门店头像'] },
  { key: '店内橱窗', aliases: ['店内橱窗'] },
];

const ICON = `<img class="index_moduleIcon__KSPQP" src="https://img.alicdn.com/...tps-44-20.svg">`;
const NEWTAG = `<img class="index_newTag__VWRM3" src="https://img.alicdn.com/...tps-246-96.png">`;

const CASES = [
  {
    name: 'P1 已配置（moduleIcon 图标）⇒ configured',
    html: `<div class="index_moduleItem__a"><div class="index_moduleTitle__b">顶部招牌</div>${ICON}</div>
           <div class="index_moduleItem__a"><div class="index_moduleTitle__b">店内海报</div>${ICON}</div>`,
    expect: { 顶部招牌: 'configured', 店内海报: 'configured', 门店头像: 'missing', 店内橱窗: 'missing' },
  },
  {
    name: 'P2 别名「门店招牌」+ moduleIcon ⇒ configured',
    html: `<div class="index_moduleItem__a"><div class="index_moduleTitle__b">门店招牌</div>${ICON}</div>`,
    expect: { 顶部招牌: 'configured', 店内海报: 'missing', 门店头像: 'missing', 店内橱窗: 'missing' },
  },
  {
    name: 'P3 已配置卡被选中（active）：图标与「去配置」按钮并存 ⇒ 仍 configured（真机 2026-10-12 实测形态）',
    html: `<div class="index_moduleItem__a index_activeModule__z"><div class="index_moduleTitle__b">店内海报</div>${ICON}<button class="cook-deco-themes-btn"><span>去配置</span></button></div>`,
    expect: { 顶部招牌: 'missing', 店内海报: 'configured', 门店头像: 'missing', 店内橱窗: 'missing' },
  },
  {
    name: 'N1 未配置：只有「去配置」按钮、无图标 ⇒ missing（顶部招牌真机形态）',
    html: `<div class="index_moduleItem__a index_activeModule__z"><div class="index_moduleTitle__b">顶部招牌</div><button class="cook-deco-themes-btn"><span>去配置</span></button></div>`,
    expect: { 顶部招牌: 'missing', 店内海报: 'missing', 门店头像: 'missing', 店内橱窗: 'missing' },
  },
  {
    name: 'N2 「新组件」标签（newTag 图）⇒ missing（图片墙真机形态）',
    html: `<div class="index_moduleItem__a"><div class="index_moduleTitle__b">店内橱窗</div>${NEWTAG}</div>`,
    expect: { 顶部招牌: 'missing', 店内海报: 'missing', 门店头像: 'missing', 店内橱窗: 'missing' },
  },
  {
    name: 'N3 模版无此组件（无图标无按钮）⇒ missing（fail-closed）',
    html: `<div class="index_moduleItem__a"><div class="index_moduleTitle__b">品牌故事</div></div>`,
    expect: { 顶部招牌: 'missing', 店内海报: 'missing', 门店头像: 'missing', 店内橱窗: 'missing' },
  },
  {
    name: 'N4 图标在别的卡不误判（跨卡隔离）',
    html: `<div class="index_moduleItem__a"><div class="index_moduleTitle__b">顶部招牌</div><button><span>去配置</span></button></div>
           <div class="index_moduleItem__a"><div class="index_moduleTitle__b">门店头像</div>${ICON}</div>`,
    expect: { 顶部招牌: 'missing', 店内海报: 'missing', 门店头像: 'configured', 店内橱窗: 'missing' },
  },
  {
    name: 'N5 卡内其它无关 img（非 moduleIcon class）不触发 configured',
    html: `<div class="index_moduleItem__a"><div class="index_moduleTitle__b">店内海报</div><img class="index_moduleSubIcon__x" src="https://x/44-20.svg"><button><span>去配置</span></button></div>`,
    expect: { 顶部招牌: 'missing', 店内海报: 'missing', 门店头像: 'missing', 店内橱窗: 'missing' },
  },
];

const browser = await chromium.launch({
  executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  headless: true,
});
let pass = 0;
const rows = [];
try {
  const page = await browser.newPage();
  await page.route('**/*', route => route.abort());
  for (const c of CASES) {
    await page.setContent(`<div id="panel">${c.html}</div>`);
    const got = await page.evaluate(readComponentBadges, { comps: COMPS });
    const ok = JSON.stringify(got) === JSON.stringify(c.expect);
    if (ok) pass++;
    rows.push({ case: c.name, expected: c.expect, actual: got, result: ok ? 'PASS' : 'FAIL' });
  }
} finally {
  await browser.close();
}
console.log(JSON.stringify({ total: CASES.length, pass, fail: CASES.length - pass, rows }, null, 2));
process.exit(pass === CASES.length ? 0 : 1);
