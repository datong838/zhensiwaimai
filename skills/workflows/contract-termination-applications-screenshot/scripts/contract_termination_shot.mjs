#!/usr/bin/env node
// contract_termination_shot.mjs —— 服务商平台「合同解约申请」任务列表截图（工位 9231）
//
// 业务口径（大同 2026-10-20）：与 Top10 同一条流程形态（进页面 → 筛选 → 截表格原图落盘），
// 只是菜单换成 客户管理 → 合同解约申请，且「任务状态」固定选「处理中」。
//   页面：https://open.shop.ele.me/manager/agent/dissolution-task
//   截图范围：蓝色标题条「任务列表」+ 表头 + 全部数据行（对齐大同给的示例图，不含操作区/分页器）
//   分页：默认 10 条/页；超出则逐页截图（不漏记录），文件名带 p1/p2…
//
// 纪律（沿用本仓既有硬规矩）：
//   · 只驱动已运行的后台专用 Chrome（127.0.0.1:9231），不启动/重启浏览器；
//   · 不新开标签页：复用 context 现有 page，站内点击菜单 + 直接 goto 本站路由；
//   · 抢 taobao-svc-post 工位锁，抢不到即 exited(4) SKIPPED_BUSY，绝不干扰正在跑的采集流；
//   · 登录态硬闸：origin 断言 + 登录特征断言，命中即 service-login-required，不截图；
//   · 只读：不点「导出查询结果」，不动任何「操作」列按钮，不提交任何写操作；
//   · 收尾复位到 home，保持工位已知良好态；
//   · flushExit 保证进程退出（防 CDP 句柄挂住）。
//
// 用法：
//   node contract_termination_shot.mjs                 # 真跑：筛选处理中 + 截图落盘
//   node contract_termination_shot.mjs --dry-run       # 只读：进页 + 转储结构，不筛选不截图
//   node contract_termination_shot.mjs --task-status 已完成
//   node contract_termination_shot.mjs --json          # 仅输出 JSON
//   node contract_termination_shot.mjs --self-test     # 纯函数判据自检（不碰工位）
// 退出码：0=成功；3=登录/页面异常；4=工位忙跳过；9=其它错误

import process from 'node:process';
import { createRequire } from 'node:module';
import { connectToPost } from '../../../posts/taobao-svc-post/scripts/connect.mjs';
import { acquirePostLease, releasePostLease } from '../../../posts/taobao-svc-post/scripts/lease.mjs';
import { assertAuthenticated, assertOrigin } from '../../../posts/taobao-svc-post/scripts/auth.mjs';

const require = createRequire(import.meta.url);
const fs = require('node:fs');
const path = require('node:path');

const HOME = '/Users/ddt/work/projects/ai_agent/zhensi_waimai_back';
const HOME_URL = 'https://open.shop.ele.me/manager/base/home';
const ROUTE = 'https://open.shop.ele.me/manager/agent/dissolution-task';

const argv = process.argv.slice(2);
const JSON_ONLY = argv.includes('--json');
const DRY = argv.includes('--dry-run');
const SELF_TEST = argv.includes('--self-test');
const argOf = (name, dflt) => { const i = argv.indexOf(name); return i >= 0 && argv[i + 1] ? argv[i + 1] : dflt; };
const TASK_STATUS = argOf('--task-status', '处理中');
const OUT_ROOT = argOf('--out-dir', path.join(HOME, 'runtime/state/screenshots/contract-termination'));

// ───────── 纯函数（可离线自检，判据不依赖浏览器） ─────────

// 分页器文本 → 总条数：'共 5 条' / '共5条' / 无 → null
export function parseTotal(text) {
  const m = String(text || '').match(/共\s*(\d+)\s*条/);
  return m ? Number(m[1]) : null;
}

// 每页条数：'10 条/页' → 10；缺失 → 10（站点默认）
export function parsePageSize(text, dflt = 10) {
  const m = String(text || '').match(/(\d+)\s*条\s*\/\s*页/);
  return m ? Number(m[1]) : dflt;
}

// 依据 total/pageSize 判定页数（total 未知时按 1 页，交由调用方另判）
export function planPages(total, pageSize) {
  if (!Number.isFinite(total) || total < 0) return 1;
  if (!Number.isFinite(pageSize) || pageSize <= 0) return 1;
  return Math.max(1, Math.ceil(total / pageSize));
}

