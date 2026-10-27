// 9233 美团 IM 每日环境复位（权威版 · 2026-10-14 修正）
// 修正记录：① URL 必须带完整 hash 路由 #/im/page/workbench/reception（缺 /reception 后缀 SPA 路由 404，2026-10-14 实测）
//          ② 顺序改为「先建新页→验证渲染→后关旧页」（旧版先关后建有 0 页面窗口；新页渲染失败时绝不禁旧页）
// 规程来源：大同 2026-10-03 立——每天发完当日工作台账后，把美团 IM 页面关掉重新打开，保障次日智能客服流环境可用
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
const nativeRequire = createRequire(import.meta.url);
const pw = nativeRequire('../skills/posts/meituan-post/scripts/node_modules/playwright-core/index.js');

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
// 权威 URL：与 runtime/auth_keepalive.mjs TARGETS[9233] 保持一致（唯一权威源）
const TARGET = 'https://waimaie.meituan.com/imworkbench/home?appId=4&clientType=140006#/im/page/workbench/reception';
const MARKERS = ['顾客消息', '客服管理', '正在接待', '待人工回复', '未回复'];
function isMeituanIM(value) {
  try { const u = new URL(value); return u.hostname === 'waimaie.meituan.com' && u.pathname.startsWith('/imworkbench/'); }
  catch { return false; }
}
async function inspectReception(page) {
  const text = await page.evaluate(() => document.body.innerText || '').catch(() => '');
  const norm = text.replace(/\s+/g, '');
  const hit = MARKERS.find(m => norm.includes(m));
  const blocked = await page.evaluate(() => {
    const visible = e => !!e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden' && getComputedStyle(e).display !== 'none';
    return [...document.querySelectorAll('.riskControlModal, .geetest_panel, [role="dialog"]')]
      .some(e => visible(e) && (e.matches('.riskControlModal, .geetest_panel') || /验证码|安全验证|登录失效|重新登录/.test(e.innerText || '')));
  }).catch(() => true);
  const url = page.url();
  let reception = false;
  try { reception = new URL(url).hash === '#/im/page/workbench/reception'; } catch {}
  return {ok: Boolean(hit && !blocked && reception && isMeituanIM(url)
      && !/noPermission|\/login/i.test(url)
      && !/noPermission|登录已失效|登录失效|请重新登录/i.test(norm)),
    url, textLength: text.length, hit: hit || null, blocked};
}
if (typeof process !== 'undefined' && process.argv.includes('--selftest')) {
  const assert = nativeRequire('node:assert/strict');
  assert.equal(isMeituanIM(TARGET), true);
  for (const u of ['https://example.com/imworkbench/home', 'https://waimaie.meituan.com.example.com/imworkbench/home', 'https://waimaie.meituan.com/login', 'invalid']) assert.equal(isMeituanIM(u), false);
  console.log(JSON.stringify({ok:true,tests:5,browserConnections:0}));
  process.exit(0);
}

export async function resetIM({ chromium = pw.chromium, wait = sleep } = {}) {
const b = await chromium.connectOverCDP('http://127.0.0.1:9233');
const ctx = b.contexts()[0];

const before = ctx.pages().map((p) => p.url()).filter(isMeituanIM);
console.log('BEFORE_PAGES=' + JSON.stringify(before));

// ① 先建新页（同 URL）
const page = await ctx.newPage();
console.log('NEWPAGE_OK');
let gotoOk = false;
try {
  await page.goto(TARGET, { waitUntil: 'domcontentloaded', timeout: 60000 });
  gotoOk = true;
  console.log('GOTO_OK');
} catch (e) {
  console.log('GOTO_FAIL=' + e.message);
}

// ② 等渲染并验证业务特征（SPA 需要 bootstrap 时间）
await wait(10000);
const initialHealth = await inspectReception(page);
console.log('URL_NOW=' + page.url());
console.log('TEXT_LEN=' + initialHealth.textLength);
console.log('HIT=' + (initialHealth.hit || '（无）'));

if (!gotoOk || !initialHealth.ok) {
  // ③ 失败保护：新页没起来就保留旧页，绝不留 0 页面
  console.log('RESULT=RESET_FAIL（新页未渲染业务特征，旧页保留不动，需人工排查）');
  try { await b.close(); } catch {}
  return {ok:false, reason:'new-im-not-healthy', oldPagesPreserved:true, closed:0, initialHealth};
}
console.log('RESET_NEWPAGE_OK');

// ④ 新页验证通过后才关旧页（除新页外的所有 imworkbench 页）
let closed = 0;
for (const p of ctx.pages()) {
  if (p === page) continue;
  const u = p.url() || '';
  if (isMeituanIM(u)) {
    try {
      await p.close();
      closed++;
      console.log('CLOSED=' + u);
    } catch (e) {
      console.log('CLOSE_FAIL=' + u + ' :: ' + e.message);
    }
  }
}
console.log('CLOSED_COUNT=' + closed);

// ⑤ 去重核验：应恰好 1 个 imworkbench 页且在渲染
await wait(2000);
const imPages = ctx.pages().filter((p) => isMeituanIM(p.url()));
const finalHealth = await inspectReception(page);
const ok = imPages.length === 1 && imPages[0] === page && finalHealth.ok;
console.log('AFTER_IMPAGES=' + imPages.length + ' ' + JSON.stringify(imPages.map((p) => p.url())));
console.log('RESULT=' + (ok ? 'RESET_OK' : 'RESET_WARN（最终IM页数或正文健康检查未通过）'));

try { await b.close(); } catch {}
return {ok, closed, remainingIMPages:imPages.length, initialHealth, finalHealth};
}

if (typeof process !== 'undefined' && fileURLToPath(import.meta.url) === path.resolve(process.argv[1] || '')) {
 resetIM().then(result => { process.exitCode = result.ok ? 0 : 1; }).catch(error => { console.error(error); process.exitCode = 1; });
}
