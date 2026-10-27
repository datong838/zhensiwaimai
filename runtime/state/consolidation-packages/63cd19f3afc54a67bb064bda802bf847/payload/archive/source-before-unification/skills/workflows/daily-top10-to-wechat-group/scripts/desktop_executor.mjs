#!/usr/bin/env node

import { execFile as execFileCallback } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { promisify } from "node:util";

const execFile = promisify(execFileCallback);
const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const OCR_BIN = path.join(SCRIPT_DIR, "ocr_vision");
const BASELINE = Object.freeze({ width: 2336, height: 1510, x: 570, y: 300, cropWidth: 1500, cropHeight: 1180 });
const BANNED_OCR = /(顾客|手机号|已下\d*单|补充备注|催单|投诉|退了|少了|发票申请)/;

export function elementId(line, role) {
  if (!line) return null;
  const match = line.match(new RegExp(`(\\d+) ${role}`));
  return match ? Number(match[1]) : null;
}

export function findLine(text, predicate) {
  return text.split("\n").find(predicate) ?? null;
}

export function isStoreAnalysis(text) {
  return text.includes("/store-analysis");
}

export function isYesterdaySelected(text) {
  return /单选按钮 昨日, Value: 1/.test(text);
}

export function fullscreenMenuStatus(text) {
  if (/^\s*\d+ 退出全屏幕(?:,|$)/m.test(text)) return "fullscreen";
  if (/^\s*\d+ 进入全屏幕(?:,|$)/m.test(text)) return "windowed";
  return "unknown";
}

export function parseTop10(text) {
  const blocks = text.split(/\n(?=\t+\d+ row\b)/);
  const rows = [];
  for (const block of blocks) {
    if (!block.includes("链接 门店详情")) continue;
    const lines = block.split("\n");
    const storeLine = lines.find((line) => /\d+ (?:文本|text) /.test(line) && !/门店详情|竞争分析/.test(line));
    const moneyLine = lines.find((line) => /\btext\s+[\d,]+\.\d{2}(?:\s|$)/.test(line));
    const rankLine = lines.find((line) => /第\s*\d+\s*名/.test(line));
    if (!storeLine || !moneyLine) continue;
    const store = storeLine.replace(/^.*?\d+ (?:文本|text)\s+/, "").trim();
    const revenueMatch = moneyLine.match(/\btext\s+([\d,]+\.\d{2})/);
    if (!revenueMatch) continue;
    rows.push({
      store,
      rank: rankLine?.replace(/^.*?\d+ (?:文本|text)\s+/, "").trim() ?? null,
      revenue: Number(revenueMatch[1].replaceAll(",", "")),
    });
  }
  return rows.slice(0, 10);
}

export function isNonIncreasing(values) {
  return values.every((value, index) => index === 0 || values[index - 1] >= value);
}

export function scrollTargetId(text) {
  const lines = text.split("\n");
  const inner = lines.find((line) => line.includes("HTML 内容 melody-stats-new"));
  const outer = lines.find((line) => line.includes("HTML 内容 淘宝闪购商家版") && line.includes("/store-analysis"));
  return elementId(inner ?? outer, "HTML 内容");
}

export function isFirstPageTenRows(text) {
  return text.includes("内容列表") && text.includes("10 条/页")
    && /按钮 \(disabled\) left/.test(text) && /\n\s+\d+ 文本 1(?:\n|$)/.test(text);
}

export function hasPagerEvidence(ocrText, imageHeight) {
  const bottomTexts = ocrText.split("\n").flatMap((line) => {
    const [box, , content = ""] = line.split("\t", 3);
    const y = Number(box?.split(",")?.[1]);
    return Number.isFinite(y) && y >= imageHeight - 80 ? [content.replaceAll(" ", "")] : [];
  });
  return bottomTexts.some((text) => text.startsWith("10")) && bottomTexts.some((text) => text.includes("跳至"));
}

