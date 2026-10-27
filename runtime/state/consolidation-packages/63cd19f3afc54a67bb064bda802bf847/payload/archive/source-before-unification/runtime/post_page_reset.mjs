// E2 · 岗位页受护栏复位（9230/9232/9233）
//
// 背景：D2 要求「页面元素找不到 ⇒ 自动关重开」。这是**对生产页的写操作**，
// 必须多重护栏，绝不盲目复位。本脚本把护栏做进代码，而不是靠调用者自觉。
//
// 四层护栏（自上而下，任一不过即不动手）：
//   G1 仅当该端口**页面断言失败**（期望页缺失/标题不符）才考虑复位（健康的绝不碰）。
//   G2 仅当**没有在跑的步骤**（runtime/state/live_steps 无存活进程组）才动手——
//      避免把正在采集的流打断。无法确认时必须放弃（fail-closed）。
//   G3 频控：每端口每窗口最多 N 次（默认 60min 内 2 次），超额不再动手只报告。
//   G4 默认 **dry-run**：只有显式 `--apply` 才真正关页重开。
//
// 边界：不点任何业务元素、不发消息、不改业务数据、不写台账；只关「本端口目标站点的
//       页面」+ 重开目标 URL + 只读校验 + 截图。**永不触碰 9231**（它由 bg-chrome-up.sh 管）。
// 用法：
//   node runtime/post_page_reset.mjs                 # dry-run 全量体检
//   node runtime/post_page_reset.mjs --apply         # 真正复位（仍受 G1-G3 约束）
//   node runtime/post_page_reset.mjs --port 9233 --apply
//   node runtime/post_page_reset.mjs --selftest      # hermetic 自测（不连 CDP）
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { execFileSync } from 'node:child_process';

const ROOT = '/Users/ddt/work/projects/ai_agent/zhensi_waimai_back';
const STATE = path.join(ROOT, 'runtime', 'state');
const LIVE_STEPS_DIR = path.join(STATE, 'live_steps');
const HISTORY = path.join(STATE, 'post_page_reset_history.json');
const AUDIT = path.join(STATE, 'post_page_reset.jsonl');
const OUT_DIR = path.join(ROOT, 'outputs');

const PW = path.join(ROOT, 'skills/posts/meituan-post/scripts/node_modules/playwright-core/index.js');

// 端口 → 目标（closeMatch = 关页时只关含该片段的页面，避免误关同站其它页）
const TARGETS = {
  9230: {
    role: '淘宝品牌商',
    title: '淘宝闪购商家版',
    url: 'https://melody.shop.ele.me/app/chain/95708808/stats__center#app.chainshop.stats.center',
    urlMatch: 'shop.ele.me',
    closeMatch: 'shop.ele.me',
  },
  9232: {
    role: '金鲨',
    title: '臻肆外卖运营',
    url: 'https://data.guoshuyufen.com/#/negativeAnalyse',
    urlMatch: 'guoshuyufen.com',
    closeMatch: 'guoshuyufen.com',
  },
  9233: {
    role: '美团',
    title: '美团商家IM客服工作台',
    url: 'https://waimaie.meituan.com/imworkbench/home?appId=4&clientType=140006#/im/page/workbench/reception',
    // 同站还有「美团外卖商家版」页（/new_fe/business），故用路径片段精确锁定 IM 工作台
    urlMatch: 'imworkbench',
    closeMatch: '/imworkbench/',
  },
};
const EXCLUDED = { 9231: '淘宝服务商 · 由 bg-chrome-up.sh 管理，本脚本只报告不复位' };
const RATE_MAX = 2;
const RATE_WINDOW_MS = 60 * 60 * 1000;
const DAILY_MAX = 6;               // 每端口每日复位次数上限（防「反复复位」抖动）
const DAY_MS = 24 * 60 * 60 * 1000;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** 测试专用注入（hermetic 端到端验证）：仅在 PPR_TEST_PORT 指定且**不在生产端口表**时生效。
 *  生产端口 9230/9231/9232/9233 永远不可被注入覆盖 —— 防止误配把复位打到真岗位上。 */
