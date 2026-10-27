import { execFile as execFileCallback } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { promisify } from "node:util";

function rejectLegacyExecution() {
  throw new Error('legacy-executor-disabled-use-installed-entrypoint');
}

const execFile = promisify(execFileCallback);
const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const OCR_BIN = path.join(SCRIPT_DIR, "ocr_vision");
const APP = "com.google.Chrome";
const MERCHANT_CHAIN = "95708808";
const MERCHANT_HOME_URL = `https://melody.shop.ele.me/app/chain/${MERCHANT_CHAIN}/dashboard#app.chainshop.dashboard`;

function elementId(line, role) {
  const match = line?.match(new RegExp(`(\\d+) ${role}`));
  return match ? Number(match[1]) : null;
}

function findLine(text, predicate) {
  return text.split("\n").find(predicate) ?? null;
}

export function yesterdayInShanghai(now = new Date()) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit",
  }).formatToParts(now);
  const value = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  const utc = new Date(`${value.year}-${value.month}-${value.day}T00:00:00+08:00`);
  utc.setUTCDate(utc.getUTCDate() - 1);
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit",
  }).format(utc);
}

function reportPrefix(type) {
  if (type === "store") return "门店下载";
  if (type === "review") return "评价下载";
  throw new Error(`unsupported-report-type:${type}`);
}

export function sourceReportPattern(type, businessDate) {
  const compact = businessDate.replaceAll("-", "");
  const prefix = reportPrefix(type);
  return new RegExp(`^${prefix}_${compact}至${compact}_全部门店_\\d+_\\d{17}(?: \\(\\d+\\))?\\.xlsx$`);
}

export function reportPattern(type, businessDate) {
  const compact = businessDate.replaceAll("-", "");
  const prefix = reportPrefix(type);
  return new RegExp(`^${prefix}_${compact}_全部门店_\\d+_\\d{17}(?: \\(\\d+\\))?\\.xlsx$`);
}

export function normalizedReportName(type, businessDate, sourceName) {
  if (!sourceReportPattern(type, businessDate).test(sourceName)) throw new Error(`${type}-source-filename-contract-failed`);
  const compact = businessDate.replaceAll("-", "");
  return sourceName.replace(`${reportPrefix(type)}_${compact}至${compact}_`, `${reportPrefix(type)}_${compact}_`);
}

export function targetEntry(type) {
  if (type === "store") return "数据上传";
  if (type === "review") return "评价上传";
  throw new Error(`unsupported-report-type:${type}`);
}

async function pollState(sky, predicate, timeoutMs, intervalMs = 180) {
  const deadline = performance.now() + timeoutMs;
  let latest = null;
  do {
    latest = await sky.get_app_state({ app: APP, disableDiff: true });
    if (predicate(latest.text)) return latest;
    if (performance.now() >= deadline) break;
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  } while (true);
  return latest;
}

function stageTimer(receipt, name) {
  const started = performance.now();
  receipt.stage = name;
  receipt.stageStarted = started;
  return () => {
    receipt.stageMs[name] = Math.round(performance.now() - started);
    delete receipt.stageStarted;
  };
}

async function ocrEntries(file) {
  const { stdout } = await execFile(OCR_BIN, [file, "zh-Hans"], { maxBuffer: 4 * 1024 * 1024 });
  return stdout.split("\n").flatMap((line) => {
    const [box, confidence, text] = line.split("\t", 3);
    if (!box || !text) return [];
    const [x, y, width, height] = box.split(",").map(Number);
    return [{ x, y, width, height, confidence: Number(confidence), text: text.trim() }];
  });
}

async function clickOcrExact(sky, state, expected, { semanticFirst = true } = {}) {
  const semantic = state.text.split("\n").filter((line) => new RegExp(`^\\s*\\d+ 文本 ${expected}$`).test(line));
  if (semanticFirst && semantic.length === 1) {
    await sky.click({ app: APP, element_index: elementId(semantic[0], "文本") });
    return;
  }
  if (/^\s*0 .*Secondary Actions: Raise/m.test(state.text)) {
    await sky.perform_secondary_action({ app: APP, element_index: 0, action: "Raise" });
    state = await sky.get_app_state({ app: APP, disableDiff: true });
  }
  if (!state?.screenshot && sky.get_screenshot_state) state = await sky.get_screenshot_state({ app: APP, disableDiff: true });
  if (!state?.screenshot) throw new Error(`screenshot-missing-for:${expected}`);
  const entries = await ocrEntries(fileURLToPath(state.screenshot.url));
  const matches = entries.filter((entry) => entry.text.replaceAll(" ", "") === expected.replaceAll(" ", ""));
  if (matches.length !== 1) throw new Error(`ocr-target-count:${expected}:${matches.length}`);
  await sky.click({ app: APP, x: matches[0].x, y: matches[0].y });
}

export function scopedSubmenuItemId(text, heading, item) {
  const lines = text.split("\n");
  const matches = [];
  for (let index = 0; index < lines.length; index += 1) {
    const headingMatch = lines[index].match(new RegExp(`^(\\s*)\\d+ 文本 ${heading}$`));
    if (!headingMatch) continue;
    const baseIndent = headingMatch[1].length;
    let menuSeen = false;
    for (let cursor = index + 1; cursor < lines.length; cursor += 1) {
      const indent = lines[cursor].match(/^\s*/)?.[0].length ?? 0;
      if (indent <= baseIndent) break;
      if (/^\s*\d+ 菜单(?: |$)/.test(lines[cursor])) menuSeen = true;
      if (menuSeen && new RegExp(`^\\s*\\d+ ${item}$`).test(lines[cursor])) matches.push(elementId(lines[cursor], item));
    }
  }
  const unique = [...new Set(matches.filter(Number.isFinite))];
  return unique.length === 1 ? unique[0] : null;
}