export function obstructionCloseId(text) {
  const lines = text.split("\n");
  const messageIndex = lines.findIndex((line) => /已下\d+单|收藏门店|顾客.*(?:发票|备注|催单|投诉)/.test(line));
  if (messageIndex < 0) return null;
  const nearby = lines.slice(Math.max(0, messageIndex - 4), messageIndex + 9);
  const closeLine = nearby.find((line) => /(?:按钮|图像) close/.test(line));
  return elementId(closeLine, closeLine?.includes("按钮 close") ? "按钮" : "图像");
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

async function pollState(sky, predicate, timeoutMs, intervalMs = 180) {
  const deadline = performance.now() + timeoutMs;
  let latest = null;
  do {
    latest = await sky.get_app_state({ app: "com.google.Chrome", disableDiff: true });
    if (predicate(latest.text)) return latest;
    if (performance.now() >= deadline) break;
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  } while (true);
  return latest;
}

async function openViewMenu(sky, state) {
  const viewLine = findLine(state.text, (line) => /^\s*\d+ 显示$/.test(line));
  const viewId = Number(viewLine?.match(/(\d+) 显示$/)?.[1]);
  if (!Number.isFinite(viewId)) return null;
  await sky.click({ app: "com.google.Chrome", element_index: viewId });
  return sky.get_app_state({ app: "com.google.Chrome", disableDiff: true });
}

async function closeChromeMenu(sky, state) {
  if (!/^\s*0 显示(?:,|$)/m.test(state.text)) return state;
  await sky.perform_secondary_action({ app: "com.google.Chrome", element_index: 0, action: "Cancel" });
  const page = await pollState(sky, (text) => /URL: .*melody\.shop\.ele\.me/.test(text), 2_000);
  if (!page || /^\s*0 显示(?:,|$)/m.test(page.text)) throw new Error("chrome-menu-not-closed");
  return page;
}

async function ensureChromeFullscreen(sky, state) {
  state = await closeChromeMenu(sky, state);
  let menu = await openViewMenu(sky, state);
  if (menu == null) return state;
  let status = fullscreenMenuStatus(menu.text);
  if (status === "windowed") {
    const enterLine = findLine(menu.text, (line) => /^\s*\d+ 进入全屏幕(?:,|$)/.test(line));
    const enterId = Number(enterLine?.match(/(\d+) 进入全屏幕/)?.[1]);
    if (!Number.isFinite(enterId)) throw new Error("chrome-enter-fullscreen-not-found");
    await sky.click({ app: "com.google.Chrome", element_index: enterId });
    await new Promise((resolve) => setTimeout(resolve, 700));
    state = await sky.get_app_state({ app: "com.google.Chrome", disableDiff: true });
    menu = await openViewMenu(sky, state);
    if (menu == null) return state;
    status = fullscreenMenuStatus(menu.text);
  }
  if (status !== "fullscreen") throw new Error(`chrome-fullscreen-not-verified:${status}`);
  return closeChromeMenu(sky, menu);
}

function stageTimer(receipt, name) {
  const started = performance.now();
  return () => { receipt.stageMs[name] = Math.round(performance.now() - started); };
}

async function dimensions(file) {
  const { stdout } = await execFile("/usr/bin/sips", ["-g", "pixelWidth", "-g", "pixelHeight", file]);
  const width = Number(stdout.match(/pixelWidth:\s*(\d+)/)?.[1]);
  const height = Number(stdout.match(/pixelHeight:\s*(\d+)/)?.[1]);
  return { width, height };
}

async function captureAndCrop(outputDir, dataDate) {
  await fs.mkdir(outputDir, { recursive: true });
  const raw = path.join(outputDir, `${dataDate}_top10seller.raw.png`);
  const output = path.join(outputDir, `${dataDate}_top10seller.png`);
  await execFile("/usr/sbin/screencapture", ["-x", raw]);
  const source = await dimensions(raw);
  if (source.width < BASELINE.width || source.height < BASELINE.height) {
    throw new Error(`screen-too-small:${source.width}x${source.height}`);
  }
  const scaleX = source.width / BASELINE.width;
  const scaleY = source.height / BASELINE.height;
  const cropWidth = Math.round(BASELINE.cropWidth * scaleX);
  const cropHeight = Math.round(BASELINE.cropHeight * scaleY);
  const x = Math.round(BASELINE.x * scaleX);
  const y = Math.round(BASELINE.y * scaleY);
  await execFile("/usr/bin/sips", [
    "-c", String(cropHeight), String(cropWidth), "--cropOffset", String(y), String(x), raw, "--out", output,
  ]);
  return { raw, output, source, crop: await dimensions(output) };
}

async function runOcr(file) {
  const { stdout } = await execFile(OCR_BIN, [file, "zh-Hans"], { maxBuffer: 8 * 1024 * 1024 });
  return stdout;
}

async function writeReceipt(file, receipt) {
  await fs.mkdir(path.dirname(file), { recursive: true });
  const temporary = `${file}.${Date.now()}.${Math.random().toString(16).slice(2)}.tmp`;
  await fs.writeFile(temporary, `${JSON.stringify(receipt, null, 2)}\n`, { mode: 0o600 });
  await fs.rename(temporary, file);
}

export async function runDesktopExecutor({
  sky,
  outputDir = "/tmp/zhensi_top10",
  receiptFile = "/tmp/zhensi_top10/desktop_receipt.json",
  navigationTimeoutMs = 10_000,
  dataTimeoutMs = 12_000,
} = {}) {
  if (!sky) throw new Error("sky is required");
  const started = performance.now();
  const receipt = { ok: false, executor: "desktop", stageMs: {}, retryCount: 0 };
  let stage = "preflight";
  try {
    let end = stageTimer(receipt, stage);
    let state = await sky.get_app_state({ app: "com.google.Chrome", disableDiff: true });
    state = await closeChromeMenu(sky, state);
    end();

    stage = "focus_fullscreen";
    end = stageTimer(receipt, stage);
    state = await ensureChromeFullscreen(sky, state);
    end();

    stage = "navigate_store_analysis";
    end = stageTimer(receipt, stage);
    if (!isStoreAnalysis(state.text)) {
      const linkLine = findLine(state.text, (line) => line.includes("链接 门店分析"));
      const linkId = elementId(linkLine, "链接");
      if (linkId == null) throw new Error("store-analysis-link-not-found");
      await sky.click({ app: "com.google.Chrome", element_index: linkId });
      state = await pollState(sky, isStoreAnalysis, navigationTimeoutMs);
      if (!state || !isStoreAnalysis(state.text)) throw new Error("store-analysis-timeout");
    }
    end();

    stage = "select_yesterday";
    end = stageTimer(receipt, stage);
    if (!isYesterdaySelected(state.text)) {
      state = await pollState(sky, (text) => text.includes("单选按钮 昨日"), navigationTimeoutMs);
      const yesterdayLine = findLine(state?.text ?? "", (line) => line.includes("单选按钮 昨日"));
      const yesterdayId = elementId(yesterdayLine, "单选按钮");
      if (yesterdayId == null) throw new Error("yesterday-control-not-found");
      await sky.click({ app: "com.google.Chrome", element_index: yesterdayId });
      state = await pollState(sky, isYesterdaySelected, navigationTimeoutMs);
      if (!state || !isYesterdaySelected(state.text)) throw new Error("yesterday-selection-timeout");
    }
    end();

    stage = "verify_sort";
    end = stageTimer(receipt, stage);
    state = await pollState(sky, (text) => parseTop10(text).length === 10, dataTimeoutMs);
    let rows = parseTop10(state?.text ?? "");
    if (rows.length !== 10) throw new Error(`top10-row-count:${rows.length}`);
    if (!isNonIncreasing(rows.map((row) => row.revenue))) {
      const revenueHeader = findLine(state.text, (line) => line.includes("列标题") && line.includes("营业额"));
      const revenueHeaderId = elementId(revenueHeader, "列标题");
      if (revenueHeaderId == null) throw new Error("revenue-header-not-found");
      receipt.retryCount += 1;
      await sky.click({ app: "com.google.Chrome", element_index: revenueHeaderId });
      state = await pollState(sky, (text) => {
        const parsed = parseTop10(text);
        return parsed.length === 10 && isNonIncreasing(parsed.map((row) => row.revenue));
      }, dataTimeoutMs);
      rows = parseTop10(state?.text ?? "");
      if (rows.length !== 10 || !isNonIncreasing(rows.map((row) => row.revenue))) throw new Error("revenue-sort-failed");
    }
    end();

    stage = "layout";
    end = stageTimer(receipt, stage);
    await sky.press_key({ app: "com.google.Chrome", key: "super+0" });
    for (let index = 0; index < 4; index += 1) await sky.press_key({ app: "com.google.Chrome", key: "super+minus" });
    state = await pollState(sky, (text) => scrollTargetId(text) != null, 4_000);
    const targetId = scrollTargetId(state?.text ?? "");
    if (targetId == null) {
      receipt.layoutFallback = "app-end-up";
      await sky.press_key({ app: "com.google.Chrome", key: "End" });
      await sky.press_key({ app: "com.google.Chrome", key: "Up" });
    } else {
      await sky.scroll({ app: "com.google.Chrome", element_index: targetId, direction: "down", pages: 5 });
      await sky.scroll({ app: "com.google.Chrome", element_index: targetId, direction: "up", pages: 0.08 });
    }
    state = await pollState(sky, (text) => {
      const parsed = parseTop10(text);
      return isStoreAnalysis(text) && isYesterdaySelected(text) && isFirstPageTenRows(text) && parsed.length === 10
        && isNonIncreasing(parsed.map((row) => row.revenue));
    }, 4_000);
    if (!state || !isStoreAnalysis(state.text) || !isYesterdaySelected(state.text)
      || !isFirstPageTenRows(state.text) || parseTop10(state.text).length !== 10) {
      throw new Error("layout-postcondition-failed");
    }
    end();

    stage = "clear_obstruction";
    end = stageTimer(receipt, stage);
    for (let attempt = 0; attempt < 2; attempt += 1) {
      state = await sky.get_app_state({ app: "com.google.Chrome", disableDiff: true });
      const closeId = obstructionCloseId(state.text);
      if (closeId == null) break;
      receipt.retryCount += attempt === 1 ? 1 : 0;
      await sky.click({ app: "com.google.Chrome", element_index: closeId });
    }
    end();

    stage = "capture_self_check";
    end = stageTimer(receipt, stage);
    const dataDate = yesterdayInShanghai();
    const capture = await captureAndCrop(outputDir, dataDate);
    if (capture.crop.width < 1500) throw new Error(`crop-width:${capture.crop.width}`);
    const ocr = await runOcr(capture.output);
    if (BANNED_OCR.test(ocr)) throw new Error("privacy-ocr-hit");
    const normalizedOcr = ocr.replaceAll(" ", "");
    for (const required of ["门店名称", "营业额", "有效订单"]) {
      if (!normalizedOcr.includes(required)) throw new Error(`ocr-required-missing:${required}`);
    }
    if (!hasPagerEvidence(ocr, capture.crop.height)) throw new Error("pager-not-visible-in-crop");
    const bytes = await fs.readFile(capture.output);
    const sha256 = crypto.createHash("sha256").update(bytes).digest("hex");
    end();

    receipt.ok = true;
    receipt.dataDate = dataDate;
    receipt.file = capture.output;
    receipt.width = capture.crop.width;
    receipt.height = capture.crop.height;
    receipt.sha256 = sha256;
    receipt.page = 1;
    receipt.pageSize = 10;
    receipt.layout = "table-and-pagination-bottom-aligned";
    receipt.revenues = rows.map((row) => row.revenue);
    receipt.stores = rows.map((row) => row.store);
    receipt.elapsedMs = Math.round(performance.now() - started);
    await writeReceipt(receiptFile, receipt);
    return receipt;
  } catch (error) {
    receipt.stage = stage;
    receipt.reason = error instanceof Error ? error.message : String(error);
    receipt.elapsedMs = Math.round(performance.now() - started);
    return receipt;
  }
}

export function selfTestDesktopExecutor() {
  const fixture = [
    "\t315 row",
    "\t\t317 文本 门店甲",
    "\t\t322 text 第 2 名 / 30 名",
    "\t\t324 text 9,359.20 1,122.00",
    "\t\t378 链接 门店详情",
    "\t382 row",
    "\t\t384 文本 门店乙",
    "\t\t389 text 第 7 名 / 429 名",
    "\t\t391 text 8,722.70 1,129.77",
    "\t\t445 链接 门店详情",
  ].join("\n");
  const rows = parseTop10(fixture);
  if (rows.length !== 2 || rows[0].revenue !== 9359.2 || rows[1].store !== "门店乙") throw new Error("parseTop10 self-test failed");
  if (!isNonIncreasing(rows.map((row) => row.revenue))) throw new Error("sort self-test failed");
  if (isNonIncreasing([2, 3])) throw new Error("negative sort self-test failed");
  if (!/^\d{4}-\d{2}-\d{2}$/.test(yesterdayInShanghai())) throw new Error("date self-test failed");
  const targetFixture = "\t17 HTML 内容 淘宝闪购商家版, URL: https://example/store-analysis\n\t119 HTML 内容 melody-stats-new, URL: https://example";
  if (scrollTargetId(targetFixture) !== 119 || scrollTargetId(targetFixture.split("\n")[0]) !== 17) throw new Error("scroll target self-test failed");
  if (!isStoreAnalysis("0 标准窗口 Chrome, URL: https://example/store-analysis") || isStoreAnalysis("门店分析")) throw new Error("store analysis URL self-test failed");
  const pagerFixture = "\t1000 内容列表\n\t1001 按钮 (disabled) left\n\t1002 文本 1\n\t1003 文本 10 条/页";
  if (!isFirstPageTenRows(pagerFixture) || isFirstPageTenRows(pagerFixture.replace("10 条/页", "20 条/页"))) throw new Error("pager self-test failed");
  if (obstructionCloseId("\t10 文本 已下1单\n\t11 图像 close") !== 11) throw new Error("obstruction self-test failed");
  const pagerOcrFixture = "1270,1171,107,14\t0.3\t10冬1V\n1367,1171,39,13\t0.3\t跳至";
  if (!hasPagerEvidence(pagerOcrFixture, 1180) || hasPagerEvidence(pagerOcrFixture.replace("跳至", "其他"), 1180)) throw new Error("pager evidence self-test failed");
  if (fullscreenMenuStatus("11 退出全屏幕, ID: toggleFullScreen:") !== "fullscreen"
    || fullscreenMenuStatus("12 进入全屏幕, ID: toggleFullScreen:") !== "windowed"
    || fullscreenMenuStatus("0 标准窗口 Chrome") !== "unknown") throw new Error("fullscreen self-test failed");
  return { ok: true, tests: 10 };
}

const runtimeProcess = globalThis.process;
const invokedPath = runtimeProcess?.argv?.[1];
if (invokedPath && import.meta.url === pathToFileURL(invokedPath).href && runtimeProcess.argv.includes("--self-test")) {
  runtimeProcess.stdout.write(`${JSON.stringify(selfTestDesktopExecutor())}\n`);
}