function testTargetFromEnv() {
  const raw = process.env.PPR_TEST_PORT;
  if (!raw) return null;
  const port = Number(raw);
  if (!Number.isInteger(port) || TARGETS[port] || EXCLUDED[port]) return null;
  return {
    port,
    role: 'TESTPAGE',
    title: process.env.PPR_TEST_TITLE || 'PPR-TEST-OK',
    url: process.env.PPR_TEST_URL || 'about:blank',
    urlMatch: process.env.PPR_TEST_MATCH || 'about:blank',
    closeMatch: process.env.PPR_TEST_CLOSE || 'about:blank',
  };
}

// ---------------------------------------------------------------- 纯逻辑（可自测）

/** G1：/json/list 里是否已有期望页。 */
export function pagePresent(pages, target) {
  if (!Array.isArray(pages)) return false;
  return pages.some(
    (p) =>
      p && p.type === 'page' &&
      String(p.title || '').includes(target.title) &&
      String(p.url || '').includes(target.urlMatch)
  );
}

/** G2：读取存活的步骤登记（pgid 存活才算）。返回 [{pgid, argv}]。 */
export function aliveLiveSteps(dir = LIVE_STEPS_DIR) {
  const alive = [];
  let files = [];
  try {
    files = fs.readdirSync(dir).filter((f) => f.endsWith('.json'));
  } catch {
    return alive;
  }
  for (const f of files) {
    let d = {};
    try {
      d = JSON.parse(fs.readFileSync(path.join(dir, f), 'utf8'));
    } catch {
      continue;
    }
    const pgid = d.pgid;
    if (!Number.isInteger(pgid)) continue;
    try {
      process.kill(-pgid, 0); // 探测进程组
      alive.push({ pgid, argv: d.argv || [] });
    } catch {
      /* 不存在 ⇒ 未存活 */
    }
  }
  return alive;
}

/** G3：频控判定（纯函数）。history = { "<port>": [epochMs,...] }。
 *  两个上限：窗口内（默认 1h）≤ RATE_MAX 次，且 24h 内 ≤ DAILY_MAX 次。 */
export function rateAllowed(history, port, nowMs, max = RATE_MAX, windowMs = RATE_WINDOW_MS,
                            dailyMax = DAILY_MAX) {
  const arr = (history && Array.isArray(history[String(port)])) ? history[String(port)] : [];
  const recent = arr.filter((t) => Number.isFinite(t) && nowMs - t < windowMs);
  const daily = arr.filter((t) => Number.isFinite(t) && nowMs - t < DAY_MS);
  return {
    allowed: recent.length < max && daily.length < dailyMax,
    recentCount: recent.length,
    dailyCount: daily.length,
  };
}

/** 决策表：把护栏合成一个可读的判定（纯函数，便于自测）。 */
export function decide({ healthy, aliveSteps, rate, apply }) {
  if (healthy) return { action: 'skip-healthy', why: '页面健康，无需复位' };
  if (aliveSteps > 0) return { action: 'blocked-live-step', why: `有 ${aliveSteps} 个步骤在跑，禁止复位` };
  if (!rate.allowed) return { action: 'blocked-rate-limit', why: `频控：1h 内 ${rate.recentCount}/${RATE_MAX}、24h 内 ${rate.dailyCount}/${DAILY_MAX}` };
  return apply
    ? { action: 'reset', why: '断言失败 + 无在跑 + 频控通过 + --apply' }
    : { action: 'would-reset', why: '满足复位条件（dry-run，未动手）' };
}

// ---------------------------------------------------------------- IO 辅助

