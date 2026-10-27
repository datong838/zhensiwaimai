import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import { execFile as execFileCb } from 'node:child_process';
import { promisify } from 'node:util';
import { chromium } from 'playwright-core';

const execFile = promisify(execFileCb);
const root = path.dirname(new URL(import.meta.url).pathname);
const date = '2026-09-16';
const raw = path.join(root, 'raw', `差评分析数据_${date}_${date}.xlsx`);
const staging = path.join(root, 'raw', '.download-staging');
const platforms = [['美团外卖', '1'], ['淘宝闪购', '2'], ['京东外卖', '4']];
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const sha256 = async (file) => crypto.createHash('sha256').update(await fs.readFile(file)).digest('hex');

async function closeDrawer(page) {
  const app = page.locator('.app-wrapper');
  const classes = String(await app.getAttribute('class') || '');
  if (!classes.split(/\s+/).includes('openSidebar')) return;
  const overlay = page.locator('.drawer-bg:visible');
  if (await overlay.count() !== 1) throw new Error(`drawer-overlay-count:${await overlay.count()}`);
  await overlay.evaluate((element) => element.click());
  const end = Date.now() + 3000;
  while (Date.now() < end) {
    if (String(await app.getAttribute('class') || '').split(/\s+/).includes('hideSidebar')) return;
    await sleep(100);
  }
  throw new Error('sidebar-close-readback-failed');
}

async function waitReady(page) {
  const end = Date.now() + 20000;
  let stable = 0;
  let last = '';
  while (Date.now() < end) {
    if (page.url().includes('#/login')) throw new Error('jinsha-login-required');
    const totalText = await page.locator('.el-pagination__total').first().innerText().catch(() => '');
    const match = totalText.match(/共\s*(\d+)\s*条/);
    const count = await page.locator('.cryptonymText').count();
    const current = `${match?.[1] || ''}:${count}`;
    stable = current === last ? stable + 1 : 1;
    last = current;
    if (match && Number(match[1]) === count && stable >= 2) return count;
    await sleep(300);
  }
  throw new Error('negative-list-not-stable');
}

async function ensurePageSize(page) {
  const input = page.locator('input[placeholder="请选择"]:visible');
  if (await input.count() !== 1) throw new Error(`page-size-input-count:${await input.count()}`);
  if (await input.inputValue() === '200条/页') return;
  await input.click();
  await sleep(300);
  const candidates = page.getByText('200条/页', { exact: true });
  const visible = [];
  for (let index = 0; index < await candidates.count(); index += 1) {
    const item = candidates.nth(index);
    if (await item.isVisible().catch(() => false)) visible.push(item);
  }
  if (visible.length !== 1) throw new Error(`page-size-option-count:${visible.length}`);
  await visible[0].click();
  const end = Date.now() + 5000;
  while (Date.now() < end) {
    if (await input.inputValue() === '200条/页') return;
    await sleep(150);
  }
  throw new Error('page-size-readback-failed');
}

async function choose(page, value) {
  const radio = page.locator(`input[type="radio"][value="${value}"]`);
  if (await radio.count() !== 1) throw new Error(`platform-radio-count:${value}:${await radio.count()}`);
  await radio.evaluate((element) => element.click());
  await sleep(800);
  await ensurePageSize(page);
  if (!await radio.isChecked()) throw new Error(`platform-readback-failed:${value}`);
  return waitReady(page);
}

async function downloadAll(page) {
  await fs.mkdir(path.dirname(raw), { recursive: true });
  try {
    await fs.access(raw);
    throw new Error('raw-destination-exists');
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
  }
  await fs.rm(staging, { recursive: true, force: true });
  await fs.mkdir(staging, { recursive: true });
  const button = page.locator('button.download_btn:visible');
  if (await button.count() !== 1) throw new Error(`download-button-count:${await button.count()}`);
  const cdp = await page.context().newCDPSession(page);
  let captured = false;
  let captureMode = 'playwright-save-as';
  try {
    await cdp.send('Page.setDownloadBehavior', { behavior: 'allow', downloadPath: staging });
    const [download] = await Promise.all([
      page.waitForEvent('download', { timeout: 60000 }),
      button.click({ timeout: 5000 }),
    ]);
    if (!/\.xlsx$/i.test(download.suggestedFilename())) throw new Error('download-filename-invalid');
    try {
      await download.saveAs(raw);
    } catch {
      captureMode = 'task-page-staging-recovery';
      const end = Date.now() + 60000;
      let stable = 0;
      let lastName = '';
      let lastSize = -1;
      let found = '';
      while (Date.now() < end) {
        const names = (await fs.readdir(staging)).filter((name) => !name.endsWith('.crdownload'));
        if (names.length > 1) throw new Error(`download-staging-ambiguous:${names.length}`);
        if (names.length === 1) {
          const file = path.join(staging, names[0]);
          const info = await fs.stat(file);
          if (info.size > 0 && names[0] === lastName && info.size === lastSize) stable += 1;
          else stable = 1;
          lastName = names[0];
          lastSize = info.size;
          if (stable >= 2) { found = file; break; }
        } else {
          stable = 0;
          lastName = '';
          lastSize = -1;
        }
        await sleep(300);
      }
      if (!found) throw new Error('download-staging-timeout');
      await fs.rename(found, raw);
    }
    const failure = await download.failure();
    if (failure) throw new Error(`download-failed:${failure}`);
    captured = true;
    const info = await fs.stat(raw);
    if (info.size <= 0) throw new Error('download-empty');
    await execFile('/usr/bin/unzip', ['-t', raw]);
    return { file: raw, size: info.size, sha256: await sha256(raw), suggestedFilename: download.suggestedFilename(), clicks: 1, captureMode };
  } finally {
    await cdp.detach().catch(() => {});
    if (captured) await fs.rm(staging, { recursive: true, force: true });
  }
}