export function scopedSubmenuTextId(text, heading, item) {
  const parent = scopedSubmenuItemId(text, heading, item);
  if (parent == null) return null;
  const lines = text.split("\n");
  const parentIndex = lines.findIndex((line) => new RegExp(`^\\s*${parent} ${item}$`).test(line));
  if (parentIndex < 0) return null;
  const parentIndent = lines[parentIndex].match(/^\s*/)?.[0].length ?? 0;
  for (let index = parentIndex + 1; index < lines.length; index += 1) {
    const indent = lines[index].match(/^\s*/)?.[0].length ?? 0;
    if (indent <= parentIndent) break;
    if (new RegExp(`^\\s*\\d+ 文本 ${item}$`).test(lines[index])) return elementId(lines[index], "文本");
  }
  return null;
}

export function mainMenuTextId(text, item) {
  const lines = text.split("\n");
  for (let index = 0; index < lines.length; index += 1) {
    const menu = lines[index].match(/^(\s*)\d+ 菜单 Secondary Actions: Cancel$/);
    if (!menu) continue;
    const baseIndent = menu[1].length;
    const block = [];
    for (let cursor = index + 1; cursor < lines.length; cursor += 1) {
      const indent = lines[cursor].match(/^\s*/)?.[0].length ?? 0;
      if (indent <= baseIndent) break;
      block.push(lines[cursor]);
    }
    const joined = block.join("\n");
    if (!["商家首页", "财务管理", "安全中心"].every((token) => joined.includes(token))) continue;
    const matches = block.filter((line) => new RegExp(`^\\s*\\d+ 文本 ${item}$`).test(line));
    if (matches.length === 1) return elementId(matches[0], "文本");
  }
  return null;
}

export function globalSearchFunctionResultId(text, expected) {
  if (!text.split("\n").some((line) => new RegExp(`^\\s*\\d+ 文本栏 \\(settable\\) Value: ${expected}, Placeholder: 搜功能、订单`).test(line))) return null;
  const lines = text.split("\n");
  const matches = [];
  for (let index = 0; index < lines.length; index += 1) {
    const container = lines[index].match(/^(\s*)\d+ container 综合$/);
    if (!container) continue;
    const baseIndent = container[1].length;
    let functionGroupSeen = false;
    for (let cursor = index + 1; cursor < lines.length; cursor += 1) {
      const indent = lines[cursor].match(/^\s*/)?.[0].length ?? 0;
      if (indent <= baseIndent) break;
      if (/^\s*\d+ 文本 功能$/.test(lines[cursor])) {
        functionGroupSeen = true;
        continue;
      }
      if (functionGroupSeen && /^\s*\d+ 文本 (?:订单|帮助|课程)$/.test(lines[cursor])) break;
      if (functionGroupSeen && new RegExp(`^\\s*\\d+ 文本 ${expected}$`).test(lines[cursor])) {
        matches.push(elementId(lines[cursor], "文本"));
      }
    }
  }
  const unique = [...new Set(matches.filter(Number.isFinite))];
  return unique.length === 1 ? unique[0] : null;
}

export function globalSearchCloseButtonId(text) {
  const lines = text.split("\n");
  const fieldIndex = lines.findIndex((line) => /^\s*\d+ 文本栏 \(settable\) Value: .+, Placeholder: 搜功能、订单/.test(line));
  if (fieldIndex < 0) return null;
  const fieldIndent = lines[fieldIndex].match(/^\s*/)?.[0].length ?? 0;
  for (let index = fieldIndex + 1; index < lines.length; index += 1) {
    const indent = lines[index].match(/^\s*/)?.[0].length ?? 0;
    if (indent < fieldIndent) break;
    const match = lines[index].match(/^\s*(\d+) 按钮 close-circle$/);
    if (match && indent === fieldIndent) return Number(match[1]);
  }
  return null;
}

export function merchantDirectDownloadMenuId(text) {
  const lines = text.split("\n");
  const title = lines[0] ?? "";
  if (!title.includes("淘宝闪购商家版") || !title.includes("App: Google Chrome")) return null;
  if (!lines.some((line) => /^\s*\d+ 菜单 Secondary Actions: Cancel$/.test(line))) return null;
  const matches = lines.filter((line) => /^\s*\d+ 数据下载$/.test(line));
  if (matches.length !== 1) return null;
  const parentIndex = lines.indexOf(matches[0]);
  const parentIndent = matches[0].match(/^\s*/)?.[0].length ?? 0;
  const childMatches = [];
  for (let index = parentIndex + 1; index < lines.length; index += 1) {
    const indent = lines[index].match(/^\s*/)?.[0].length ?? 0;
    if (indent <= parentIndent) break;
    if (/^\s*\d+ 文本 数据下载$/.test(lines[index])) childMatches.push(lines[index]);
  }
  if (childMatches.length > 1) return null;
  return childMatches.length === 1
    ? elementId(childMatches[0], "文本")
    : elementId(matches[0], "数据下载");
}

export function downloadCenterSubmenuId(text) {
  return scopedSubmenuTextId(text, "数据中心", "数据下载")
    ?? scopedSubmenuItemId(text, "数据中心", "数据下载")
    ?? merchantDirectDownloadMenuId(text);
}

