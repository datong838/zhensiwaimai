#!/usr/bin/env node
/**
 * 抖音评论单条回复（需 --confirm-reply）
 * 遵循 sc-server/vedio/douyin：作品 → 评论 → 确认 → 发送 → 回读
 */
import { chromium } from 'playwright';

const CDP = process.env.DOUYIN_CDP || 'http://127.0.0.1:9222';
const MANAGE_URL = 'https://creator.douyin.com/creator-micro/content/manage';

function parseArgs(argv) {
  const out = { confirm: false };
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--confirm-reply') out.confirm = true;
    else if (a === '--work-title') out.workTitle = argv[++i];
    else if (a === '--comment-snippet') out.commentSnippet = argv[++i];
    else if (a === '--text') out.text = argv[++i];
    else if (a === '--cdp') out.cdp = argv[++i];
  }
  return out;
}

export async function replyComment({ workTitle, commentSnippet, text, confirm, cdp = CDP }) {
  if (!workTitle || !commentSnippet || !text) {
    throw new Error('需要 --work-title --comment-snippet --text');
  }
  const browser = await chromium.connectOverCDP(cdp);
  const context = browser.contexts()[0];
  const page = context.pages().find(p => p.url().includes('douyin.com')) || await context.newPage();
  await page.goto(MANAGE_URL, { waitUntil: 'domcontentloaded', timeout: 60000 });

  await page.getByText(workTitle.slice(0, 10), { exact: false }).first().click({ timeout: 15000 });
  await page.waitForTimeout(1500);
  await page.getByText(commentSnippet.slice(0, 12), { exact: false }).first().click({ timeout: 10000 }).catch(() => {});

  const result = { workTitle, commentSnippet, text, state: 'prepared' };
  if (!confirm) {
    result.state = 'reply_pending';
    return result;
  }

  const box = page.locator('textarea, div[contenteditable="true"]').last();
  await box.fill(text);
  await page.getByRole('button', { name: /发送|回复/ }).first().click({ timeout: 8000 });
  await page.waitForTimeout(2000);
  const seen = await page.getByText(text.slice(0, 8), { exact: false }).count();
  result.verified = seen > 0;
  result.state = seen > 0 ? 'verified' : 'reply_unknown';
  return result;
}

async function main() {
  const args = parseArgs(process.argv);
  try {
    const result = await replyComment({
      workTitle: args.workTitle,
      commentSnippet: args.commentSnippet,
      text: args.text,
      confirm: args.confirm,
      cdp: args.cdp || CDP,
    });
    console.log(JSON.stringify({ ok: result.verified || result.state === 'reply_pending', ...result }, null, 2));
  } catch (err) {
    console.error(JSON.stringify({ ok: false, error: String(err.message || err) }));
    process.exit(1);
  }
}

main();
