// 一次性修复：9230 brand 岗标签页恢复（2026-10-21 13:5x）
// 背景：浏览器壳活着（HeadlessChrome pid 12284）但 /json/list 0 标签页 ⇒ 保活 ⚠️「无目标域标签页」。
//      已用 CDP PUT /json/new 建了一个 about:blank 页（新版 Chrome 忽略 url 参数）。
// 动作：复用该空白页导航回权威 URL + 消弹窗 + shell 特征验证（同 reset_9230_20261020.mjs）。
// 铁律：#68 复用已开页禁再新开标签；#47 探针不留残留 DOM；结束必释租约。
import { connectToPost } from '../skills/posts/taobao-brand-post/scripts/connect.mjs';
import { acquirePostLease, releasePostLease } from '../skills/posts/taobao-brand-post/scripts/lease.mjs';

// 与 auth_keepalive.mjs TARGETS[9230] 一致（唯一权威源）
const TARGET = 'https://melody.shop.ele.me/app/chain/95708808/stats__center#app.chainshop.stats.center';
const SHELL = ['商家首页', '订单管理', '商品管理', '顾客管理', '门店管理', '数据中心', '搜索菜单'];
const LOGIN = ['账号登录', '请先选择您的账号类型', '扫码登录', '登录注册', '立即登录'];

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function dismissModal(page) {
  for (let i = 0; i < 3; i++) {
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

const lease = await acquirePostLease(`restore-9230-${Date.now()}`);
if (!lease) { console.log('LEASE_BUSY: 有采集流占用 9230，退出不动'); process.exit(4); }
let browser;
try {
  const conn = await connectToPost();
  browser = conn.browser;
  const all = browser.contexts().flatMap(c => c.pages());
  console.log('pages total=', all.length, all.map(p => p.url().slice(0, 60)).join(' ;; '));
  const melody = all.filter(p => p.url().startsWith('https://melody.shop.ele.me/'));
  const blank = all.filter(p => p.url() === 'about:blank' || p.url() === '');
  const page = melody[0] || blank[0];
  if (!page) { console.log('NO_PAGE: 无可复用页面'); process.exit(3); }
  console.log('USING url=', page.url());
  console.log('BEFORE url=', page.url());

  await page.goto(TARGET, { waitUntil: 'domcontentloaded', timeout: 60000 });
  console.log('GOTO_OK');

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
    console.log('RESULT=RESTORE_OK 登录态正常，标签页已恢复到权威目标，保活判据恢复');
    process.exit(0);
  } else if (verdict.state === 'out') {
    console.log('RESULT=LOGGED_OUT 掉登录，需人工有头重登');
    process.exit(3);
  } else {
    console.log('RESULT=STILL_UNKNOWN 渲染特征仍未命中，需人工看屏');
    process.exit(2);
  }
} catch (e) {
  console.log('RESTORE-ERROR:', e.message);
  console.log(String(e.stack || '').split('\n').slice(0, 6).join(' ⏎ '));
  process.exit(1);
} finally {
  await browser?.close().catch(() => {});
  if (lease) await releasePostLease(lease).catch(() => {});
}
