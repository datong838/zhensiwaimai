// 一次性修复：9230 brand 岗复位（2026-10-20 23:06 大同指令「换页面刷新一下」）
// 背景：页面被指标流切到单店视图 shop/521561152/stats__center（len=600 空壳），保活连续 4 轮
//      unknown（21:19/20:18/22:20/本时段）。auth_keepalive TARGETS[9230] 权威 URL =
//      chain/95708808/stats__center。复位动作 = 复用已开页导航回权威 URL + 消弹窗 + 等渲染验证。
// 铁律：#68 复用已开页禁新开标签；#47 探针不留残留 DOM；结束必释租约。
import { connectToPost } from '../skills/posts/taobao-brand-post/scripts/connect.mjs';
import { acquirePostLease, releasePostLease } from '../skills/posts/taobao-brand-post/scripts/lease.mjs';

// 与 auth_keepalive.mjs TARGETS[9230] 一致（唯一权威源）
const TARGET = 'https://melody.shop.ele.me/app/chain/95708808/stats__center#app.chainshop.stats.center';
// 与 auth_keepalive.mjs TARGETS[9230].shell 一致（业务特征）
const SHELL = ['商家首页', '订单管理', '商品管理', '顾客管理', '门店管理', '数据中心', '搜索菜单'];
const LOGIN = ['账号登录', '请先选择您的账号类型', '扫码登录', '登录注册', '立即登录'];

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// 消解提示类弹窗（同 probe_activity_shop.mjs，仅中性按钮/关闭X，不做表单提交）
async function dismissModal(page) {
  for (let i = 0; i <3; i++) {
    const visible = await page.evaluate(() => {
      const w = document.querySelector('.ant-modal-wrap, .cook-modal-wrap');
      if (!w) return false;
      const s = getComputedStyle(w);
      return s.display !== 'none' && s.visibility !== 'hidden';
    });
    if (!visible) return;
    const btn = page.locator('.ant-modal-root .ant-modal-footer button, .cook-modal-wrap button')
      .filter({ hasText: /跳|知道了|我知道|确/ }).first();
    if (await btn.count()) await btn.click({ timeout: 4000 }).catch(() => {});
    else await page.locator('.ant-modal-close, .cook-modal-close').first().click({ timeout: 4000 }).catch(() => {});
    await page.waitForTimeout(800);
  }
}

const lease = await acquirePostLease(`reset-9230-${Date.now()}`);
if (!lease) { console.log('LEASE_BUSY: 有采集流占用 9230，退出不动'); process.exit(4); }
let browser;
try {
  const conn = await connectToPost();
  browser = conn.browser;
  const pages = browser.contexts().flatMap(c => c.pages()).filter(p => p.url().startsWith('https://melody.shop.ele.me/'));
  console.log('brand pages=', pages.length);
  if (!pages.length) { console.log('NO_PAGE: 无 melody 页可复用'); process.exit(3); }
  const page = pages[0];
  console.log('BEFORE url=', page.url());

  // ① 复用已开页导航回权威 URL（#40: hung⇒reload；这里整页导航更强的重置）
  await page.goto(TARGET, { waitUntil: 'domcontentloaded', timeout: 60000 });
  console.log('GOTO_OK');

  // ② 等渲染：SPA bootstrap + shell 特征轮询（最多 45s）
  let verdict = { state: 'unknown', hit: null };
  for (let i = 0; i < 45; i++) {
    await sleep(1000);
    await dismissModal(page).catch(() => {});
    const txt = await page.evaluate(() => document.body ? document.body.innerText : '').catch(() => '');
    const loginHit = LOGIN.find(m => txt.includes(m));
    if (loginHit) { verdict = { state: 'out', hit: loginHit }; break; }
    const shellHit = SHELL.find(m => txt.includes(m));
    if (shellHit) { verdict = { state: 'in', hit: shellHit }; break; }
  }

  const url = page.url();
  const txtLen = await page.evaluate(() => document.body ? document.body.innerText.length : 0).catch(() => 0);
  console.log('AFTER url=', url);
  console.log('VERDICT state=', verdict.state, 'hit=', verdict.hit, 'len=', txtLen);

  if (verdict.state === 'in') {
    console.log('RESULT=RESET_OK 登录态正常，页面已复位到权威目标，保活判据恢复');
    process.exit(0);
  } else if (verdict.state === 'out') {
    console.log('RESULT=LOGGED_OUT 掉登录，需人工有头重登');
    process.exit(3);
  } else {
    console.log('RESULT=STILL_UNKNOWN 渲染特征仍未命中，需人工看屏');
    process.exit(2);
  }
} catch (e) {
  console.log('RESET-ERROR:', e.message);
  console.log(String(e.stack || '').split('\n').slice(0, 6).join(' ⏎ '));
  process.exit(1);
} finally {
  await browser?.close().catch(() => {});
  if (lease) await releasePostLease(lease).catch(() => {});
}
