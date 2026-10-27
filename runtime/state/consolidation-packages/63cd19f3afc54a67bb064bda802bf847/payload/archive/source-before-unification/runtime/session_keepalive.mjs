// 浏览器岗位登录态保活探针（监理职责：环境可用性保障）。
// 设计铁律：
//  - 只读+轻刷新：拿不到岗位锁（业务在跑）→ busy 跳过，绝不驱动浏览器；
//  - 每岗位 reload 一次工作台页并判定登录态；掉线 → exit 2（调度层据此告警）；
//  - 岗位间随机抖动，避免固定模式。
// 用法: node runtime/session_keepalive.mjs
import { chromium } from '/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/skills/posts/taobao-brand-post/scripts/node_modules/playwright-core/index.mjs';

const ROOT = '/Users/ddt/work/projects/ai_agent/zhensi_waimai_back';
const POSTS = [
  {
    post: 'jinsha-business', port: 9232,
    lease: import(`${ROOT}/skills/posts/jinsha-post/scripts/lease.mjs`),
    acquire: 'acquireJinshaLease', release: 'releaseJinshaLease',
    leasePath: '/tmp/zhensi-jinsha-cua-exam.lock',
    workbench: (u) => u.hostname.includes('guoshuyufen.com'),
    offline: (u) => /\/login|\/signin|passport/i.test(u.href),
    name: '金鲨岗',
  },
  {
    post: 'taobao-brand', port: 9230,
    lease: import(`${ROOT}/skills/posts/taobao-brand-post/scripts/lease.mjs`),
    acquire: 'acquirePostLease', release: 'releasePostLease',
    leasePath: '/tmp/zhensi-post-9230.lock',
    workbench: (u) => /taobao\.com|alibaba\.com|ele\.me$/.test(u.hostname.replace(/.*\./, (m) => m)) || u.hostname.endsWith('ele.me') || u.hostname.includes('taobao.com'),
    offline: (u) => /login\.taobao|passport\.taobao|login\.ele\.me|\/member\/login/i.test(u.href),
    name: '淘宝品牌商岗',
  },
  {
    post: 'taobao-agent-service', port: 9231,
    lease: import(`${ROOT}/skills/posts/taobao-svc-post/scripts/lease.mjs`),
    acquire: 'acquirePostLease', release: 'releasePostLease',
    leasePath: '/tmp/zhensi-post-9231.lock',
    workbench: (u) => u.hostname.endsWith('ele.me') || u.hostname.includes('taobao.com') || u.hostname.includes('alibaba.com'),
    offline: (u) => /login\.taobao|passport\.taobao|login\.ele\.me|\/member\/login/i.test(u.href),
    name: '淘宝服务商岗',
  },
  {
    post: 'meituan-merchant', port: 9233,
    lease: import(`${ROOT}/skills/posts/meituan-post/scripts/lease.mjs`),
    acquire: 'acquirePostLease', release: 'releasePostLease',
    leasePath: '/tmp/zhensi-post-9233.lock',
    workbench: (u) => u.hostname === 'waimaie.meituan.com',
    offline: (u) => /passport\.meituan|\/longterm\/|\/account\/login/i.test(u.href),
    name: '美团岗',
  },
];

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function checkPost(cfg, runId) {
  const leaseMod = await cfg.lease;
  const lease = await leaseMod[cfg.acquire](runId, cfg.leasePath, 5 * 60 * 1000);
  if (!lease) return { post: cfg.post, name: cfg.name, status: 'busy', detail: '岗位锁被业务持有，本轮跳过' };
  try {
    const browser = await chromium.connectOverCDP(`http://127.0.0.1:${cfg.port}`);
    const context = browser.contexts()[0];
    if (!context) return { post: cfg.post, name: cfg.name, status: 'error', detail: 'context-missing' };
    const pages = context.pages().filter((p) => { try { return cfg.workbench(new URL(p.url())); } catch { return false; } });
    if (pages.length === 0) {
      return { post: cfg.post, name: cfg.name, status: 'no-workbench-page', detail: `浏览器在线但无工作台页（开放页数=${context.pages().length}）` };
    }
    const page = pages[0];
    const before = new URL(page.url()).href;
    await page.reload({ waitUntil: 'domcontentloaded', timeout: 20000 });
    await sleep(1500);
    const after = new URL(page.url());
    if (cfg.offline(after)) {
      return { post: cfg.post, name: cfg.name, status: 'OFFLINE', detail: `刷新后落到登录页：${after.href.slice(0, 90)}` };
    }
    if (!cfg.workbench(after)) {
      return { post: cfg.post, name: cfg.name, status: 'OFFLINE', detail: `刷新后离开工作台域：${after.href.slice(0, 90)}` };
    }
    return { post: cfg.post, name: cfg.name, status: 'ok', detail: `登录态正常（reload 前后同域）`, url: after.origin };
  } catch (e) {
    const msg = String(e?.message || e);
    if (/ECONNREFUSED|Target closed|Browser closed|NS_ERROR/i.test(msg)) {
      return { post: cfg.post, name: cfg.name, status: 'browser-down', detail: msg.slice(0, 90) };
    }
    return { post: cfg.post, name: cfg.name, status: 'error', detail: msg.slice(0, 120) };
  } finally {
    await leaseMod[cfg.release](lease).catch(() => {});
  }
}

const runId = `keepalive-${Date.now()}`;
const results = [];
for (const cfg of POSTS) {
  results.push(await checkPost(cfg, runId));
  await sleep(800 + Math.floor(Math.random() * 1700)); // 随机抖动
}
const bad = results.filter((r) => ['OFFLINE', 'browser-down'].includes(r.status));
console.log(JSON.stringify({ ok: bad.length === 0, checkedAt: new Date().toISOString(), results }, null, 1));
process.exit(bad.length ? 2 : 0);