function readJson(p, dflt) {
  try { return JSON.parse(fs.readFileSync(p, 'utf8')); } catch { return dflt; }
}
function writeJson(p, obj) {
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, JSON.stringify(obj, null, 2), 'utf8');
}
function audit(line) {
  try {
    fs.mkdirSync(path.dirname(AUDIT), { recursive: true });
    fs.appendFileSync(AUDIT, JSON.stringify(line) + '\n', 'utf8');
  } catch { /* 审计失败不影响主流程 */ }
}
async function cdpList(port, timeoutMs = 6000) {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), timeoutMs);
  try {
    const r = await fetch(`http://127.0.0.1:${port}/json/list`, { signal: ctl.signal });
    return await r.json();
  } finally {
    clearTimeout(t);
  }
}

// ---------------------------------------------------------------- 复位动作

async function doReset(port, target) {
  const { default: pw } = await import(PW);
  const b = await pw.chromium.connectOverCDP(`http://127.0.0.1:${port}`);
  const ctx = b.contexts()[0];
  let closed = 0;
  for (const p of ctx.pages()) {
    if (String(p.url()).includes(target.closeMatch)) {
      try { await p.close(); closed += 1; } catch { /* ignore */ }
    }
  }
  const page = await ctx.newPage();
  let gotoWarn = '';
  try {
    await page.goto(target.url, { waitUntil: 'domcontentloaded', timeout: 60000 });
  } catch (e) { gotoWarn = e.message; }
  await sleep(8000);
  let title = '';
  try { title = await page.title(); } catch { /* ignore */ }
  const ok = title.includes(target.title);
  let shot = '';
  try {
    const outDir = process.env.PPR_TEST_PORT ? os.tmpdir() : OUT_DIR;
    shot = path.join(outDir, `post_page_reset_${port}_${new Date().toISOString().slice(0, 10).replace(/-/g, '')}.png`);
    await page.screenshot({ path: shot, fullPage: false });
  } catch { shot = ''; }
  await b.close();
  return { closed, title, ok, gotoWarn, shot };
}

// ---------------------------------------------------------------- 主流程

async function main(argv) {
  const args = argv.slice(2);
  const apply = args.includes('--apply');
  const selftest = args.includes('--selftest');
  if (selftest) return runSelftest();
  const portArg = args.indexOf('--port');
  const only = portArg >= 0 ? Number(args[portArg + 1]) : null;
  const injected = testTargetFromEnv();
  const table = injected ? { ...TARGETS, [injected.port]: injected } : TARGETS;
  const ports = Object.keys(table).map(Number).filter((p) => !only || p === only);

  const hist = readJson(injected ? path.join(os.tmpdir(), 'ppr_test_history.json') : HISTORY, {});
  const alive = aliveLiveSteps();
  const now = Date.now();
  const results = [];

  for (const port of ports) {
    const target = table[port];
    let pages = null;
    try { pages = await cdpList(port); } catch { pages = null; }
    const healthy = pagePresent(pages, target);
    const rate = rateAllowed(hist, port, now);
    const d = decide({ healthy, aliveSteps: alive.length, rate, apply });
    let detail = {};
    if (d.action === 'reset') {
      try {
        detail = await doReset(port, target);
      } catch (e) {
        detail = { ok: false, error: String(e.message || e) };
      }
      if (detail.ok) {
        const arr = Array.isArray(hist[String(port)]) ? hist[String(port)] : [];
        arr.push(now);
        hist[String(port)] = arr.filter((t) => now - t < DAY_MS);
        writeJson(injected ? path.join(os.tmpdir(), 'ppr_test_history.json') : HISTORY, hist);
      }
    }
    const row = { port, role: target.role, action: d.action, why: d.why, ...detail };
    results.push(row);
    console.log(JSON.stringify(row, null, 2));
    if (!injected) audit({ at: new Date().toISOString(), ...row });
  }

  const bad = results.filter((r) => ['reset-failed'].includes(r.action) || (r.action === 'reset' && r.ok === false));
  const headline = results.map((r) => `${r.port}:${r.action}`).join(' ');
  console.log(`post-page-reset(${apply ? 'APPLY' : 'DRY'}): ${headline}`);
  if (EXCLUDED[9231]) console.log(`  [note] 9231 不归本脚本：${EXCLUDED[9231]}`);
  return bad.length ? 1 : 0;
}