export function completeCapture(actualPages, plannedPages, actualRows, total) {
  return Number.isInteger(actualPages) && actualPages > 0 && Number.isInteger(plannedPages)
    && actualPages === plannedPages && Number.isInteger(actualRows) && actualRows >= 0
    && (total === null || Number.isInteger(total) && total >= 0 && actualRows === total);
}

// 下拉选项里精确定位目标项（禁模糊匹配：'处理中' 不得命中 '待处理中'）
export function pickOptionIndex(options, want) {
  const arr = Array.isArray(options) ? options : [];
  const norm = s => String(s || '').replace(/\s+/g, '').trim();
  const idx = arr.findIndex(o => norm(o) === norm(want));
  return idx;
}

// 表格行去噪：全空行（nbsp/空串）丢弃
export function cleanRows(rows) {
  return (Array.isArray(rows) ? rows : [])
    .map(r => (Array.isArray(r) ? r.map(c => String(c || '').replace(/\u00a0/g, ' ').trim()) : []))
    .filter(r => r.some(c => c !== ''));
}

// 截图矩形：宿主元素可视框 + 文档滚动偏移（CDP captureBeyondViewport 用文档坐标）
export function buildClip(host, tableBottom, scrollX, scrollY) {
  if (!host) return null;
  const x = Math.round(host.x + (scrollX || 0));
  const y = Math.round(host.y + (scrollY || 0));
  const w = Math.round(host.w);
  const h = Math.round((tableBottom != null ? tableBottom : host.y + host.h) - host.y);
  if (!(w > 0) || !(h > 0)) return null;
  return { x, y, width: w, height: h, scale: 1 };
}

export function selfTest() {
  const cases = [
    { name: 'parseTotal·正 共 5 条', got: parseTotal('共 5 条'), want: 5 },
    { name: 'parseTotal·正 无空格 共13条', got: parseTotal('共13条'), want: 13 },
    { name: 'parseTotal·负 无分页文本 ⇒ null', got: parseTotal('任务列表'), want: null },
    { name: 'parsePageSize·正 20 条/页', got: parsePageSize('20 条/页'), want: 20 },
    { name: 'parsePageSize·缺省 ⇒ 10', got: parsePageSize(''), want: 10 },
    { name: 'planPages·正 25/10 ⇒ 3 页', got: planPages(25, 10), want: 3 },
    { name: 'planPages·正 10/10 ⇒ 1 页', got: planPages(10, 10), want: 1 },
    { name: 'planPages·负 total=0 ⇒ 1 页', got: planPages(0, 10), want: 1 },
    { name: 'pickOptionIndex·正 处理中', got: pickOptionIndex(['已完成', '处理中'], '处理中'), want: 1 },
    { name: 'pickOptionIndex·负 待处理中 ≠ 处理中', got: pickOptionIndex(['待处理中'], '处理中'), want: -1 },
    { name: 'cleanRows·负 全 nbsp 行被丢', got: cleanRows([['\u00a0', ' '], ['a', '']]).length, want: 1 },
    { name: 'buildClip·正 加滚动偏移', got: JSON.stringify(buildClip({ x: 10, y: 20, w: 800, h: 100 }, 120, 0, 500)), want: JSON.stringify({ x: 10, y: 520, width: 800, height: 100, scale: 1 }) },
    { name: 'buildClip·负 零宽 ⇒ null', got: buildClip({ x: 0, y: 0, w: 0, h: 0 }, 0, 0, 0), want: null },
    { name: 'completeCapture·完整多页', got: completeCapture(2,2,12,12), want: true },
    { name: 'completeCapture·缺页', got: completeCapture(1,2,10,12), want: false },
    { name: 'completeCapture·缺行', got: completeCapture(2,2,11,12), want: false },
    { name: 'completeCapture·无总数仍核对页数', got: completeCapture(2,2,12,null), want: true },
    { name: 'completeCapture·空表一页', got: completeCapture(1,1,0,0), want: true },
    { name: 'completeCapture·无页不可成功', got: completeCapture(0,0,0,0), want: false },
  ];
  let pass = 0;
  const fails = [];
  for (const c of cases) {
    const ok = JSON.stringify(c.got) === JSON.stringify(c.want);
    if (ok) pass++; else fails.push(`${c.name}（got=${JSON.stringify(c.got)} want=${JSON.stringify(c.want)}）`);
  }
  console.log(`SELF-TEST: ${pass} passed, ${fails.length} failed`);
  fails.forEach(f => console.log('  FAIL ' + f));
  return fails.length === 0;
}

