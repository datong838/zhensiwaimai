#!/usr/bin/env node
/**
 * 抖音创作者中心：上传视频 + 填描述/位置 + 发布（需 --confirm-publish）
 * 依赖：Chrome CDP 9222、playwright（npx playwright 或项目内安装）
 */
import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';

const CDP = process.env.DOUYIN_CDP || 'http://127.0.0.1:9222';
const UPLOAD_URL = 'https://creator.douyin.com/creator-micro/content/upload';
const MANAGE_URL = 'https://creator.douyin.com/creator-micro/content/manage';

function parseArgs(argv) {
  const out = { confirm: false };
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--confirm-publish') out.confirm = true;
    else if (a === '--video') out.video = argv[++i];
    else if (a === '--caption') out.caption = argv[++i];
    else if (a === '--location') out.location = argv[++i];
    else if (a === '--cdp') out.cdp = argv[++i];
  }
  return out;
}

async function probeCdp(url) {
  const res = await fetch(`${url.replace(/\/$/, '')}/json/version`);
  if (!res.ok) throw new Error(`CDP 不可用: ${url}`);
  return res.json();
}

async function fillLocation(page, locationText) {
  const loc = page.getByText('位置', { exact: false }).first();
  if (await loc.count()) await loc.click({ timeout: 5000 }).catch(() => {});
  const input = page.locator('input[placeholder*="位置"], input[placeholder*="地点"], textarea').filter({ hasText: '' }).first();
  if (await input.count()) {
    await input.fill(locationText);
    await page.keyboard.press('Enter');
    await page.waitForTimeout(800);
    const option = page.getByText(locationText.slice(0, 8), { exact: false }).first();
    if (await option.count()) await option.click({ timeout: 3000 }).catch(() => {});
  }
}

export async function publishOne({ video, caption, location, confirm, cdp = CDP }) {
  if (!video || !fs.existsSync(video)) throw new Error(`视频不存在: ${video}`);
  if (!caption) throw new Error('缺少 caption');
  if (!location) throw new Error('缺少 location');
  await probeCdp(cdp);

  const browser = await chromium.connectOverCDP(cdp);
  const context = browser.contexts()[0] || (await browser.newContext());
  const page = context.pages().find(p => p.url().includes('douyin.com')) || await context.newPage();
  await page.goto(UPLOAD_URL, { waitUntil: 'domcontentloaded', timeout: 60000 });

  const fileInput = page.locator('input[type="file"]').first();
  await fileInput.setInputFiles(path.resolve(video));
  await page.waitForTimeout(3000);

  const desc = page.locator('textarea, div[contenteditable="true"]').filter({ hasNotText: '添加音乐' }).first();
  await desc.click({ timeout: 15000 });
  await desc.fill(caption);

  await fillLocation(page, location);

  const result = { video: path.basename(video), caption, location, state: 'prepared' };
  if (!confirm) {
    result.state = 'publish_pending';
    result.note = '未传 --confirm-publish，停在发布前';
    return result;
  }

  const pub = page.getByRole('button', { name: /发布/ }).first();
  await pub.click({ timeout: 10000 });
  await page.waitForTimeout(5000);
  result.state = 'submitted';

  await page.goto(MANAGE_URL, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(2000);
  const seen = await page.getByText(caption.slice(0, 12), { exact: false }).count();
  result.verified = seen > 0;
  result.state = seen > 0 ? 'verified' : 'publish_unknown';
  return result;
}

async function main() {
  const args = parseArgs(process.argv);
  try {
    const result = await publishOne({
      video: args.video,
      caption: args.caption,
      location: args.location,
      confirm: args.confirm,
      cdp: args.cdp || CDP,
    });
    console.log(JSON.stringify({ ok: result.state === 'verified' || result.state === 'publish_pending', ...result }, null, 2));
    process.exit(result.state === 'failed' ? 1 : 0);
  } catch (err) {
    console.error(JSON.stringify({ ok: false, error: String(err.message || err) }));
    process.exit(1);
  }
}

main();