export function merchantDownloadCenterTarget(text) {
  const title = text.split("\n")[0] ?? "";
  if (!title.includes("淘宝闪购商家版") || !title.includes("App: Google Chrome")) return null;
  const matches = text.split("\n").filter((line) =>
    /^\s*\d+ 文本栏 \(settable\) Description: 地址和搜索栏, Value: (?:https:\/\/)?melody\.shop\.ele\.me\/app\/chain\/\d+\//.test(line));
  if (matches.length !== 1) return null;
  const chain = matches[0].match(/melody\.shop\.ele\.me\/app\/chain\/(\d+)\//)?.[1];
  const id = elementId(matches[0], "文本栏");
  if (!chain || id == null) return null;
  return {
    id,
    chain,
    homeUrl: `https://melody.shop.ele.me/app/chain/${chain}/dashboard#app.chainshop.dashboard`,
    url: `https://melody.shop.ele.me/app/chain/${chain}/downloadCenter#app.chainshop.downloadCenter`,
  };
}

export function isMerchantHomeState(text, chain = MERCHANT_CHAIN) {
  const title = text.split("\n")[0] ?? "";
  return title.includes("淘宝闪购商家版")
    && title.includes("App: Google Chrome")
    && text.includes(`melody.shop.ele.me/app/chain/${chain}/dashboard`)
    && text.includes("商家首页");
}

export function isMerchantDownloadCenterState(text, chain = MERCHANT_CHAIN) {
  const title = text.split("\n")[0] ?? "";
  return title.includes("淘宝闪购商家版")
    && title.includes("App: Google Chrome")
    && text.includes(`melody.shop.ele.me/app/chain/${chain}/downloadCenter`);
}

export function isMerchantMenuOnlyState(text) {
  const title = text.split("\n")[0] ?? "";
  return title.includes("淘宝闪购商家版")
    && title.includes("App: Google Chrome")
    && /^\s*0 菜单 Secondary Actions: Cancel$/m.test(text)
    && /^\s*\d+ 商家首页$/m.test(text)
    && /^\s*\d+ 数据中心$/m.test(text)
    && !text.includes("地址和搜索栏");
}

async function dismissMerchantMenuOnly(sky, state) {
  if (!isMerchantMenuOnlyState(state.text)) return state;
  if (typeof sky.refresh_app_binding === "function" && await sky.refresh_app_binding({ app: APP })) {
    const refreshed = await sky.get_app_state({ app: APP, disableDiff: true });
    if (!isMerchantMenuOnlyState(refreshed.text)) return refreshed;
    state = refreshed;
  }
  await sky.perform_secondary_action({ app: APP, element_index: 0, action: "Cancel" });
  return pollState(sky, (text) => merchantDownloadCenterTarget(text) != null, 4_000) ?? state;
}

async function clickExactText(sky, state, expected) {
  const lines = state.text.split("\n").filter((line) => new RegExp(`^\\s*\\d+ 文本 ${expected}$`).test(line));
  if (lines.length !== 1) throw new Error(`text-target-count:${expected}:${lines.length}`);
  await sky.click({ app: APP, element_index: elementId(lines[0], "文本") });
}

function fullscreenMenuStatus(text) {
  if (/^\s*\d+ 退出全屏幕(?:,|$)/m.test(text)) return "fullscreen";
  if (/^\s*\d+ 进入全屏幕(?:,|$)/m.test(text)) return "windowed";
  return "unknown";
}

async function closeChromeMenu(sky, state) {
  if (!/^\s*0 显示(?:,|$)/m.test(state.text)) return state;
  await sky.perform_secondary_action({ app: APP, element_index: 0, action: "Cancel" });
  const page = await pollState(sky, (text) => /URL: .*melody\.shop\.ele\.me/.test(text), 2_000);
  if (!page || /^\s*0 显示(?:,|$)/m.test(page.text)) throw new Error("chrome-menu-not-closed");
  return page;
}

async function openViewMenu(sky, state) {
  const line = findLine(state.text, (value) => /^\s*\d+ 显示$/.test(value));
  const id = Number(line?.match(/(\d+) 显示$/)?.[1]);
  if (!Number.isFinite(id)) return null;
  await sky.click({ app: APP, element_index: id });
  return sky.get_app_state({ app: APP, disableDiff: true });
}

async function ensureChromeFullscreen(sky, state) {
  state = await closeChromeMenu(sky, state);
  let menu = await openViewMenu(sky, state);
  if (menu == null) return state;
  let status = fullscreenMenuStatus(menu.text);
  if (status === "windowed") {
    const line = findLine(menu.text, (value) => /^\s*\d+ 进入全屏幕(?:,|$)/.test(value));
    const id = Number(line?.match(/(\d+) 进入全屏幕/)?.[1]);
    if (!Number.isFinite(id)) throw new Error("chrome-enter-fullscreen-not-found");
    await sky.click({ app: APP, element_index: id });
    await new Promise((resolve) => setTimeout(resolve, 700));
    state = await sky.get_app_state({ app: APP, disableDiff: true });
    menu = await openViewMenu(sky, state);
    if (menu == null) return state;
    status = fullscreenMenuStatus(menu.text);
  }
  if (status !== "fullscreen") throw new Error(`chrome-fullscreen-not-verified:${status}`);
  return closeChromeMenu(sky, menu);
}

async function selectTaobaoTab(sky, state) {
  if (isMerchantDownloadCenterState(state.text)) return state;
  state = await dismissMerchantMenuOnly(sky, state);
  if (isMerchantDownloadCenterState(state.text)) return state;
  let addressTarget = merchantDownloadCenterTarget(state.text);
  if (addressTarget == null && merchantDirectDownloadMenuId(state.text) != null) {
    await sky.perform_secondary_action({ app: APP, element_index: 0, action: "Cancel" });
    state = await pollState(sky, (text) => merchantDownloadCenterTarget(text) != null, 2_500) ?? state;
    addressTarget = merchantDownloadCenterTarget(state.text);
  }
  if (addressTarget == null) {
    const line = findLine(state.text, (value) => /标签 .*Description: 淘宝闪购商家版/.test(value));
    const id = elementId(line, "标签");
    if (id == null) throw new Error("taobao-tab-not-found");
    await sky.click({ app: APP, element_index: id });
    state = await pollState(sky, (text) => merchantDownloadCenterTarget(text) != null, 4_000) ?? state;
    addressTarget = merchantDownloadCenterTarget(state.text);
  }
  if (addressTarget == null) throw new Error("taobao-tab-selection-failed");
  if (addressTarget.chain !== MERCHANT_CHAIN) throw new Error(`merchant-chain-mismatch:${addressTarget.chain}`);
  if (isMerchantDownloadCenterState(state.text, addressTarget.chain)) return state;
  if (!isMerchantHomeState(state.text, addressTarget.chain)) {
    const homeId = mainMenuTextId(state.text, "商家首页");
    if (homeId == null) throw new Error("merchant-home-menu-not-found");
    await sky.click({ app: APP, element_index: homeId });
    state = await pollState(sky, (text) => isMerchantHomeState(text, addressTarget.chain), 12_000);
  }
  if (!state || !isMerchantHomeState(state.text, addressTarget.chain)) throw new Error("merchant-home-recovery-failed");
  return state;
}

export async function recoverDownloadNavigationOverlay(sky, state, receipt = {}) {
  if (state?.text.includes("/downloadCenter") || merchantDirectDownloadMenuId(state?.text ?? "") == null) return state;
  if (typeof sky.refresh_app_binding === "function") {
    await sky.refresh_app_binding({ app: APP });
    receipt.menuRebindBeforeCancel = (receipt.menuRebindBeforeCancel ?? 0) + 1;
    state = await sky.get_app_state({ app: APP, disableDiff: true });
  }
  if (!state?.text.includes("/downloadCenter") && merchantDirectDownloadMenuId(state?.text ?? "") != null) {
    await sky.perform_secondary_action({ app: APP, element_index: 0, action: "Cancel" });
    receipt.menuSemanticCancelAfterNavigation = (receipt.menuSemanticCancelAfterNavigation ?? 0) + 1;
  }
  return pollState(sky, (text) => text.includes("/downloadCenter"), 12_000);
}

async function navigateDownloadCenter(sky, state, workDir, receipt) {
  if (!state.text.includes("/downloadCenter")) {
    const searchCloseId = globalSearchCloseButtonId(state.text);
    if (searchCloseId != null) {
      await sky.click({ app: APP, element_index: searchCloseId });
      state = await pollState(sky, (text) => globalSearchCloseButtonId(text) == null, 2_000) ?? state;
    }
    const dataCenterId = mainMenuTextId(state.text, "数据中心");
    if (dataCenterId != null) {
      await sky.click({ app: APP, element_index: dataCenterId });
      state = await pollState(sky, (text) => downloadCenterSubmenuId(text) != null, 4_000);
      const downloadId = downloadCenterSubmenuId(state?.text ?? "");
      if (downloadId != null) {
        await sky.click({ app: APP, element_index: downloadId });
        state = await pollState(sky, (text) => text.includes("/downloadCenter")
          || merchantDirectDownloadMenuId(text) != null, 4_000);
        if (!state?.text.includes("/downloadCenter") && merchantDirectDownloadMenuId(state?.text ?? "") != null) {
          state = await recoverDownloadNavigationOverlay(sky, state, receipt);
        }
      }
    }
    if (!state?.text.includes("/downloadCenter")) {
      state = await sky.get_app_state({ app: APP, disableDiff: true });
    }
    if (!state?.text.includes("/downloadCenter")) {
      const searchLine = findLine(state?.text ?? "", (line) => /^\s*\d+ 文本栏 \(settable\).*搜功能、订单/.test(line));
      const searchId = elementId(searchLine, "文本栏");
      if (searchId != null) {
        await sky.set_value({ app: APP, element_index: searchId, value: "数据下载" });
        state = await pollState(sky, (text) => globalSearchFunctionResultId(text, "数据下载") != null, 4_000);
        const resultId = globalSearchFunctionResultId(state?.text ?? "", "数据下载");
        if (resultId != null) {
          await sky.click({ app: APP, element_index: resultId });
          state = await pollState(sky, (text) => text.includes("/downloadCenter"), 8_000);
        }
      }
    }
    if (!state?.text.includes("/downloadCenter")) {
      if (typeof sky.refresh_app_binding === "function") {
        await sky.refresh_app_binding({ app: APP });
        state = await pollState(sky, (text) => text.includes("/downloadCenter"), 4_000)
          ?? await sky.get_app_state({ app: APP, disableDiff: true });
      }
    }
    if (!state?.text.includes("/downloadCenter")) throw new Error("merchant-download-center-recovery-failed");
  }
  state = await pollState(sky, (text) => text.includes("/downloadCenter") && text.includes("报表下载")
    && (text.includes("门店下载") || text.includes("订单类型")), 12_000);
  if (!state?.text.includes("/downloadCenter") || !(state.text.includes("门店下载") || state.text.includes("订单类型"))) {
    throw new Error("download-center-content-not-ready");
  }
  return state;
}

function pageMatches(text, type, businessDate) {
  const specific = type === "store"
    ? ["粒度", "订单类型", "渠道", "店铺"]
    : ["评价时间", "评价内容", "订单详情"];
  const dateFieldMatches = (placeholder) => text.split("\n").some((line) =>
    line.includes("文本栏")
      && line.includes(`Value: ${businessDate}`)
      && line.includes(`Placeholder: ${placeholder}`));
  return text.includes("/downloadCenter")
    && dateFieldMatches("开始日期")
    && dateFieldMatches("结束日期")
    && text.includes("文本 全部门店")
    && /复选框 全选 .*Value: 1/.test(text)
    && specific.every((token) => text.includes(token));
}

export function selectAllCheckboxState(text) {
  const lines = text.split("\n").filter((line) => /\d+ 复选框 全选 .*Value: [01]/.test(line));
  if (lines.length !== 1) return null;
  const id = elementId(lines[0], "复选框");
  const value = Number(lines[0].match(/Value: ([01])/)?.[1]);
  return id == null || !Number.isInteger(value) ? null : { id, value };
}

export function downloadScrollTargetId(text) {
  const lines = text.split("\n").filter((line) => /\d+ container \(showing \d+-\d+ of \d+ items\)/.test(line));
  const ids = [...new Set(lines.map((line) => Number(line.match(/(\d+) container/)?.[1])).filter(Number.isFinite))];
  return ids.length === 1 ? ids[0] : null;
}

async function innerScroll(sky, state, direction, pages) {
  const id = downloadScrollTargetId(state.text);
  if (id == null) throw new Error("download-inner-scroll-target-missing");
  await sky.scroll({ app: APP, element_index: id, direction, pages });
  return sky.get_app_state({ app: APP, disableDiff: true });
}

async function configureReport(sky, state, type, businessDate, receipt) {
  state = await innerScroll(sky, state, "up", 10);
  await clickOcrExact(sky, state, type === "store" ? "门店下载" : "评价下载");
  state = await pollState(sky, (text) => type === "store" ? text.includes("订单类型") : text.includes("评价时间"), 4_000);
  if (!state) throw new Error(`${type}-tab-selection-failed`);
  await clickExactText(sky, state, "按天");
  state = await sky.get_app_state({ app: APP, disableDiff: true });
  await clickExactText(sky, state, "昨日");
  state = await sky.get_app_state({ app: APP, disableDiff: true });
  await clickExactText(sky, state, "全部门店");
  receipt.explicitStoreScopeSelections[type] += 1;
  await new Promise((resolve) => setTimeout(resolve, 400));
  state = await sky.get_app_state({ app: APP, disableDiff: true });
  for (let attempt = 0; attempt < 2; attempt += 1) {
    let checkbox = selectAllCheckboxState(state.text);
    if (checkbox == null) {
      state = await pollState(sky, (text) => selectAllCheckboxState(text) != null, 2_000);
      checkbox = selectAllCheckboxState(state?.text ?? "");
    }
    if (checkbox == null) throw new Error(`${type}-select-all-not-found`);
    if (checkbox.value === 0) {
      receipt.selectAllAttempts[type] += 1;
      await sky.click({ app: APP, element_index: checkbox.id });
      state = await pollState(sky, (text) => selectAllCheckboxState(text)?.value === 1, 2_500);
    }
    await new Promise((resolve) => setTimeout(resolve, 450));
    state = await sky.get_app_state({ app: APP, disableDiff: true });
    if (pageMatches(state.text, type, businessDate)) return state;
  }
  state = await pollState(sky, (text) => pageMatches(text, type, businessDate), 4_000);
  if (!state || !pageMatches(state.text, type, businessDate)) throw new Error(`${type}-filter-contract-failed`);
  return state;
}

async function configureReportWithRecovery(sky, state, type, businessDate, receipt) {
  try {
    return await configureReport(sky, state, type, businessDate, receipt);
  } catch (error) {
    if (!String(error).includes("noWindowsAvailable") || receipt.clickAttempts[type] !== 0) throw error;
    receipt.retryCount += 1;
    state = await sky.get_app_state({ app: APP, disableDiff: true });
    return configureReport(sky, state, type, businessDate, receipt);
  }
}

async function inventory(directory) {
  const entries = await fs.readdir(directory, { withFileTypes: true });
  return new Set(entries.filter((entry) => entry.isFile()).map((entry) => entry.name));
}

async function sha256File(file) {
  const digest = crypto.createHash("sha256");
  digest.update(await fs.readFile(file));
  return digest.digest("hex");
}

async function validateXlsx(file) {
  const { stdout } = await execFile("/usr/bin/unzip", ["-Z1", file], { maxBuffer: 8 * 1024 * 1024 });
  const names = new Set(stdout.split("\n"));
  if (!names.has("[Content_Types].xml") || !names.has("xl/workbook.xml")) throw new Error("xlsx-structure-invalid");
}

async function waitForNewReport(directory, baseline, type, businessDate, timeoutMs = 55_000) {
  const pattern = sourceReportPattern(type, businessDate);
  const deadline = performance.now() + timeoutMs;
  let priorSize = null;
  let stableCount = 0;
  while (performance.now() <= deadline) {
    const names = [...await inventory(directory)].filter((name) => !baseline.has(name) && pattern.test(name));
    if (names.length > 1) throw new Error(`${type}-new-report-ambiguous:${names.length}`);
    if (names.length === 1) {
      const file = path.join(directory, names[0]);
      const stat = await fs.stat(file);
      stableCount = stat.size > 0 && stat.size === priorSize ? stableCount + 1 : 0;
      priorSize = stat.size;
      if (stableCount >= 2) {
        await validateXlsx(file);
        const normalizedName = normalizedReportName(type, businessDate, names[0]);
        const normalizedFile = path.join(directory, normalizedName);
        try {
          await fs.access(normalizedFile);
          throw new Error(`${type}-normalized-file-already-exists`);
        } catch (error) {
          if (error?.code !== "ENOENT") throw error;
        }
        await fs.rename(file, normalizedFile);
        return { file: normalizedFile, name: normalizedName, size: stat.size, sha256: await sha256File(normalizedFile) };
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 400));
  }
  throw new Error(`${type}-download-result-unknown`);
}

export async function normalizeCompletedDownloadReceipt(receiptFile = "/tmp/zhensi_daily_download/download_receipt.json") {
  rejectLegacyExecution();
  const receipt = JSON.parse(await fs.readFile(receiptFile, "utf8"));
  if (receipt.ok !== true || !/^\d{4}-\d{2}-\d{2}$/.test(receipt.businessDate ?? "")) throw new Error("download-receipt-not-ready");
  for (const type of ["store", "review"]) {
    const item = receipt[type];
    if (!item?.file || !item?.sha256) throw new Error(`${type}-receipt-entry-missing`);
    let file = path.resolve(item.file);
    let name = path.basename(file);
    const stat = await fs.stat(file);
    if (!stat.isFile() || stat.size !== item.size) throw new Error(`${type}-file-size-changed`);
    await validateXlsx(file);
    if (await sha256File(file) !== item.sha256) throw new Error(`${type}-file-hash-changed`);
    if (!reportPattern(type, receipt.businessDate).test(name)) {
      const normalizedName = normalizedReportName(type, receipt.businessDate, name);
      const normalizedFile = path.join(path.dirname(file), normalizedName);
      try {
        await fs.access(normalizedFile);
        throw new Error(`${type}-normalized-file-already-exists`);
      } catch (error) {
        if (error?.code !== "ENOENT") throw error;
      }
      await fs.rename(file, normalizedFile);
      file = normalizedFile;
      name = normalizedName;
    }
    receipt[type] = { ...item, file, name };
  }
  receipt.filenameFormat = "single-business-date";
  await writeReceipt(receiptFile, receipt);
  return receipt;
}

async function validatedReportInfo(file, type, businessDate) {
  const resolved = path.resolve(file);
  const name = path.basename(resolved);
  if (!reportPattern(type, businessDate).test(name)) throw new Error(`${type}-resume-file-contract-failed`);
  const stat = await fs.stat(resolved);
  if (!stat.isFile() || stat.size <= 0) throw new Error(`${type}-resume-file-invalid`);
  await validateXlsx(resolved);
  return { file: resolved, name, size: stat.size, sha256: await sha256File(resolved), resumed: true };
}

async function clickDownloadOnce(sky, state, receipt, type, baseline, directory, businessDate) {
  receipt.clickAttempts[type] = 1;
  await clickOcrExact(sky, state, "下载数据");
  return waitForNewReport(directory, baseline, type, businessDate);
}

async function writeReceipt(file, receipt) {
  await fs.mkdir(path.dirname(file), { recursive: true });
  const temporary = `${file}.${Date.now()}.tmp`;
  await fs.writeFile(temporary, `${JSON.stringify(receipt, null, 2)}\n`, { mode: 0o600 });
  await fs.rename(temporary, file);
}

export async function runDownloadExecutor({
  sky,
  downloadDir = path.join(os.homedir(), "Downloads"),
  receiptFile = "/tmp/zhensi_daily_download/download_receipt.json",
  businessDate = yesterdayInShanghai(),
  resumeStoreFile = null,
  initialState = null,
} = {}) {
  rejectLegacyExecution();
  if (!sky) throw new Error("sky-is-required");
  const started = performance.now();
  const receipt = {
    ok: false,
    executor: "taobao-download",
    businessDate,
    stageMs: {},
    clickAttempts: { store: 0, review: 0 },
    explicitStoreScopeSelections: { store: 0, review: 0 },
    selectAllAttempts: { store: 0, review: 0 },
    retryCount: 0,
  };
  const workDir = await fs.mkdtemp(path.join(os.tmpdir(), "zhensi-download-"));
  try {
    let end = stageTimer(receipt, "preflight");
    await fs.access(downloadDir);
    let state = initialState ?? await sky.get_app_state({ app: APP, disableDiff: true });
    receipt.initialStateSource = initialState ? "chrome-front-gate" : "download-executor-read";
    state = await closeChromeMenu(sky, state);
    if (isMerchantMenuOnlyState(state.text) && typeof sky.refresh_app_binding === "function") {
      await sky.refresh_app_binding({ app: APP });
      state = await sky.get_app_state({ app: APP, disableDiff: true });
    }
    state = await selectTaobaoTab(sky, state);
    receipt.merchantTabActivation = "cua-ui-tree";
    end();

    end = stageTimer(receipt, "focus_target");
    state = await closeChromeMenu(sky, state);
    if (!state.text.includes("melody.shop.ele.me")) throw new Error("taobao-target-focus-lost");
    state = await dismissMerchantMenuOnly(sky, state);
    if (!state.text.includes("melody.shop.ele.me")) throw new Error("taobao-target-lost-after-focus-recovery");
    end();

    end = stageTimer(receipt, "navigate_download_center");
    state = await navigateDownloadCenter(sky, state, workDir, receipt);
    end();

    end = stageTimer(receipt, "download_store");
    if (resumeStoreFile) {
      receipt.store = await validatedReportInfo(resumeStoreFile, "store", businessDate);
    } else {
      const storeBaseline = await inventory(downloadDir);
      state = await configureReportWithRecovery(sky, state, "store", businessDate, receipt);
      receipt.store = await clickDownloadOnce(sky, state, receipt, "store", storeBaseline, downloadDir, businessDate);
    }
    end();

    end = stageTimer(receipt, "download_review");
    state = await sky.get_app_state({ app: APP, disableDiff: true });
    const reviewBaseline = await inventory(downloadDir);
    state = await configureReportWithRecovery(sky, state, "review", businessDate, receipt);
    receipt.review = await clickDownloadOnce(sky, state, receipt, "review", reviewBaseline, downloadDir, businessDate);
    end();

    receipt.ok = true;
    receipt.elapsedMs = Math.round(performance.now() - started);
    await writeReceipt(receiptFile, receipt);
    return receipt;
  } catch (error) {
    if (receipt.stageStarted != null && receipt.stage && receipt.stageMs[receipt.stage] == null) {
      receipt.stageMs[receipt.stage] = Math.round(performance.now() - receipt.stageStarted);
    }
    delete receipt.stageStarted;
    receipt.reason = error instanceof Error ? error.message : String(error);
    receipt.elapsedMs = Math.round(performance.now() - started);
    return receipt;
  } finally {
    await fs.rm(workDir, { recursive: true, force: true });
  }
}

export function selfTestDownloadExecutor() {
  if (yesterdayInShanghai(new Date("2026-09-02T12:00:00+08:00")) !== "2026-09-01") throw new Error("date-self-test-failed");
  if (!sourceReportPattern("store", "2026-09-01").test("门店下载_20260901至20260901_全部门店_5296218123_20260902145626472.xlsx")) throw new Error("store-source-pattern-self-test-failed");
  if (!sourceReportPattern("review", "2026-09-01").test("评价下载_20260901至20260901_全部门店_5296218123_20260902145934047.xlsx")) throw new Error("review-source-pattern-self-test-failed");
  if (!reportPattern("store", "2026-09-01").test("门店下载_20260901_全部门店_5296218123_20260902145626472.xlsx")) throw new Error("store-pattern-self-test-failed");
  if (!reportPattern("review", "2026-09-01").test("评价下载_20260901_全部门店_5296218123_20260902145934047.xlsx")) throw new Error("review-pattern-self-test-failed");
  if (normalizedReportName("store", "2026-09-01", "门店下载_20260901至20260901_全部门店_5296218123_20260902145626472.xlsx") !== "门店下载_20260901_全部门店_5296218123_20260902145626472.xlsx") throw new Error("normalize-name-self-test-failed");
  if (targetEntry("store") !== "数据上传" || targetEntry("review") !== "评价上传") throw new Error("mapping-self-test-failed");
  if (pageMatches("/downloadCenter 文本栏 Value: 2026-09-01, Placeholder: 开始日期 文本栏 Value: 2026-09-01, Placeholder: 结束日期 文本 全部门店 复选框 全选  , Value: 1 粒度 订单类型 渠道 店铺", "store", "2026-09-01") !== true) throw new Error("page-contract-self-test-failed");
  const settableContract = "/downloadCenter\n103 文本栏 (settable) Value: 2026-09-01, Placeholder: 开始日期\n105 文本栏 (settable) Value: 2026-09-01, Placeholder: 结束日期\n119 文本 全部门店\n132 复选框 全选  , Value: 1\n粒度 订单类型 渠道 店铺";
  if (!pageMatches(settableContract, "store", "2026-09-01")
    || pageMatches(settableContract.replace("Value: 2026-09-01, Placeholder: 结束日期", "Value: 2026-08-31, Placeholder: 结束日期"), "store", "2026-09-01")) throw new Error("page-settable-contract-self-test-failed");
  const mainMenu = "40 菜单 Secondary Actions: Cancel\n  41 商家首页\n    42 文本 商家首页\n  43 数据中心\n    44 文本 数据中心\n  45 财务管理\n    46 文本 财务管理\n  47 安全中心\n    48 文本 安全中心";
  const correctMenu = "90 文本 数据中心\n  91 菜单 Secondary Actions: Cancel\n    92 数据下载\n      93 文本 数据下载";
  const wrongMenu = "90 文本 编辑\n  91 菜单 Secondary Actions: Cancel\n    92 数据下载";
  if (scopedSubmenuItemId(correctMenu, "数据中心", "数据下载") !== 92 || scopedSubmenuTextId(correctMenu, "数据中心", "数据下载") !== 93 || scopedSubmenuItemId(wrongMenu, "数据中心", "数据下载") !== null || mainMenuTextId(`${mainMenu}\n${correctMenu}`, "数据中心") !== 44) throw new Error("scoped-submenu-self-test-failed");
  const searchResult = "29 文本栏 (settable) Value: 数据下载, Placeholder: 搜功能、订单(订单号)、帮助\n40 container 综合\n  41 container\n    42 文本 功能\n    44 图像 数据下载\n    45 文本 数据下载\n    46 文本 数据中心\n128 菜单 Secondary Actions: Cancel\n  129 文本 数据下载";
  if (globalSearchFunctionResultId(searchResult, "数据下载") !== 45) throw new Error("global-search-scope-self-test-failed");
  if (globalSearchFunctionResultId(searchResult.replace("42 文本 功能", "42 文本 帮助"), "数据下载") !== null) throw new Error("global-search-group-self-test-failed");
  const searchOverlay = "27 container\n  28 container\n    29 文本栏 (settable) Value: 数据下载, Placeholder: 搜功能、订单(订单号)、帮助\n    30 按钮 close-circle\n      31 图像 close-circle\n  32 按钮 搜 索";
  if (globalSearchCloseButtonId(searchOverlay) !== 30 || globalSearchCloseButtonId(searchOverlay.replace("Value: 数据下载, ", "")) !== null) throw new Error("global-search-close-self-test-failed");
  const merchantMenu = 'Window: "“淘宝闪购商家版”🔊", App: Google Chrome.\n0 菜单 Secondary Actions: Cancel\n    7 数据下载\n        8 文本 数据下载';
  if (merchantDirectDownloadMenuId(merchantMenu) !== 8
    || merchantDirectDownloadMenuId(merchantMenu.replace("淘宝闪购商家版", "淘宝闪购服务商平台")) !== null
    || merchantDirectDownloadMenuId(`${merchantMenu}\n    9 数据下载`) !== null
    || merchantDirectDownloadMenuId(`${merchantMenu}\n        11 文本 数据下载`) !== null) throw new Error("merchant-direct-download-menu-self-test-failed");
  if (downloadCenterSubmenuId(correctMenu) !== 93 || downloadCenterSubmenuId(merchantMenu) !== 8) throw new Error("download-center-submenu-shape-self-test-failed");
  const merchantPage = 'Window: "淘宝闪购商家版", App: Google Chrome.\n9 文本栏 (settable) Description: 地址和搜索栏, Value: melody.shop.ele.me/app/chain/95708808/dashboard#app.chainshop.dashboard, Placeholder: 问问 Google 或输入网址';
  const addressTarget = merchantDownloadCenterTarget(merchantPage);
  if (addressTarget?.id !== 9 || addressTarget.chain !== "95708808"
    || addressTarget.homeUrl !== "https://melody.shop.ele.me/app/chain/95708808/dashboard#app.chainshop.dashboard"
    || addressTarget.url !== "https://melody.shop.ele.me/app/chain/95708808/downloadCenter#app.chainshop.downloadCenter"
    || merchantDownloadCenterTarget(merchantPage.replace("淘宝闪购商家版", "淘宝闪购服务商平台")) !== null) throw new Error("merchant-address-target-self-test-failed");
  const merchantHome = `${merchantPage}\n42 文本 商家首页`;
  const merchantDownload = merchantPage.replace("dashboard#app.chainshop.dashboard", "downloadCenter#app.chainshop.downloadCenter");
  if (!isMerchantHomeState(merchantHome)
    || isMerchantHomeState(merchantHome.replace("dashboard", "downloadCenter"))
    || isMerchantHomeState(merchantHome.replace("淘宝闪购商家版", "淘宝闪购服务商平台"))) throw new Error("merchant-home-state-self-test-failed");
  if (!isMerchantDownloadCenterState(merchantDownload)
    || isMerchantDownloadCenterState(merchantDownload.replace("95708808", "95708809"))
    || isMerchantDownloadCenterState(merchantDownload.replace("淘宝闪购商家版", "淘宝闪购服务商平台"))) throw new Error("merchant-download-center-state-self-test-failed");
  const menuOnly = 'Window: "淘宝闪购商家版", App: Google Chrome.\n0 菜单 Secondary Actions: Cancel\n  1 商家首页\n  2 数据中心';
  if (!isMerchantMenuOnlyState(menuOnly)
    || isMerchantMenuOnlyState(menuOnly.replace("淘宝闪购商家版", "淘宝闪购服务商平台"))
    || isMerchantMenuOnlyState(`${menuOnly}\n9 文本栏 (settable) Description: 地址和搜索栏, Value: melody.shop.ele.me/`)) throw new Error("merchant-menu-only-self-test-failed");
  const scrollState = "91 HTML 内容 melody-stats-new, URL: melody-stats-next.ele.me/new/#/download-center\n  101 container (showing 0-100 of 144 items)";
  if (downloadScrollTargetId(scrollState) !== 101
    || downloadScrollTargetId(`${scrollState}\n  102 container (showing 0-10 of 20 items)`) !== null) throw new Error("download-scroll-target-self-test-failed");
  const selectAll = "123 复选框 全选  , Value: 0";
  if (selectAllCheckboxState(selectAll)?.id !== 123 || selectAllCheckboxState(selectAll)?.value !== 0
    || selectAllCheckboxState(selectAll.replace("Value: 0", "Value: 1"))?.value !== 1
    || selectAllCheckboxState(`${selectAll}\n124 复选框 全选  , Value: 1`) !== null) throw new Error("select-all-state-self-test-failed");
  return { ok: true, tests: 26 };
}

export async function selfTestDownloadNavigationRecovery() {
  const menu = { text: 'Window: "淘宝闪购商家版", App: Google Chrome.\n0 菜单 Secondary Actions: Cancel\n  7 数据下载\n    8 文本 数据下载' };
  const page = { text: 'Window: "淘宝闪购商家版", App: Google Chrome.\n9 文本栏 (settable) Description: 地址和搜索栏, Value: melody.shop.ele.me/app/chain/95708808/downloadCenter#app.chainshop.downloadCenter' };
  const calls = [];
  let readCount = 0;
  const sky = {
    async refresh_app_binding() { calls.push("refresh"); return true; },
    async get_app_state() { calls.push("state"); readCount += 1; return readCount === 1 ? menu : page; },
    async perform_secondary_action(args) { calls.push(`secondary:${args.action}:${args.element_index}`); },
    async click() { calls.push("coordinate-or-element-click"); },
  };
  const receipt = {};
  const recovered = await recoverDownloadNavigationOverlay(sky, menu, receipt);
  if (!recovered?.text.includes("/downloadCenter")
    || calls.join(",") !== "refresh,state,secondary:Cancel:0,state"
    || receipt.menuRebindBeforeCancel !== 1
    || receipt.menuSemanticCancelAfterNavigation !== 1) throw new Error("download-navigation-overlay-recovery-self-test-failed");
  return { ok: true, tests: 1 };
}

const runtimeProcess = globalThis.process;
const invokedPath = runtimeProcess?.argv?.[1];
if (invokedPath && import.meta.url === pathToFileURL(invokedPath).href && runtimeProcess.argv.includes("--self-test")) {
  const pure = selfTestDownloadExecutor();
  const navigation = await selfTestDownloadNavigationRecovery();
  runtimeProcess.stdout.write(`${JSON.stringify({ ok: true, tests: pure.tests + navigation.tests })}\n`);
}