// ───────── 运行期工具 ─────────

const log = (...a) => { if (!JSON_ONLY) console.log(...a); };
const sleep = ms => new Promise(r => setTimeout(r, ms));

// 进程级单次退出：务必先释放工位租约再 exit（否则租约被死 pid 占住，后续 run 全部 SKIPPED_BUSY）
let LEASE = null;
let BROWSER = null;
let exiting = false;
async function shutdown(code, payload) {
  if (exiting) return;
  exiting = true;
  try {
    if (LEASE) await releasePostLease(LEASE);
  } catch {}
  LEASE = null;
  try { if (BROWSER) await BROWSER.close(); } catch {}
  BROWSER = null;
  const out = JSON.stringify(payload);
  process.stdout.write(out + '\n', () => process.exit(code));
  setTimeout(() => process.exit(code), 3000).unref();
}

async function loginGuard(page) {
  assertOrigin(page.url());
  const body = await page.evaluate(() => (document.body && document.body.innerText) || '');
  assertAuthenticated(body);
  return body;
}

// 等待表格渲染出「任务列表」+ 至少一个业务行或明确空态
async function waitTableReady(page, timeoutMs = 25000) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    const st = await page.evaluate(() => {
      const body = (document.body && document.body.innerText) || '';
      const rows = document.querySelectorAll('.ant-table-tbody tr.ant-table-row').length;
      const empty = !!document.querySelector('.ant-table-placeholder') || /暂无数据|没有数据|暂无内容/.test(body);
      const spin = !!document.querySelector('.ant-spin-spinning');
      return { hasTitle: body.includes('任务列表'), rows, empty, spin, hasPager: /共\s*\d+\s*条/.test(body) };
    });
    if (st.hasTitle && !st.spin && (st.rows > 0 || st.empty || st.hasPager)) return st;
    await sleep(800);
  }
  throw new Error('table-not-ready');
}

// 读取表头/数据行（antd：表头 .ant-table-thead th，数据行 .ant-table-tbody tr.ant-table-row；
// 页面里第一张 <table> 是 antd 的定宽量测表，没有数据行，不可用 table.rows 取数）
async function readTable(page) {
  return await page.evaluate(() => {
    const norm = s => String(s || '').replace(/\u00a0/g, ' ').replace(/\n/g, ' ').trim();
    const ths = [...document.querySelectorAll('.ant-table-thead th')];
    const headers = ths.map(th => norm(th.innerText));
    const trs = [...document.querySelectorAll('.ant-table-tbody tr.ant-table-row')];
    const rows = trs.map(tr => [...tr.children].map(td => norm(td.innerText)));
    const pagerEl = document.querySelector('.ant-pagination');
    return { headers, rows, pager: pagerEl ? norm(pagerEl.innerText) : '', body: (document.body.innerText || '') };
  });
}

// 「任务状态」下拉定位：在文档顺序上找 label 之后出现的第一个 .ant-select（禁按下标硬编码）
async function locateSelectAfterLabel(page, label) {
  return await page.evaluate((lb) => {
    const all = [...document.querySelectorAll('.ant-select')];
    const labelEl = [...document.querySelectorAll('*')].find(e =>
      e.children.length === 0 && (e.textContent || '').trim() === lb);
    if (!labelEl) return -1;
    const pos = labelEl.compareDocumentPosition;
    for (let i = 0; i < all.length; i++) {
      // 4 = Node.DOCUMENT_POSITION_FOLLOWING
      if (pos.call(labelEl, all[i]) & Node.DOCUMENT_POSITION_FOLLOWING) return i;
    }
    return -1;
  }, label);
}

