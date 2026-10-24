#!/usr/bin/env node
// Read the existing signed-in taobao-brand shop tab. Never creates a browser tab.
// 2026-10-12 大同指定开发：新店装修审计（顶部招牌/店内海报「已配置」徽标检查）。
// 选店/弹窗消解/skip 语义从 activity_collector.mjs 完整复刻（均经实战验证）。
import { createRequire } from 'node:module';
import { connectToPost } from '../../../posts/taobao-brand-post/scripts/connect.mjs';
import { acquirePostLease, releasePostLease } from '../../../posts/taobao-brand-post/scripts/lease.mjs';
import { assertAuthenticated } from '../../../posts/taobao-brand-post/scripts/auth.mjs';
const require = createRequire(import.meta.url);
const fs = require('node:fs');

const ACCOUNT = 'gmfmmZH';
// 巡检组件与模版别名（2026-10-12 实证：行业通用模版叫「顶部招牌」，匠心品质模版叫「门店招牌」，
// 语义相同均为店招；不同模版组件集合可能不同，card-not-found 按 missing 处理=未配置，fail-closed 向报警）。
const COMPONENTS = [
  { key: '顶部招牌', aliases: ['顶部招牌', '门店招牌'] },
  { key: '店内海报', aliases: ['店内海报'] },
  { key: '门店头像', aliases: ['门店头像'] },
  { key: '店内橱窗', aliases: ['店内橱窗'] },
];

// 2026-10-10 站点显示差异：店名在「来源 / 头部 / 下拉 / 流量表格」各处可能带或不带分店后缀，
// 且站点会在店名与后缀/状态之间插入换行或空格。统一用「去空白 + 前缀」判同店，避免精确相等漏判。
const normName = (s) => String(s ?? '').replace(/\s+/g, '');

export async function enterShopFromResult(li) {
  const name = li.locator('span[class^="itemShopName__"]');
  if (await name.count() !== 1) throw new Error('shop-entry-name-not-unique');
  // Click the visible name container; the name span is covered by a tooltip mask.
  await li.locator('div[class^="itemShopNameContainer__"]').click({ timeout: 5000 });
}

export function shopSearchResultsSettled(want) {
  const rows = [...document.querySelectorAll('li.cook-cascader-menu-item')]
    .filter(el => el.getBoundingClientRect().width > 0 && el.getBoundingClientRect().height > 0);
  return rows.length > 0 && rows.every(el => (el.innerText || '').replace(/\s+/g, '').includes(want));
}

// Header selection does not navigate the current SPA route; use the existing home menu.
export async function settleSelectedShopRoute(page, targetId) {
  if (!targetId) throw new Error('selected-shop-id-missing');
  if (!page.url().includes(`/app/shop/${targetId}/`)) {
    const home = page.getByText('商家首页', { exact: true });
    if (await home.count() !== 1) throw new Error('shop-home-menu-not-unique');
    await home.click({ timeout: 5000 });
  }
  await page.waitForFunction(id => location.href.includes(`/app/shop/${id}/`), targetId, { timeout: 15000 });
}

// 2026-10-10 根因修复：品牌商后台会弹出「绑定手机号提醒」ant-modal，覆盖在搜索框之上，
// 导致 selectShop 的 fill(搜索框) 被拦截、整条巡检流连败。selectShop 进入前先消解该
// 模态（点「跳过」），模态不可见即跳过；消解失败也不抛错，让后续点击自行暴露真实拦截（fail-closed）。
// 2026-10-11 第二代组件库加固：站点弹窗存在 cook-modal-wrap 变体，统一兼容两代 wrap；
// 按钮优先中性动作（跳过/知道了/确认），找不到再点关闭 X。仅消解提示类弹窗，不做任何表单提交。
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

