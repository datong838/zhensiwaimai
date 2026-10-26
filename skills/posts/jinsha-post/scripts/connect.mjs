// 金鲨岗（jinsha-post）通用采集模块 —— S1 收敛，不改语义
// 岗位 = 9232（金鲨 SaaS，data.guoshuyufen.com）
// 职责：连接专用浏览器 + 页面身份断言 + 登录态校验 + 遮罩处理
// 本文件只做「通用」，不掺任何流水线专属业务（日报下载/差评提取/新店识别）。

import {chromium} from 'playwright-core';

// 固定：金鲨专用浏览器 9232
export const JINSHA_PORT = 9232;
export const JINSHA_CDP = 'http://127.0.0.1:9232';
export const JINSHA_ORIGIN = 'https://data.guoshuyufen.com/';

// 登录态判定：title 白名单 + 风险词黑名单（与原三处实现逐字一致）
const TITLE_WHITELIST = ['金鲨数据', '臻肆外卖运营'];
const AUTH_RISK_RE = /(验证码|滑块|账号风险|安全验证|请重新登录)/;

/**
 * 连接金鲨专用浏览器（9232）。不启动、不重配、不建新标签。
 * 返回 playwright Browser 句柄；调用方负责 close。
 */
export async function connectJinsha(cdp = JINSHA_CDP) {
  return chromium.connectOverCDP(cdp);
}

/**
 * 页面身份断言：必须落在金鲨 origin，否则报 jinsha-origin-changed。
 */
export function assertJinshaOrigin(url) {
  if (!String(url).startsWith(JINSHA_ORIGIN)) throw Error('jinsha-origin-changed');
  return true;
}

/**
 * 登录态校验：title 命中白名单 且 正文不含风险词，否则 jinsha-authentication-required。
 * @param {import('playwright-core').Page} page
 * @param {string} body 已取到的 body.innerText（可选，省一次读取）
 */
export async function assertAuthenticated(page, body) {
  const text = body !== undefined ? String(body) : await page.locator('body').innerText();
  const title = String(await page.title());
  const url = page.url();
  if (url.includes('#/login')) throw Error('jinsha-authentication-required');
  if (!TITLE_WHITELIST.some((x) => title.includes(x))) throw Error('jinsha-authentication-required');
  if (AUTH_RISK_RE.test(text)) throw Error('jinsha-authentication-required');
  return true;
}

/**
 * 关闭侧栏抽屉（.drawer-bg 遮罩）。openSidebar 不存在或遮罩 0 个则直接返回；
 * 遮罩 >1 报 drawer-overlay-count（唯一性闸门）。与原 daily-negative-reviews 实现一致。
 */
export async function closeDrawer(page) {
  const app = page.locator('.app-wrapper');
  const classes = String((await app.getAttribute('class')) || '');
  if (!classes.split(/\s+/).includes('openSidebar')) return;
  const overlay = page.locator('.drawer-bg:visible');
  const count = await overlay.count();
  if (count === 0) return;
  if (count !== 1) throw Error(`drawer-overlay-count:${count}`);
  await overlay.evaluate((element) => element.click());
  await page.waitForFunction(
    () => !document.querySelector('.app-wrapper')?.classList.contains('openSidebar'),
    null,
    {timeout: 3000},
  );
}

/**
 * 公告弹窗处理：按白名单关闭；白名单外一律 unknown-page-overlay 熔断（fail-safe）。
 * 与原 daily-new-stores collector.dismissAnnouncement 语义一致，白名单下沉到调用方传入。
 * @param {import('playwright-core').Page} page
 * @param {string[]} knownMarkers 已知公告文案片段白名单
 * @param {number} waitMs 等待遮罩出现的上限
 */
export async function dismissAnnouncement(page, knownMarkers = [], waitMs = 2500) {
  const overlay = page.locator('.upload .content');
  const deadline = Date.now() + waitMs;
  let found = 0;
  while (Date.now() < deadline) {
    found = await overlay.count();
    if (found === 1 && (await overlay.first().isVisible().catch(() => false))) break;
    if (found > 1) throw Error(`announcement-overlay-count:${found}`);
    await page.waitForTimeout(150);
  }
  if (found === 0) return false;
  const text = await overlay.first().innerText();
  if (!knownMarkers.some((marker) => text.includes(marker))) throw Error('unknown-page-overlay');
  const closeBtn = overlay.first().locator('.close');
  const closeCount = await closeBtn.count();
  if (closeCount !== 1) throw Error(`announcement-close-not-unique:${closeCount}`);
  await closeBtn.first().click();
  return true;
}