async function extract(page, platform) {
  const cards = page.locator('.cryptonym');
  const rows = [];
  for (let index = 0; index < await cards.count(); index += 1) {
    const card = cards.nth(index);
    const store = (await card.locator('.shopName').first().innerText()).trim();
    const dimensions = (await card.locator('.pointLi').allInnerTexts()).map((value) => value.trim()).filter(Boolean);
    const score = dimensions.find((value) => /^总分\s*\d/.test(value)) || '';
    const text = (await card.innerText()).trim();
    const rowDate = (text.match(/20\d{2}-\d{2}-\d{2}/) || [])[0] || '';
    const comment = (await card.locator('.cryptonymText').first().innerText().catch(() => '')).trim();
    const status = (await card.locator('.txt').allInnerTexts()).map((value) => value.trim()).filter(Boolean).join('；');
    rows.push({ store, score, date: rowDate, comment, dimensions, status, platform });
  }
  return rows;
}

const started = Date.now();
const browser = await chromium.connectOverCDP('http://127.0.0.1:9232');
try {
  const pages = browser.contexts().flatMap((context) => context.pages());
  const matches = pages.filter((page) => page.url().includes('data.guoshuyufen.com'));
  if (matches.length !== 1) throw new Error(`jinsha-page-count:${matches.length}`);
  const page = matches[0];
  const initialBody = await page.locator('body').innerText().catch(() => '');
  const title = String(await page.title());
  const authenticatedTitle = title.includes('臻肆外卖运营') || title.includes('金鲨数据');
  const authenticatedStructure = ['总览', '数据上传', '店铺列表'].filter((marker) => initialBody.includes(marker)).length >= 2;
  if (page.url().includes('#/login') || !authenticatedTitle || !authenticatedStructure || /(验证码|滑块|账号风险|安全验证)/.test(initialBody)) throw new Error('jinsha-authentication-required');
  await page.goto('https://data.guoshuyufen.com/#/negativeAnalyse', { waitUntil: 'domcontentloaded', timeout: 30000 });
  await sleep(4000);
  await closeDrawer(page);
  const bodyText = await page.locator('body').innerText();
  if (/(验证码|滑块|账号风险|安全验证)/.test(bodyText)) throw new Error('jinsha-risk-gate');
  const dates = page.locator('input.el-range-input');
  if (await dates.count() !== 2) throw new Error(`date-input-count:${await dates.count()}`);
  for (let index = 0; index < 2; index += 1) {
    if (await dates.nth(index).inputValue() !== date) throw new Error(`date-readback-mismatch:${index}`);
  }
  await choose(page, '0');
  const download = await downloadAll(page);
  const rows = [];
  const counts = {};
  for (const [name, value] of platforms) {
    counts[name] = await choose(page, value);
    rows.push(...await extract(page, name));
  }
  if (rows.length !== Object.values(counts).reduce((sum, value) => sum + value, 0)) throw new Error('ui-count-sum-mismatch');
  const businessWarnings = /授权失败/.test(bodyText) ? ['授权失败'] : [];
  await fs.writeFile(path.join(root, 'ui-status.json'), JSON.stringify({ readAt: new Date().toISOString(), date, url: page.url(), counts, businessWarnings, rows }, null, 2), { mode: 0o600 });
  await page.goto('https://data.guoshuyufen.com/#/businessData/realTimeData', { waitUntil: 'domcontentloaded', timeout: 30000 });
  console.log(JSON.stringify({ ok: true, date, counts, total: rows.length, businessWarnings, download, elapsedMs: Date.now() - started }));
} finally {
  await browser.close();
}