// ---------------------------------------------------------------- hermetic 自测

function runSelftest() {
  let ok = true;
  const chk = (name, cond) => {
    console.log(`  [${cond ? 'OK' : 'FAIL'}] ${name}`);
    ok = ok && cond;
  };
  const T = TARGETS[9233];
  chk('G1 命中期望页', pagePresent([{ type: 'page', title: '美团商家IM客服工作台', url: 'https://waimaie.meituan.com/imworkbench/x' }], T) === true);
  chk('G1 标题对但URL不对 ⇒ 不算健康', pagePresent([{ type: 'page', title: '美团商家IM客服工作台', url: 'https://waimaie.meituan.com/?x' }], T) === false);
  chk('G1 登录页 ⇒ 不算健康', pagePresent([{ type: 'page', title: '登录', url: 'https://waimaie.meituan.com/login' }], T) === false);
  chk('G1 非数组 ⇒ 不健康', pagePresent(null, T) === false);

  const r1 = rateAllowed({ 9233: [1e12] }, 9233, 1e12 + 1000);
  chk('G3 窗口内 1 次仍允许', r1.allowed === true && r1.recentCount === 1);
  const r2 = rateAllowed({ 9233: [1e12, 1e12 + 1] }, 9233, 1e12 + 2000);
  chk('G3 窗口内 2 次已达上限', r2.allowed === false && r2.recentCount === 2);
  const r3 = rateAllowed({ 9233: [1e12] }, 9233, 1e12 + 2 * 3600 * 1000);
  chk('G3 窗口外不算', r3.allowed === true && r3.recentCount === 0);
  // 日上限：22h 内已 6 次（窗口外但当日超额）⇒ 阻断
  const many = Array.from({ length: 6 }, (_, i) => 1e12 + i * 3 * 3600 * 1000);
  const r4 = rateAllowed({ 9233: many }, 9233, 1e12 + 22 * 3600 * 1000);
  chk('G3 日上限 6 次 ⇒ 阻断（即使 1h 窗口为空）',
    r4.allowed === false && r4.recentCount === 0 && r4.dailyCount === 6);

  chk('决策-健康⇒跳过', decide({ healthy: true, aliveSteps: 2, rate: { allowed: true, recentCount: 0 }, apply: true }).action === 'skip-healthy');
  chk('决策-有流在跑⇒阻断(fail-closed)', decide({ healthy: false, aliveSteps: 1, rate: { allowed: true, recentCount: 0 }, apply: true }).action === 'blocked-live-step');
  chk('决策-频控达限⇒阻断', decide({ healthy: false, aliveSteps: 0, rate: { allowed: false, recentCount: 2 }, apply: true }).action === 'blocked-rate-limit');
  chk('决策-dry-run⇒would-reset', decide({ healthy: false, aliveSteps: 0, rate: { allowed: true, recentCount: 0 }, apply: false }).action === 'would-reset');
  chk('决策-apply⇒reset', decide({ healthy: false, aliveSteps: 0, rate: { allowed: true, recentCount: 0 }, apply: true }).action === 'reset');
  chk('护栏优先级：在跑 > 频控（先判在跑）', decide({ healthy: false, aliveSteps: 1, rate: { allowed: false, recentCount: 9 }, apply: true }).action === 'blocked-live-step');

  console.log(`post-page-reset-selftest: ${ok ? 'ALL PASS' : 'FAIL'}`);
  return ok ? 0 : 1;
}

const rc = await main(process.argv);
process.exit(rc);