// 选店逻辑与 activity_collector.mjs 完全一致（同岗位同站点同站点行为），
// 含 2026-10-10~12 全部加固：前缀判同店、下拉复用、shop-not-found / shop-not-operating /
// shop-search-timeout skip 语义、跨店回切精确等 URL。
async function selectShop(page, requestedName) {
  assertAuthenticated(page.url());
  await ensureShopSelectorReady(page);
  await dismissBindModal(page);
  const current = page.locator('span[class^="shop-name__"]').first();
  // 2026-10-12 dry-run 实况：chain home 页顶部店名恰为目标店时（默认店），原逻辑跳过搜索，
  // 但 URL 仍在 chain 页（非 /app/shop/{id}/）⇒ waitForFunction 超时。跳过搜索的前提是
  // 「已在目标店的 shop 域页面」；否则（含 chain 页默认店）一律走搜索选店。
  const onShopDomain = /\/app\/shop\/\d+\//.test(page.url());
  const alreadyThere = onShopDomain && normName(await current.innerText()).startsWith(normName(requestedName));
  if (!alreadyThere) {
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
    const li = page.locator('li.cook-cascader-menu-item', { hasText: requestedName }).first();
    try {
      await li.waitFor({ timeout: 8000 });
    } catch {
      const emptyLi = page.locator('li.cook-cascader-menu-item').filter({ hasText: '未搜索到店铺' }).first();
      if (await emptyLi.isVisible().catch(() => false)) throw new Error('shop-not-found:未搜索到店铺');
      throw new Error('shop-search-timeout');
    }
    // The old full tree still contains the target during debounced search.
    // Do not click it before the filtered result has replaced that tree.
    await page.waitForFunction(shopSearchResultsSettled, normName(requestedName), { timeout: 8000 });
    await waitSpinnerGone(page);
    const dataValue = await li.getAttribute('data-value').catch(() => null);
    const targetId = dataValue?.match(/SHOP:(\d+)/)?.[1];
    const liText = (await li.innerText().catch(() => '')).replace(/\s+/g, '');
    const offState = ['已下线', '暂停营业'].find(st => liText.includes(st));
    if (offState) throw new Error(`shop-not-operating:${offState}`);
    const prevUrl = page.url();
    const chosenHtml = (await li.evaluate(el=>el.outerHTML).catch(()=>'' )).slice(0,4000);
    await enterShopFromResult(li);
    const selectionEvidence = await page.evaluate(() => ({
      notices: [...document.querySelectorAll('.ant-message, .cook-message, .ant-notification, .cook-notification, .ant-modal-wrap, .cook-modal-wrap')]
        .filter(el=>el.offsetParent!==null).map(el=>el.innerText).filter(Boolean),
    }));
    selectionEvidence.chosenHtml = chosenHtml;
    process.stderr.write(`[selection-evidence] ${JSON.stringify({requestedName,targetId,...selectionEvidence})}\n`);
    const waitSettled = async () => {
      await page.waitForFunction(
        (want) => {
          const t = document.querySelector('span[class^="shop-name__"]')?.innerText || '';
          return !!t && t.replace(/\s+/g, '').startsWith(want);
        },
        normName(requestedName), { timeout: 15000 },
      );
      await settleSelectedShopRoute(page, targetId);
    };
    try {
      await waitSettled();
    } catch {
      await page.reload({ waitUntil: 'domcontentloaded', timeout: 30000 });
      try { await waitSettled(); }
      catch (error) {
        const heading = await page.locator('span[class^="shop-name__"]').first().innerText().catch(()=>'');
        throw new Error(`shop-selection-not-settled:${JSON.stringify({requestedName,targetId,chosenText:liText,currentUrl:page.url(),heading,reason:String(error.message||error)})}`);
      }
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
  return shopId;
}

// 2026-10-09 根因修复：cook-spin 加载动画在数据加载窗口盖住点击目标，点击前统一等 spinner 消失。
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

// 切店控件被全页加载态禁用时，先恢复同一页；不绕过遮罩点击。
export async function ensureShopSelectorReady(page, timeoutMs = 20000) {
  assertAuthenticated(page.url());
  if (await waitSpinnerGone(page, timeoutMs)) return { reloaded: false };
  await page.reload({ waitUntil: 'domcontentloaded', timeout: 30000 });
  assertAuthenticated(page.url());
  if (!await waitSpinnerGone(page, timeoutMs)) throw new Error('shop-selector-loading-timeout');
  return { reloaded: true };
}

// ===== 装修页 DOM 校准常量（2026-10-12 现场探查实证钉死）=====
// 页面路径（实证）：shop 域 → 左侧菜单先点「门店管理」展开子菜单 → 点「门店装修」→
//   /app/shop/{id}/decorate → 主 frame 只有菜单，内容在 iframe(r.ele.me/melody-decorate-pc) →
//   iframe 内先关「门店装修升级啦」推广弹窗(.index_close__V-lf9) → 基础模版区 →
//   已应用模版卡片的按钮（文本「已应用，编辑此模板」= button.cook-deco-themes-btn）→
//   iframe 跳转 #/single/template-config → 右侧组件面板 [class*=moduleItem]。
// ⚠ deep-link /app/shop/{id}/decorate 会 302 /login，必须从 shop 域内菜单进入（SPA 导航）。
// ⚠ 「编辑此模板」按钮视觉 click 超时（遮挡/重渲染），须 dispatchEvent('click') JS 级点击。
// ⚠ 「去配置」按钮在已配置的店也存在（图3 店内海报）⇒ 判据只认「已配置」徽标，不认按钮。
const DECOR_PARENT_MENU_TEXT = '门店管理';      // 父菜单（子菜单折叠，必须先点开）
const DECOR_MENU_TEXT = '门店装修';             // 子菜单项
const EDIT_TEMPLATE_TEXT = '编辑此模板';        // 已应用卡按钮文本（实证为「已应用，编辑此模板」）
const APPLIED_MARK_TEXT = '已应用';             // fail-closed：按钮附近必须含「已应用」标记
const CONFIGURED_BADGE_TEXT = '已配置';         // 组件卡片徽标（图3 实证）
const DECORATE_IFRAME = 'melody-decorate-pc';   // 装修页内容 iframe 域名特征

// 取装修页内容 iframe（主 frame 只有左侧菜单）
function decorateFrame(page) {
  return page.frames().find(f => f.url().includes(DECORATE_IFRAME)) || null;
}

// 关「门店装修升级啦」推广弹窗（iframe 内 X，实证 class index_close__V-lf9）
async function dismissUpgradeModal(frame) {
  await frame.evaluate(() => {
    for (const sel of ['.index_close__V-lf9', '[class*=close]']) {
      const x = document.querySelector(sel);
      if (x) { x.click(); return; }
    }
  }).catch(() => {});
}

// 组件徽标判据（纯 DOM 函数，浏览器上下文执行；抽离以便离线正负对照复用同一份逻辑）。
// ★ 2026-10-12 大同纠错实证：「已配置」徽标是 44×20 橙色 svg **图片**（class 含 moduleIcon），
//   DOM 内无任何文本 ⇒ 旧版「文本=已配置」扫描必然全报 missing（已发 4 条消息受此污染）。
//   「去配置」按钮在未配置卡与已配置选中卡都会出现，**不能作判据**；
//   「新组件」标签（class 含 newTag）= 刚上架未配置 ⇒ missing。
//   卡片不存在该组件（如品牌故事）⇒ missing（fail-closed 向报警）。
export function readComponentBadges({ comps }) {
  const out = {};
  for (const comp of comps) {
    let card = null;
    for (const alias of comp.aliases) {
      for (const t of document.querySelectorAll('[class*=moduleTitle]')) {
        if ((t.textContent || '').replace(/\s+/g, '') === alias) {
          card = t.closest('[class*=moduleItem]') || t.parentElement;
          break;
        }
      }
      if (card) break;
    }
    if (!card) { out[comp.key] = 'missing'; continue; }
    const configured = [...card.querySelectorAll('img')]
      .some(i => /moduleIcon/.test(String(i.className)) && !/newTag/.test(String(i.className)));
    out[comp.key] = configured ? 'configured' : 'missing';
  }
  return out;
}

// 门店装修页读取：菜单进入 → 关升级弹窗 → 已应用模版「编辑此模板」→ 读两组件的「已配置」徽标。
export async function readDecoration(page, shopId, name) {
  // 1) 左侧菜单：先展开「门店管理」，再点「门店装修」（实证：子菜单折叠，直接点找不到）
  const header = await page.locator('body').first().innerText();
  if (!header.includes(ACCOUNT) || !header.includes(name)) throw new Error('shop-or-account-mismatch');
  const parentMenu = page.locator('a, li, div, span').filter({ hasText: new RegExp(`^${DECOR_PARENT_MENU_TEXT}$`) }).first();
  if (await parentMenu.count()) {
    await parentMenu.click({ timeout: 8000 }).catch(() => {});
    await page.waitForTimeout(1500);
  }
  const decorMenu = page.locator('a, li, div, span').filter({ hasText: new RegExp(`^${DECOR_MENU_TEXT}$`) }).first();
  if (!(await decorMenu.count())) throw new Error('decoration-menu-not-found');
  await decorMenu.click({ timeout: 8000 });
  await page.waitForFunction(() => location.href.includes('/decorate'), null, { timeout: 15000 });
  await waitSpinnerGone(page);
  // 等装修 iframe 出现（内容全在 iframe，主 frame 只有菜单）
  let frame = null;
  for (let i = 0; i < 20; i++) {
    frame = decorateFrame(page);
    if (frame) break;
    await page.waitForTimeout(500);
  }
  if (!frame) throw new Error('decoration-iframe-not-found');

  // 2) 关升级推广弹窗 + 定位模版区/编辑页（双状态：iframe 可能已在 template-config 残留态）
  await page.waitForTimeout(2000);
  await dismissUpgradeModal(frame);
  await page.waitForTimeout(2000);
  let cfgFrame = null;
  if (frame.url().includes('template-config')) {
    // 残留编辑页态（上次运行/探针留下）：直接用，等组件面板渲染
    for (let i = 0; i < 20; i++) {
      const ok = await frame.evaluate(() => !!document.querySelector('[class*=moduleItem]')).catch(() => false);
      if (ok) { cfgFrame = frame; break; }
      await page.waitForTimeout(1000);
    }
    if (!cfgFrame) throw new Error('decoration-component-panel-not-rendered');
  } else {
    // template-home 态：找「已应用，编辑此模板」按钮并 JS 级点击
    const editBtn = frame.locator('button.cook-deco-themes-btn', { hasText: new RegExp(EDIT_TEMPLATE_TEXT) }).first();
    let btnReady = false;
    for (let i = 0; i < 20; i++) {
      if (await editBtn.count().catch(() => 0)) { btnReady = true; break; }
      await dismissUpgradeModal(frame).catch(() => {});
      await page.waitForTimeout(1000);
    }
    if (!btnReady) throw new Error('decoration-edit-button-not-found');
    // fail-closed：按钮文本必须含「已应用」（证明找的是生效中的模版卡，不是未应用模版）
    const btnText = ((await editBtn.innerText().catch(() => '')) || '').replace(/\s+/g, '');
    if (!btnText.includes(APPLIED_MARK_TEXT)) throw new Error('decoration-applied-template-unproven');
    // 视觉 click 超时（遮挡/重渲染）⇒ JS 级点击（cook 组件监听真实 click 事件）
    await editBtn.scrollIntoViewIfNeeded().catch(() => {});
    await page.waitForTimeout(500);
    await editBtn.dispatchEvent('click');
    // 等 iframe 跳转到 template-config + 组件面板渲染
    for (let i = 0; i < 30; i++) {
      await page.waitForTimeout(1000);
      const f2 = decorateFrame(page);
      if (f2 && f2.url().includes('template-config')) {
        const has = await f2.evaluate(() => !!document.querySelector('[class*=moduleItem]')).catch(() => false);
        if (has) { cfgFrame = f2; break; }
      }
    }
    if (!cfgFrame) throw new Error('decoration-config-page-not-reached');
  }

  // 4) 读两个组件的「已配置」徽标（textContent 全文扫描——innerText 会漏遮罩/弹罩内文本）
  const components = await cfgFrame.evaluate(readComponentBadges, { comps: COMPONENTS });

  // 现场取证钩子（仅 env DECOR_DUMP_PATH 打开时）：把组件卡真实 DOM + 伪元素 content
  // 落盘，用于核对徽标形态（大同 2026-10-12 质疑「已配置」识别不准时的定性依据）。
  if (process.env.DECOR_DUMP_PATH) {
    const dump = await cfgFrame.evaluate(() => {
      const titles = [...document.querySelectorAll('[class*=moduleTitle]')]
        .map(t => (t.textContent || '').replace(/\s+/g, ''));
      const cards = [];
      for (const t of document.querySelectorAll('[class*=moduleTitle]')) {
        const card = t.closest('[class*=moduleItem]') || t.parentElement;
        if (!card) continue;
        const nodes = [];
        for (const el of card.querySelectorAll('*')) {
          const txt = (el.textContent || '').replace(/\s+/g, '');
          const before = (getComputedStyle(el, '::before').content || '').replace(/"/g, '');
          const after = (getComputedStyle(el, '::after').content || '').replace(/"/g, '');
          if (txt.includes('配置') || before.includes('配置') || after.includes('配置')) {
            nodes.push({
              tag: el.tagName, cls: String(el.className || '').slice(0, 80),
              children: el.children.length, text: txt.slice(0, 40),
              before: before.slice(0, 40), after: after.slice(0, 40),
              html: (el.outerHTML || '').slice(0, 300),
            });
          }
        }
        cards.push({
          title: (t.textContent || '').replace(/\s+/g, ''),
          innerText: (card.innerText || '').replace(/\n+/g, ' | ').slice(0, 300),
          html: (card.outerHTML || '').slice(0, 2500),
          configNodes: nodes,
        });
      }
      return { titles, cards, bodyHasBadge: (document.body.innerText || '').includes('已配置') };
    }).catch(e => ({ error: String(e.message).slice(0, 200) }));
    fs.writeFileSync(process.env.DECOR_DUMP_PATH, JSON.stringify({ shop: name, shopId, components, ...dump }, null, 2));
  }

  return {
    status: 'complete', checkedAt: new Date().toISOString(), account: ACCOUNT,
    shopId, shopName: name, pageUrl: page.url(),
    components, targetStatus: components,
  };
}

// 显式退出 + 冲刷：CDP 连接句柄使事件循环非空，node 不会自行退出。
function flushExit(code, payload, stream = 'stdout') {
  const line = JSON.stringify(payload) + '\n';
  const done = () => process.exit(code);
  if (stream === 'stderr') process.stderr.write(line, done);
  else process.stdout.write(line, done);
}

async function main() {
  const output = process.argv[2];
  const requestedName = process.argv[3];
  if (!output) throw new Error('output-path-required');
  if (!requestedName) throw new Error('shop-name-required');
  // 岗位实体化 L1-2：经 taobao-brand-post 连接独占工位 9230，并取工位互斥锁。
  const lease = await acquirePostLease(`taobao-brand-${Date.now()}`);
  if (!lease) {
    // 工位被同端口其它流水线占用（忙）→ 跳过本轮，绝不驱动浏览器（对齐 daemon SKIPPED_BUSY）
    console.log(JSON.stringify({ status: 'skipped', reason: 'post-lease-busy', port: 9230 }));
    return;
  }
  let browser;
  let payload = null;
  try {
    process.stderr.write(`[dryrun] ${new Date().toISOString()} acquiring lease...\n`);
    const conn = await connectToPost();
    process.stderr.write(`[dryrun] connected\n`);
    browser = conn.browser;
    const pages = browser.contexts().flatMap(c => c.pages()).filter(p => p.url().startsWith('https://melody.shop.ele.me/'));
    process.stderr.write(`[dryrun] melody pages: ${pages.length} url=${pages[0]?.url?.().slice(0, 80)}\n`);
    if (pages.length !== 1) throw new Error('brand-tab-not-unique');
    const shopId = await selectShop(pages[0], requestedName);
    process.stderr.write(`[dryrun] selectShop ok: ${shopId}\n`);
    const receipt = await readDecoration(pages[0], shopId, requestedName);
    process.stderr.write(`[dryrun] readDecoration ok: ${JSON.stringify(receipt.targetStatus)}\n`);
    fs.mkdirSync(require('node:path').dirname(output), { recursive: true, mode: 0o700 });
    fs.writeFileSync(output, JSON.stringify(receipt, null, 2), { flag: 'wx', mode: 0o600 });
    payload = { status: receipt.status, shopId: receipt.shopId, targetStatus: receipt.targetStatus, output };
  } finally {
    // 严禁 browser.close()：connectOverCDP 的 close 会杀掉整个 9230 岗位实例。只释放 lease。
    if (lease) await releasePostLease(lease).catch(() => {});
  }
  // 2026-10-12 根因修复：不 close 浏览器 ⇒ CDP WebSocket 句柄保持事件循环非空 ⇒
  //   node 永不自行退出，上层 subprocess(timeout=120) 把「已成功落盘」误判成超时 unknown
  //   （当日 19:46/19:53 两轮均为此形状：collection.json 已写、进程仍挂着）。
  //   收尾必须显式退出，并用 write 回调确保 stdout 冲刷后再 exit。
  if (payload) flushExit(0, payload);
}
if (process.argv[1] && import.meta.url === `file://${process.argv[1]}`) {
  main().catch(e => {
    // 与 activity_collector 对齐的 skipped 语义：非营业中店 / 店铺树无此店 / 搜索空态超时 /
    // 工位忙均为业务或工位数据缺口，stdout JSON + 退出 0，上游记 skipped 不算 unknown。
    if (/^shop-not-operating:/.test(e.message || '') || /^shop-not-found:/.test(e.message || '') || /^shop-search-timeout$/.test(e.message || '')) {
      flushExit(0, { status: 'skipped', reason: e.message });
    }
    flushExit(1, { status: 'unknown', reason: e.message,
      stack: String(e.stack || '').split('\n').slice(0, 8).join(' ⏎ ').slice(0, 900) }, 'stderr');
  });
}