async function pickSelectOption(page, selectIndex, want) {
  const sel = page.locator('.ant-select').nth(selectIndex);
  await sel.scrollIntoViewIfNeeded().catch(() => {});
  await sel.click({ timeout: 10000 });
  await page.waitForTimeout(600);
  const opts = await page.evaluate(() => [...document.querySelectorAll('.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option-content')].map(o => (o.innerText || '').trim()));
  const idx = pickOptionIndex(opts, want);
  if (idx < 0) { await page.keyboard.press('Escape'); throw new Error(`option-not-found:${want} in ${JSON.stringify(opts)}`); }
  await page.locator('.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option').nth(idx).click({ timeout: 8000 });
  await page.waitForTimeout(400);
  return opts;
}

async function clickQuery(page) {
  const btn = page.getByRole('button', { name: /查\s*询/ }).first();
  if (!(await btn.count())) throw new Error('query-button-missing');
  await btn.click({ timeout: 10000 });
  await page.waitForTimeout(1200);
}

// 几何：返回宿主（含「任务列表」标题的最小祖先）与表格底部。
// 截图前先把页面滚到顶、把表体横向滚回 0，保证 clip 与真实像素一一对应（否则会切掉右侧列）。
async function measure(page) {
  await page.evaluate(() => {
    window.scrollTo(0, 0);
    const tb = document.querySelector('.ant-table-body, .ant-table-content');
    if (tb) tb.scrollLeft = 0;
  });
  await sleep(300);
  return await page.evaluate(() => {
    const table = document.querySelector('.ant-table');
    if (!table) return null;
    let el = table, host = null;
    while (el && el !== document.body) {
      if ((el.innerText || '').includes('任务列表')) { host = el; break; }
      el = el.parentElement;
    }
    const h = host || table.parentElement;
    const hr = h.getBoundingClientRect();
    const rows = [...document.querySelectorAll('.ant-table-tbody tr.ant-table-row')];
    const last = rows[rows.length - 1];
    const tableBottom = last ? last.getBoundingClientRect().bottom : table.getBoundingClientRect().bottom;
    const body = document.querySelector('.ant-table-body, .ant-table-content');
    return {
      host: { x: hr.x, y: hr.y, w: hr.width, h: hr.height },
      tableBottom,
      scrollX: window.scrollX, scrollY: window.scrollY,
      innerHScroll: body ? body.scrollWidth > body.clientWidth + 2 : false,
      docH: document.documentElement.scrollHeight,
      hostCls: (h.className || '').toString().slice(0, 60),
    };
  });
}

async function capture(page, outFile) {
  // 该工位窗口只有 ~1126 宽，而表格最小宽度 1440（12 列×120px）⇒ 不放大视口右侧列会被切掉。
  // 用 CDP 视口覆盖把宽度提到 1800、DSF=2（同 Top10「固定 viewport + 原图」口径），截完立即清除。
  const cdp = await page.context().newCDPSession(page);
  try {
    await cdp.send('Emulation.setDeviceMetricsOverride', { width: 1800, height: 1200, deviceScaleFactor: 2, mobile: false });
    await sleep(1200);
    const m = await measure(page);
    if (!m) throw new Error('table-geometry-missing');
    const clip = buildClip(m.host, m.tableBottom, m.scrollX, m.scrollY);
    if (!clip) throw new Error('clip-invalid');
    const shot = await cdp.send('Page.captureScreenshot', { format: 'png', fromSurface: true, captureBeyondViewport: true, clip });
    fs.mkdirSync(path.dirname(outFile), { recursive: true });
    fs.writeFileSync(outFile, Buffer.from(shot.data, 'base64'), { mode: 0o600 });
    const size = fs.statSync(outFile).size;
    if (!size) throw new Error('screenshot-empty');
    return { file: outFile, size, clip, innerHScroll: m.innerHScroll, hostCls: m.hostCls };
  } finally {
    await cdp.send('Emulation.clearDeviceMetricsOverride').catch(() => {});
    await cdp.detach().catch(() => {});
  }
}

