#!/usr/bin/env node
// 美团外卖商家版静默执行探测：通过既有 9233 专用通道 CDP 连接，后台标签加载，不抢焦点
import fs from 'node:fs';
import { createRequire } from 'node:module';
const require = createRequire('/Users/ddt/work/projects/ai_agent/aos-platform/plugins/browser/headless-playwright/');
const { chromium } = require('playwright-core');

const CDP = 'http://127.0.0.1:9233';
const URL_TARGET = 'https://waimaie.meituan.com/?ignoreSetRouterProxy=true#/new_fe/business#/index';
const OUT = '/tmp/meituan-silent-probe';
fs.mkdirSync(OUT, { recursive: true });

const receipt = { ok: false, steps: {} };
try {
  const browser = await chromium.connectOverCDP(CDP);
  const ctx = browser.contexts()[0];
  receipt.steps.contexts = browser.contexts().length;
  receipt.steps.existingPages = ctx.pages().map(p => p.url().slice(0, 90));

  const page = await ctx.newPage();
  const resp = await page.goto(URL_TARGET, { waitUntil: 'domcontentloaded', timeout: 30000 });
  receipt.steps.httpStatus = resp ? resp.status() : null;
  await page.waitForTimeout(6000); // 等 SPA 路由与接口
  receipt.steps.finalUrl = page.url();
  receipt.steps.title = await page.title();

  // 登录态判定：页面文本特征
  const bodyText = await page.evaluate(() => document.body.innerText.slice(0, 3000));
  receipt.steps.loginIndicators = {
    hasQRLogin: /扫码|二维码|手机号登录|请登录/.test(bodyText),
    hasMerchantHome: /经营|门店|订单|营业/.test(bodyText),
    snippet: bodyText.replace(/\s+/g, ' ').slice(0, 300),
  };

  // 不抢焦点：直接截图（后台标签也能截）
  await page.screenshot({ path: `${OUT}/waimaie-probe.png`, fullPage: false });
  receipt.steps.screenshot = `${OUT}/waimaie-probe.png`;

  // 窗口/焦点影响检查：新标签是否被激活
  receipt.steps.isActiveTab = await page.evaluate(() => document.visibilityState);

  await page.close(); // 探测完关闭任务标签
  receipt.ok = true;
} catch (e) {
  receipt.error = String(e).slice(0, 500);
}
fs.writeFileSync(`${OUT}/probe-receipt.json`, JSON.stringify(receipt, null, 2));
console.log(JSON.stringify(receipt, null, 2));
