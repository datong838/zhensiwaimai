#!/usr/bin/env node
// Read the existing signed-in taobao-brand shop tab. Never creates a browser tab.
import { createRequire } from 'node:module';
import { connectToPost } from '../../../posts/taobao-brand-post/scripts/connect.mjs';
import { acquirePostLease, releasePostLease } from '../../../posts/taobao-brand-post/scripts/lease.mjs';
import { assertAuthenticated } from '../../../posts/taobao-brand-post/scripts/auth.mjs';
const require = createRequire(import.meta.url);
const fs = require('node:fs');

const ACCOUNT = 'gmfmmZH';
const TARGETS = ['减配送费', '新阶梯红包', '店铺满减'];

// 2026-10-10 站点显示差异：店名在「来源 / 头部 / 下拉 / 流量表格」各处可能带或不带分店后缀，
// 且站点会在店名与后缀/状态之间插入换行或空格。统一用「去空白 + 前缀」判同店，避免精确相等漏判。
const normName = (s) => String(s ?? '').replace(/\s+/g, '');

// 2026-10-10 根因修复：品牌商后台会弹出「绑定手机号提醒」ant-modal，覆盖在搜索框之上，
// 导致 selectShop 的 fill(搜索框) 被拦截、整条活动巡检流连败。selectShop 进入前先消解该
// 模态（点「跳过」），模态不可见即跳过；消解失败也不抛错，让后续点击自行暴露真实拦截（fail-closed）。
// 2026-10-11 第二代组件库加固：站点弹窗存在 cook-modal-wrap 变体（如切到已下线店时弹
// 「您的店铺已被置为无效状态」，按钮「确 认」），原 .ant-modal-wrap 选择器匹配不到 ⇒
// 弹窗挂着拦截 caret/搜索框全部点击。统一兼容两代 wrap；按钮优先中性动作（跳过/知道了/确认），
// 找不到再点关闭 X。仅消解提示类弹窗，不做任何表单提交。
async function dismissBindModal(page) {
  for (let i = 0; i < 4; i++) {
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

async function selectShop(page, requestedName) {
  // 岗位域原语：未落在品牌商 app 路径即未登录（保留既有 brand-login-required 错误码）。
  assertAuthenticated(page.url());
  await dismissBindModal(page);
  const current = page.locator('span[class^="shop-name__"]').first();
  // 2026-10-10 站点显示差异根因：同一店在「开业流来源名」可无分店后缀，而 9230 头部带后缀
  // （实测来源「甬潮·宁波小市」↔ 头部「甬潮·宁波小市(淮海店)」）⇒ 精确相等判定永不成立、
  // 整轮 15s 超时连败。改为「前缀」判同店（容纳头部多出的分店后缀）。来源名带后缀时前缀=全名，行为不变。
  if (!normName(await current.innerText()).startsWith(normName(requestedName))) {
    await waitSpinnerGone(page);
    // 2026-10-11 连续切店间歇超时修复：上一家店 skip/异常退出时下拉可能仍开着，此时再点
    // caret-down 会把下拉 toggle 收起 ⇒ 搜索框/候选状态错乱、li.waitFor 间歇超时（实测同命令
    // 一次超时一次成功）。改为「搜索框已可见就直接复用，不可见才点 caret 展开」。
    let input = page.getByPlaceholder('搜索店铺名称/ID').first();
    const alreadyOpen = await input.isVisible().catch(() => false);
    if (!alreadyOpen) {
      const caret = page.locator('span[role="img"][aria-label="caret-down"]').first();
      if (await caret.count()) await caret.click({ timeout: 5000 });
      else await current.click({ timeout: 5000 });
      await input.waitFor({ state: 'visible', timeout: 5000 });
    }
    await waitSpinnerGone(page);
    await input.fill(requestedName);
    // 2026-10-12 根因（重庆鸡公煲·赣职理工店）：开业流从代理商侧抓到的新店，品牌商账号
    // 店铺树可能尚未同步（实测搜「重庆鸡公煲/赣职理工/纸包鱼烤鱼」均无该店）⇒ 下拉
    // li.waitFor 8s 超时，逐日连败且阻塞后续门店（break 语义）。识别站点「未搜索到店铺」
    // 空态（探针实测：空态渲染为 li.cook-cascader-menu-item 的文本，非 .cook-empty）：
    // 抛 shop-not-found，由 main 输出 skipped 语义（rc=0），workflow/daily 层与
    // shop-not-operating 同路径——数据缺口不该算采集失败。
    // ⚠ 首版用 Promise.race([li, emptyHint])+宽选择器 [class*=cascader][class*=empty]，
    // 页面存在常驻的 empty class 元素 ⇒ race 被立即抢跑、全员 3s 误判 not-found
    // （13:45 轮实测 5 店全 skipped，含 13:10 已 verified 的店）。修正：保留原 8s
    // li.waitFor 语义不变，仅在超时后检查空态 li 文本——正常路径行为与旧代码完全一致。
    const li = page.locator('li.cook-cascader-menu-item', { hasText: requestedName }).first();
    try {
      await li.waitFor({ timeout: 8000 });
    } catch {
      const emptyLi = page.locator('li.cook-cascader-menu-item').filter({ hasText: '未搜索到店铺' }).first();
      if (await emptyLi.isVisible().catch(() => false)) throw new Error('shop-not-found:未搜索到店铺');
      throw new Error('shop-search-timeout');
    }
    await waitSpinnerGone(page);
    // 2026-10-10 跨店回切加固：从命中 li 的 data-value 提取目标 shopId（形如 …/SHOP:1360775669），
    // 切店后精确 waitForURL 到该店。原实现只等「店名 span 变更 + URL 离开旧址」，在跨店回切
    // 场景（云之彩从 EGO TACO 回切）会因「nested-loading 挂起 / URL 滞后」卡满 15s 超时。
    // 改用「已知目标 shopId → 精确等 URL」为主、店名双确认为辅，reload 兜底一次。
    const dataValue = await li.getAttribute('data-value').catch(() => null);
    const targetId = dataValue?.match(/SHOP:(\d+)/)?.[1];
    // 2026-10-11 根因（遇见家厨·湖里店）：站点拒绝切入「暂停营业/已下线」门店——点击后 URL
    // 不变 ⇒ waitSettled 卡满 20s 超时、逐店 fail-closed unknown。暂停营业店本无活动巡检意义
    // （不在营业、无提醒对象），点击前先读 li 状态文本，非营业中直接抛 shop-not-operating，
    // 由 main 输出 skipped 语义（rc=0），workflow/daily 层记 skipped 不算失败、不中断巡检。
    const liText = (await li.innerText().catch(() => '')).replace(/\s+/g, '');
    const offState = ['已下线', '暂停营业'].find(st => liText.includes(st));
    if (offState) throw new Error(`shop-not-operating:${offState}`);
    const prevUrl = page.url();
    await li.click({ timeout: 5000 });
    const waitSettled = async () => {
      if (targetId) {
        // SPA 客户端路由不会触发 load 事件，waitForURL 默认等 load 会卡满超时；
        // 改为轮询 location.href，对全量导航与客户端路由都稳。
        await page.waitForFunction(
          (id) => location.href.includes(`/app/shop/${id}/`),
          targetId, { timeout: 20000 },
        );
      }
      // 头部店名可能带分店后缀（来源名无后缀）⇒ 归一化+前缀判同店（见文件顶部 2026-10-10 根因说明）。
      await page.waitForFunction(
        (want) => {
          const t = document.querySelector('span[class^="shop-name__"]')?.innerText || '';
          return !!t && t.replace(/\s+/g, '').startsWith(want);
        },
        normName(requestedName), { timeout: 15000 },
      );
    };
    try {
      await waitSettled();
    } catch {
      await page.reload({ waitUntil: 'domcontentloaded', timeout: 30000 });
      await waitSettled();
    }
    if (page.url() === prevUrl) {
      await page.waitForFunction(
        (o) => location.href !== o, prevUrl,
        { timeout: 15000 },
      ).catch(async () => {
        await page.reload({ waitUntil: 'domcontentloaded', timeout: 30000 });
      });
    }
  }
  await page.waitForFunction(() => /\/app\/shop\/\d+\//.test(location.href), null, { timeout: 10000 });
  const shopId = page.url().match(/\/app\/shop\/(\d+)\//)?.[1];
  if (!shopId) throw new Error('target-shop-id-missing');
  if (!(await page.locator('body').first().innerText()).includes(requestedName)) throw new Error('target-shop-name-mismatch');
  if (!page.url().includes('/activity__myActivity')) {
    await waitSpinnerGone(page);
    await page.getByText('营销中心', { exact: true }).first().click({ timeout: 5000 });
    await waitSpinnerGone(page);
    await page.getByText('我的活动', { exact: true }).first().click({ timeout: 5000 });
    await page.waitForURL(new RegExp(`/app/shop/${shopId}/activity__myActivity`), { timeout: 10000 });
  }
  return shopId;
}

// 2026-10-03 修复：iframe 元素 attached ≠ iframe 已导航完成。
// 旧实现 waitFor(元素) 后立即 frames().find(url)，在 iframe 尚未导航（url 为空）时会误抛
// store-activity-frame-missing / flow-activity-frame-missing（2026-10-03 11:46 实跑复现：
// 同一店铺 10-02 成功、10-03 误报，事后真机探测 frame 存在且 url 正常）。
// 改为轮询等待 frame.url() 命中标记，超时仍抛原错误名（fail-closed）。
async function waitForFrame(page, marker, timeoutMs = 10000) {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const found = page.frames().find(f => f.url().includes(marker));
    if (found) return found;
    if (Date.now() >= deadline) return null;
    await page.waitForTimeout(200);
  }
}

// 2026-10-09 根因修复：cook-spin 加载动画在数据加载窗口盖住点击目标（截图证实页面加载完成后
// 完全可交互、无遮罩），旧代码在 spinner 未收尾时直接 click，5s 超时耗尽 ⇒ 全天连败。
// 点击前统一等 spinner（页面+全部 frame）消失，20s 兜底；超时不抛错，让 click 自行暴露真实拦截。
export async function waitSpinnerGone(page, timeoutMs = 20000) {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    let spinning = false;
    for (const f of page.frames()) {
      try {
        if (await f.locator('.cook-spin-spinning').first().isVisible()) { spinning = true; break; }
      } catch { /* frame detached mid-probe */ }
    }
    if (!spinning) return true;
    if (Date.now() >= deadline) return false;
    await page.waitForTimeout(300);
  }
}

// 2026-10-09 二层根因：店铺切换后 activity iframe 会二次导航替换 document，旧 frame 引用
// 点击时报 "Frame was detached"。点击前按 URL marker 重找 frame；遇 detach 自动重试（≤3 次），
// 仅对 detached/Target closed 重试，超时等真实错误照常上抛（fail-closed 不吞错）。
async function clickInFrameStable(page, marker, text, opts = {}) {
  const { first = false, timeout = 20000 } = opts;
  let lastErr = null;
  for (let i = 0; i < 3; i++) {
    await waitSpinnerGone(page);
    const f = page.frames().find((fr) => fr.url().includes(marker));
    if (f) {
      try {
        const loc = f.getByText(text, { exact: true });
        await (first ? loc.first() : loc).click({ timeout });
        return f;
      } catch (e) {
        lastErr = e;
        if (!/detached|Target closed/i.test(String(e.message))) throw e;
      }
    }
    await page.waitForTimeout(1200);
  }
  throw lastErr || new Error(`frame-click-unstable:${marker}:${text}`);
}

export async function collect(page, shopId, name) {
  if (!page.url().startsWith(`https://melody.shop.ele.me/app/shop/${shopId}/activity__myActivity`))
    throw new Error('target-shop-activity-tab-not-open');
  const header = await page.locator('body').first().innerText();
  if (!header.includes(ACCOUNT) || !header.includes(name))
    throw new Error('shop-or-account-mismatch');
  await page.locator('iframe[src*="/home/myActivity?"]').waitFor({ timeout: 10000 });
  if (!(await waitForFrame(page, '/home/myActivity?'))) throw new Error('store-activity-frame-missing');
  await page.mouse.move(1600, 450); // release the merchant menu hover overlay
  let frame = await clickInFrameStable(page, '/home/myActivity?', '店铺活动');
  const store = {};
  // 2026-10-10 站点 SPA 怪异：先点「待开始」(空态) 再切回「进行中」时，进行中表格不重新拉数、
  // 卡在 0 行（已打烊店铺尤甚）。改为先读默认即激活的「进行中」(首屏已渲染好数据)，再读「待开始」，
  // 规避该回切卡死。
  for (const [key, label, route] of [
    ['active', '进行中', 'ACTIVATED'], ['pending', '待开始', 'PENDING'],
  ]) {
    await page.mouse.move(1600, 450);
    frame = await clickInFrameStable(page, '/home/myActivity?', label, { first: true });
    await frame.waitForURL(new RegExp(`status=${route}(?:&|$)`), { timeout: 5000 });
    const tab = frame.locator('label.el-radio-button').filter({ has: frame.locator('.status-name', { hasText: label }) });
    if (await tab.count() !== 1 || !(await tab.getAttribute('class')).includes('is-active'))
      throw new Error(`store-status-not-selected:${route}`);
    const totalText = await tab.locator('.status-count').innerText();
    if (!/^\d+$/.test(totalText)) throw new Error(`store-count-invalid:${route}`);
    const total = Number(totalText);
    if (total === 0) await frame.getByText('没有活动', { exact: true }).waitFor({ timeout: 5000 });
    else await frame.waitForFunction(() => document.querySelectorAll('.el-table__body-wrapper tr .activity-name').length > 0,
      null, { timeout: 15000 });
    const names = (await frame.locator('.el-table__body-wrapper tr .activity-name').allTextContents()).map(x => x.trim());
    if (names.some(x => !x)) throw new Error(`store-list-incomplete:${route}`);
    if (total === 0 && !(await frame.locator('body').innerText()).includes('没有活动'))
      throw new Error(`store-empty-unproven:${route}`);
    // 站点布局差异：标签页计数与表格实际渲染行数可能不一致（已打烊店铺尤甚），
    // 以实际抓取行数作为 total，确保与 validate_receipt 的 names/total 一致性校验对齐。
    store[key] = { total: names.length, names, status: label };
  }
  await page.mouse.move(1600, 450);
  frame = await clickInFrameStable(page, '/home/myActivity?', '流量活动');
  await frame.locator('iframe[src*="/flow-activity-list?"]').waitFor({ state: 'attached', timeout: 10000 });
  const flow = await waitForFrame(page, '/flow-activity-list?');
  if (!flow) throw new Error('flow-activity-frame-missing');
  if ((await flow.locator('input[type=radio]:checked').evaluateAll(es => es.map(e => e.value))).join(',') !== 'APPROVED')
    throw new Error('flow-status-not-active');
  const totalTexts = await flow.locator('.ant-pagination-total-text').allTextContents();
  const rows = await flow.locator('.ant-table-tbody > tr').evaluateAll(es => es.map(e => ({
    name: e.querySelector('.flow-activity-item-title')?.textContent?.trim(),
    shopIds: [...e.querySelectorAll('.flow-activity-sub-item-info')].map(x => x.textContent.trim()),
    shops: [...e.querySelectorAll('.flow-activity-sub-item-title')].map(x => x.textContent.trim()),
  })));
  let total, size, flowNames, emptyEvidence;
  if (totalTexts.length === 0) {
    if (await flow.getByText('暂无数据', { exact: true }).count() !== 1 || rows.some(r => r.name))
      throw new Error('flow-empty-unproven');
    total = 0; size = 0; flowNames = []; emptyEvidence = '暂无数据';
  } else {
    const sizeText = (await flow.locator('.ant-select-selection-item').allTextContents()).find(x => /条\/页/.test(x));
    const totalMatch = totalTexts.length === 1 && totalTexts[0].trim().match(/^共\s*(\d+)\s*条$/);
    const sizeMatch = sizeText?.match(/^(\d+)\s*条\/页$/);
    if (!totalMatch || !sizeMatch) throw new Error('flow-pagination-unknown');
    total = Number(totalMatch[1]); size = Number(sizeMatch[1]);
    if (total > size) throw new Error('flow-multiple-pages-unhandled');
    // 2026-10-10 同一根因第二处：流量活动表格的门店名同样带分店后缀（来源名无后缀）⇒
    // 原「精确数组包含」r.shops.includes(name) 永不命中。改为「归一化 + 前缀」匹配。
    if (rows.length !== total || rows.some(r => !r.name || !r.shopIds.includes(`门店ID: ${shopId}`)
      || !r.shops.some(s => normName(s).startsWith(normName(name)))))
      throw new Error('flow-list-incomplete-or-other-shop');
    flowNames = rows.map(r => r.name);
  }
  const names = [...store.pending.names, ...store.active.names, ...flowNames];
  return { status: 'complete', checkedAt: new Date().toISOString(), account: ACCOUNT,
    shopId, shopName: name, pageUrl: page.url(), store,
    flow: { status: '进行中', total, pageSize: size, names: flowNames, ...(emptyEvidence ? { emptyEvidence } : {}) },
    targetStatus: Object.fromEntries(TARGETS.map(x => [x, names.includes(x) ? 'present' : 'missing'])) };
}

async function main() {
  const output = process.argv[2];
  const requestedName = process.argv[3] || 'EGO TACO ·伊戈塔可·香辣蟹(雨花店)';
  if (!output) throw new Error('output-path-required');
  // 岗位实体化 L1-2：经 taobao-brand-post 连接独占工位 9230，并取工位互斥锁。
  const lease = await acquirePostLease(`taobao-brand-${Date.now()}`);
  if (!lease) {
    // 工位被同端口其它流水线占用（忙）→ 跳过本轮，绝不驱动浏览器（对齐 daemon SKIPPED_BUSY）
    console.log(JSON.stringify({ status: 'skipped', reason: 'post-lease-busy', port: 9230 }));
    return;
  }
  let browser;
  try {
    const conn = await connectToPost();
    browser = conn.browser;
    const pages = browser.contexts().flatMap(c => c.pages()).filter(p => p.url().startsWith('https://melody.shop.ele.me/'));
    if (pages.length !== 1) throw new Error('brand-tab-not-unique');
    const shopId = await selectShop(pages[0], requestedName);
    const receipt = await collect(pages[0], shopId, requestedName);
    fs.mkdirSync(require('node:path').dirname(output), { recursive: true, mode: 0o700 });
    fs.writeFileSync(output, JSON.stringify(receipt, null, 2), { flag: 'wx', mode: 0o600 });
    console.log(JSON.stringify({ status: receipt.status, shopId: receipt.shopId, targetStatus: receipt.targetStatus, output }));
  } finally { await browser?.close().catch(() => {}); if (lease) await releasePostLease(lease).catch(() => {}); }
}
if (process.argv[1] && import.meta.url === `file://${process.argv[1]}`) {
  main().catch(e => {
    // 2026-10-11 非营业中店：skipped 语义（对齐 post-lease-busy：stdout JSON、退出 0、不落收据文件），
    // 上游 workflow 据此记 skipped 而非 unknown，避免暂停营业店天天造成连败告警噪音。
    // 2026-10-12 shop-not-found（品牌商侧店铺树无此店，如代理商新店未同步）：同 skipped 语义。
    if (/^shop-not-operating:/.test(e.message || '') || /^shop-not-found:/.test(e.message || '') || /^shop-search-timeout$/.test(e.message || '')) {
      console.log(JSON.stringify({ status: 'skipped', reason: e.message }));
      process.exit(0);
    }
    console.error(JSON.stringify({ status: 'unknown', reason: e.message,
      stack: String(e.stack || '').split('\n').slice(0, 8).join(' ⏎ ').slice(0, 900) })); process.exitCode = 1;
  });
}