async function main() {
  const now = new Date();
  const ymd = new Intl.DateTimeFormat('sv-SE', {timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(now);
  const hhmm = new Intl.DateTimeFormat('en-GB', {timeZone:'Asia/Shanghai',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(now).replace(':','');
  const outDir = path.join(OUT_ROOT, ymd);
  const runId = `contract-termination-shot-${now.getTime()}`;
  const receipt = { runId, at: now.toISOString(), route: ROUTE, taskStatus: TASK_STATUS, outDir, pages: [], rows: [], header: null, warnings: [], reset: null };

  const LEASE_PATH = '/tmp/zhensi-post-9231.lock';
  LEASE = await acquirePostLease(runId, LEASE_PATH);
  if (!LEASE) { log('SKIPPED_BUSY: 9231 工位忙（他人持有租约），不驱动浏览器'); return shutdown(4, { ...receipt, ok: false, reason: 'post-busy' }); }

  try {
    const conn = await connectToPost();
    BROWSER = conn.browser;
    const page = conn.page;

    if (!page.url().includes('dissolution-task')) {
      await page.goto(ROUTE, { waitUntil: 'domcontentloaded', timeout: 45000 });
    }
    await sleep(3000);
    let body = await loginGuard(page);
    log('URL=', page.url());
    log('页头:', (body.match(/合同解约申请[\s\S]{0,60}/) || [''])[0].replace(/\n/g, ' ').trim());

    if (DRY) {
      const t = await waitTableReady(page).catch(() => null);
      const tbl = await readTable(page);
      log('DRY 表头=', JSON.stringify(tbl.headers));
      log('DRY 行数=', cleanRows(tbl.rows).length, ' pager=', tbl.pager.replace(/\n/g, ' ').slice(0, 80));
      log('DRY ready=', JSON.stringify(t));
      return shutdown(0, { ...receipt, ok: true, dryRun: true, headers: tbl.headers, rowsRaw: cleanRows(tbl.rows) });
    }

    // 1) 任务状态 → 指定值
    const si = await locateSelectAfterLabel(page, '任务状态');
    if (si < 0) throw new Error('task-status-select-not-found');
    const opts = await pickSelectOption(page, si, TASK_STATUS);
    log(`任务状态 选项=${JSON.stringify(opts)} → 选中 ${TASK_STATUS}`);
    receipt.taskStatusOptions = opts;

    // 2) 查询
    await clickQuery(page);
    const ready = await waitTableReady(page);
    receipt.tableReady = ready;

    // 3) 取总数/页数（本页分页器不显示「共N条」，只有页码序列 ⇒ 总条数缺失时用最大页码兜底）
    let tbl = await readTable(page);
    const pagerInfo = await page.evaluate(() => {
      const items = [...document.querySelectorAll('.ant-pagination-item')];
      const nums = items.map(li => Number(li.getAttribute('title') || (li.textContent || '').trim())).filter(n => Number.isFinite(n) && n > 0);
      return { maxPage: nums.length ? Math.max(...nums) : 1, nums };
    });
    const total = parseTotal(tbl.pager);
    const pageSize = parsePageSize(await page.evaluate(() => {
      const el = document.querySelector('.ant-pagination-options');
      return el ? (el.innerText || '') : '';
    }));
    const pages = total != null ? planPages(total, pageSize) : (pagerInfo.maxPage || 1);
    const m0 = (tbl.body.match(/待处理申请数量\s*(\d+)\s*个[,，]?\s*超时\s*(\d+)\s*个/) || null);
    receipt.header = m0 ? { pending: Number(m0[1]), overdue: Number(m0[2]) } : null;
    receipt.pager = { total, pageSize, pages, maxPageFromPager: pagerInfo.maxPage };
    log(`待处理申请数量：${receipt.header ? receipt.header.pending : '?'}（超时 ${receipt.header ? receipt.header.overdue : '?'}）｜总条数=${total ?? '未显示'} / ${pageSize} 条每页 / 分页器最大页码=${pagerInfo.maxPage} ⇒ 截图 ${pages} 页`);

    // 4) 逐页截图（不漏记录）
    const dateTag = ymd;
    for (let p = 1; p <= pages; p++) {
      await waitTableReady(page);
      tbl = await readTable(page);
      const rows = cleanRows(tbl.rows);
      if (p === 1) receipt.headers = tbl.headers;
      const outFile = path.join(outDir, `${dateTag}_合同解约申请_${TASK_STATUS}_p${p}.png`);
      const cap = await capture(page, outFile);
      receipt.pages.push({ page: p, rows: rows.length, file: cap.file, bytes: cap.size, clip: cap.clip, innerHScroll: cap.innerHScroll });
      receipt.rows.push(...rows);
      if (cap.innerHScroll) receipt.warnings.push(`p${p} 表体存在横向滚动（右侧列可能被切）`);
      log(`p${p}: ${rows.length} 行 → ${cap.file} (${(cap.size / 1024).toFixed(0)} KB, ${cap.clip.width}×${cap.clip.height})`);

      if (p < pages) {
        const next = page.locator('.ant-pagination-next').first();
        const disabled = await page.evaluate(() => {
          const n = document.querySelector('.ant-pagination-next');
          return !n || n.className.includes('disabled') || n.getAttribute('aria-disabled') === 'true';
        });
        if (disabled) { receipt.warnings.push(`第 ${p} 页后『下一页』不可用，与实际页数 ${pages} 不符`); break; }
        const firstBefore = JSON.stringify(rows[0] || []);
        await next.click({ timeout: 10000 });
        await page.waitForTimeout(2500);
        await waitTableReady(page).catch(() => {});
        const after = await readTable(page);
        if (JSON.stringify(cleanRows(after.rows)[0] || []) === firstBefore) {
          receipt.warnings.push(`第 ${p} 页翻页后首行未变化，判定翻页失败`);
          break;
        }
      }
    }

    // 5) 状态一致性自检：所有行任务状态必须等于目标值
    const statusIdx = (receipt.headers || []).findIndex(h => h.replace(/\s/g, '') === '任务状态');
    if (statusIdx >= 0) {
      const bad = receipt.rows.filter(r => String(r[statusIdx] || '').replace(/\s/g, '') !== TASK_STATUS.replace(/\s/g, ''));
      if (bad.length) receipt.warnings.push(`有 ${bad.length} 行任务状态 ≠ ${TASK_STATUS}`);
      receipt.statusCheck = { index: statusIdx, bad: bad.length, sampleBad: bad.slice(0, 3) };
    } else {
      receipt.warnings.push('表头未找到「任务状态」列，无法做状态一致性自检');
    }

    // 6) 收尾复位到 home（保持工位已知良好态）
    try {
      await page.goto(HOME_URL, { waitUntil: 'domcontentloaded', timeout: 45000 });
      await sleep(2500);
      receipt.reset = page.url();
    } catch (e) { receipt.warnings.push('复位 home 失败：' + e.message.slice(0, 80)); }

    receipt.completePages = completeCapture(receipt.pages.length, pages, receipt.rows.length, total);
    const ok = receipt.pages.length > 0 && receipt.completePages && (receipt.statusCheck ? receipt.statusCheck.bad === 0 : false);
    receipt.ok = ok;
    fs.mkdirSync(outDir, { recursive: true });
    const receiptFile = path.join(outDir, `${dateTag}_contract-termination_run-${hhmm}.json`);
    fs.writeFileSync(receiptFile, JSON.stringify(receipt, null, 2));
    receipt.receiptFile = receiptFile;
    log(`收据: ${receiptFile}`);
    log(`合计 ${receipt.rows.length} 行 / ${receipt.pages.length} 页；状态自检=${receipt.statusCheck ? receipt.statusCheck.bad : 'n/a'} 异常`);
    if (receipt.warnings.length) log('告警: ' + receipt.warnings.join(' | '));
    return shutdown(ok ? 0 : 9, receipt);
  } catch (e) {
    const msg = String(e && e.message || e);
    const loginish = /service-login-required|service-origin-changed/.test(msg);
    log('FAIL:', msg);
    if (msg.includes('service-login-required')) log('⇒ 9231 掉登录，需人工有头重登');
    return shutdown(loginish ? 3 : 9, { ...receipt, ok: false, error: msg });
  } finally {
    // shutdown() 已负责释放租约 + 关连接；此处仅兜底
    if (LEASE) await releasePostLease(LEASE).catch(() => {});
    LEASE = null;
    if (BROWSER) await BROWSER.close().catch(() => {});
    BROWSER = null;
  }
}

if (SELF_TEST) { process.exit(selfTest() ? 0 : 1); } else { await main(); }
